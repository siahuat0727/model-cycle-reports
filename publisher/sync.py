"""Sync successful measurements to an independently authenticated Miaoda app."""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from publisher import report, source, state


def run(args, cwd=None, timeout=300):
    env = {k:v for k,v in os.environ.items() if k not in {
        'GH_TOKEN','GITHUB_TOKEN','SOURCE_ACTIONS_TOKEN','STATE_KEY',
        'SOURCE_REPOSITORY','SOURCE_BRANCH'}}
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                            text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('External operation failed: '+args[0]+'\n'+(result.stdout+result.stderr)[-4000:])
    return result.stdout


class Publisher:
    def __init__(self, payload, sha):
        self.payload, self.sha = payload, sha
        self.app = payload['app_id']

    def persist(self):
        self.payload['credentials'] = state.capture_credentials()
        self.sha = state.save(self.payload, self.sha)

    def api(self, command, *args):
        result = json.loads(run(['lark-cli','apps',command,'--app-id',self.app,
                                 '--as','user',*args], timeout=100))
        if not result.get('ok'):
            raise RuntimeError('Miaoda API operation failed: '+command)
        return result['data']

    def complete(self):
        pending = self.payload['pending']
        deadline = time.monotonic()+300
        while time.monotonic() < deadline:
            release = self.api('+release-get','--release-id',pending['release_id'])
            status = release.get('status')
            if status == 'finished':
                if release.get('commit_id') != pending['commit']:
                    raise RuntimeError('Published commit differs from requested commit')
                self.payload.update(last_source=pending['source'],
                                    published_commit=pending['commit'],
                                    online_url=release.get('online_url'),
                                    release_id=pending['release_id'])
                del self.payload['pending']
                self.persist()
                print('Publication completed; release commit matches the locally verified build',flush=True)
                return
            if status == 'failed':
                del self.payload['pending']
                self.persist()
                raise RuntimeError('Miaoda release failed; next sync can retry')
            time.sleep(20)
        raise RuntimeError('Release still running; next sync will resume verification')

    def resume(self):
        if self.payload.get('unconfirmed'):
            intent=self.payload['unconfirmed']
            matches=[r for r in self.api('+release-list')['releases']
                     if int(r['created_at'])>=intent['started_ms']]
            if len(matches)!=1:
                raise RuntimeError('Uncertain release requires private reconciliation')
            self.payload['pending']={**self.payload.pop('unconfirmed'),
                                     'release_id':matches[0]['release_id']}
            self.persist()
        if self.payload.get('pending'):
            self.complete()

    def publish(self, data, source_key):
        metadata=self.api('+git-credential-init')
        with tempfile.TemporaryDirectory(prefix='cycle-publisher-') as directory:
            repo=Path(directory)/'app'
            run(['git','clone','--depth','1','--branch','sprint/default',
                 metadata['repository_url'],str(repo)])
            destination=repo/'public/reports'
            destination.mkdir(parents=True,exist_ok=True)
            entries=[]
            if (destination/'index.json').exists():
                entries=json.loads((destination/'index.json').read_text())
                for item in entries:
                    if not re.fullmatch('[a-f0-9]{16}',item['report_id']):
                        raise RuntimeError('Invalid report index')
            report.write_report(data,destination/'runs'/data['report_id'])
            entries=[e for e in entries if e['report_id']!=data['report_id']]
            entries.append({k:data[k] for k in ['report_id','created_at','commit']})
            report.write_index(destination,entries)
            files={p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in destination.rglob('*') if p.is_file()}
            run(['npm','ci','--registry=https://registry.npmjs.org','--no-audit','--no-fund'],cwd=repo,timeout=900)
            run(['npm','run','build'],cwd=repo,timeout=900)
            for name,digest in files.items():
                built=repo/'dist/output/reports'/name
                if not built.is_file() or hashlib.sha256(built.read_bytes()).hexdigest()!=digest:
                    raise RuntimeError('Build did not preserve report assets')
            run(['git','config','user.name',metadata['commit_author_name']],cwd=repo)
            run(['git','config','user.email',metadata['commit_author_email']],cwd=repo)
            run(['git','add','--','public/reports'],cwd=repo)
            changed=run(['git','diff','--cached','--name-only'],cwd=repo).strip()
            if changed:
                run(['git','commit','-m','Publish measured cycles'],cwd=repo)
                run(['git','push','origin','HEAD:sprint/default'],cwd=repo)
            commit=run(['git','rev-parse','HEAD'],cwd=repo).strip()
        self.payload['unconfirmed']={'source':source_key,'commit':commit,
                                    'files':files,'started_ms':int(time.time()*1000)}
        self.persist()
        release=self.api('+release-create','--branch','sprint/default')
        self.payload['pending']={**self.payload.pop('unconfirmed'),
                                 'release_id':release['release_id']}
        self.persist()
        self.complete()


def main():
    payload,sha=state.load()
    state.restore_credentials(payload['credentials'])
    publisher=Publisher(payload,sha)
    try:
        publisher.resume()
        latest=source.latest()
        if latest is None:
            print('No successful measurement artifact is available')
            return
        source_key=[latest[k] for k in ['run_id','attempt','artifact_id']]
        if payload.get('last_source')==source_key:
            print('Latest successful measurement is already published')
            return
        raw,manifest=source.decode(source.download(latest['url'],os.environ['SOURCE_ACTIONS_TOKEN']))
        if manifest.get('commit')!=latest['commit']:
            raise RuntimeError('Artifact source version does not match CI run')
        data=report.sanitize(raw,manifest,state.public_id(latest['run_id'],latest['attempt']))
        publisher.publish(data,source_key)
        payload.pop('diagnostic',None)
    except Exception as error:
        payload['diagnostic']={'type':type(error).__name__,'detail':str(error)[-5000:]}
        raise
    finally:
        # OAuth refreshes must survive errors, otherwise unattended publishing breaks.
        publisher.persist()

if __name__=='__main__':
    try:
        main()
    except Exception as error:
        # CLI and network exceptions can contain private URLs or credential paths.
        print('Publisher failed ('+type(error).__name__+'). Inspect protected state privately.')
        raise SystemExit(1)
