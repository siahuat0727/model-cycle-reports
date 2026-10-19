"""Sync successful measurements to an independently authenticated Miaoda app."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from publisher import report, source, state, catalog


def run(args, cwd=None, timeout=300):
    env = {k:v for k,v in os.environ.items() if k not in {
        'GH_TOKEN','GITHUB_TOKEN','SOURCE_ACTIONS_TOKEN','STATE_KEY',
        'SOURCE_REPOSITORY','SOURCE_BRANCH'}}
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError('External operation timed out: '+args[0]) from None
    if result.returncode:
        raise RuntimeError('External operation failed: '+args[0]+' (exit '+str(result.returncode)+')')
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
                self.payload['published_sources'] = list(dict.fromkeys([*self.payload.get('published_sources', []), *pending.get('sources', [])]))
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
        sources = [item['source_key'] for item in data]
        metadata=self.api('+git-credential-init')
        with tempfile.TemporaryDirectory(prefix='cycle-publisher-') as directory:
            repo=Path(directory)/'app'
            run(['git','clone','--depth','1','--branch','sprint/default',
                 metadata['repository_url'],str(repo)])
            destination=repo/'public/reports'
            destination.mkdir(parents=True,exist_ok=True)
            entries=[]
            index=destination/'catalog.json'
            if index.exists():
                entries=json.loads(index.read_text())['runs']
            for item in data:
                entries,writes=catalog.append(entries,item['run'])
                for scene in writes:
                    documents=report.rank_documents(item['reports'][scene['scene_id']],
                                                    [r['rank'] for r in scene['ranks']])
                    for rank,rendered in documents.items():
                        target=destination/scene['details'][rank]
                        target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_text(report.sanitize(rendered,item['run']),encoding='utf-8')
            report.write_catalog(destination,entries)
            # The public repository owns the dashboard source; the Miaoda repo
            # supplies its platform scaffold and dependencies.
            shutil.copytree(Path(__file__).resolve().parents[1]/'web',repo/'src',dirs_exist_ok=True)
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
            run(['git','add','--','public/reports','src'],cwd=repo)
            changed=run(['git','diff','--cached','--name-only'],cwd=repo).strip()
            if changed:
                run(['git','commit','-m','Publish measured cycles'],cwd=repo)
                run(['git','push','origin','HEAD:sprint/default'],cwd=repo)
            commit=run(['git','rev-parse','HEAD'],cwd=repo).strip()
        self.payload['unconfirmed']={'source':source_key,'sources':sources,'commit':commit,
                                    'files':files,'started_ms':int(time.time()*1000)}
        self.persist()
        release=self.api('+release-create','--branch','sprint/default')
        self.payload['pending']={**self.payload.pop('unconfirmed'),
                                 'release_id':release['release_id']}
        self.persist()
        self.complete()


def collect(candidates, payload):
    """One malformed historical artifact must not block later valid runs."""
    seen={key.rsplit(':',1)[-1] for key in payload.get('published_sources',[])}
    rejected=payload.setdefault('rejected_sources',{})
    data,transport_errors=[],[]
    for latest in candidates:
        artifact=str(latest['artifact_id'])
        if artifact in seen or artifact in rejected:continue
        try:
            content=source.download(latest['url'],os.environ['SOURCE_ACTIONS_TOKEN'])
        except Exception as exc:
            transport_errors.append(type(exc).__name__)
            continue  # Retry transport failures on the next poll.
        try:
            document,reports=source.bundle(content)
            execution=document['run']
            if execution.get('run_id') is not None and str(execution['run_id'])!=str(latest['run_id']):
                raise ValueError('Artifact run identity does not match CI')
            attempt=int(execution.get('attempt',latest.get('attempt') or 1))
            if attempt<1 or latest.get('attempt') is not None and attempt!=latest['attempt']:
                raise ValueError('Artifact attempt does not match named artifact')
            info=report.metadata(dict(commit=latest['commit'],created_at=execution['created_at']),
                                 state.public_id(latest['run_id'],attempt))
            item=catalog.validate(document,info)
            # Reject unsafe detail pages before staging any release. Raw HTML
            # remains untrusted; publish applies the same sanitizer when writing.
            for scene in item['scenes']:
                if scene['status']=='passed':
                    docs=report.rank_documents(reports[scene['scene_id']],[r['rank'] for r in scene['ranks']])
                    for rendered in docs.values():report.sanitize(rendered,info)
            key=':'.join(map(str,[latest['run_id'],attempt,latest['artifact_id']]))
            data.append(dict(run=item,reports=reports,source_key=key))
        except Exception as exc:
            rejected[artifact]=dict(type=type(exc).__name__,reason=str(exc)[-1000:])
            print('::warning::Invalid historical artifact isolated; diagnostic retained in encrypted publisher state')
    return data,transport_errors


def main():
    payload,sha=state.load()
    state.restore_credentials(payload['credentials'])
    publisher=Publisher(payload,sha)
    try:
        publisher.resume()
        data,transport_errors=collect(source.available(),payload)
        if not data:
            if transport_errors:raise RuntimeError('Artifact download failed; next poll will retry')
            print('No unpublished completed measurement artifacts')
            return
        source_key=data[-1]['source_key'].split(':')
        publisher.publish(data,[int(value) for value in source_key])
        if transport_errors:raise RuntimeError('Some artifact downloads failed; next poll will retry')
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
