"""Sync successful measurements to an independently authenticated Miaoda app."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
from publisher import report, source, state, catalog, publication


class ExternalOperationError(RuntimeError):
    def __init__(self, message, private_detail):
        super().__init__(message)
        self.private_detail = private_detail


class AuthorizationRequiredError(ExternalOperationError):
    pass


def authorization_required(error):
    try:
        result = json.loads(error.private_detail)
    except (ValueError, TypeError):
        result = {}
    if isinstance(result, dict) and result.get('ok') is False and result.get('missing'):
        return True  # `auth check --json` reports missing permissions this way.
    return bool(re.search(
        r'\b(token_missing|no_token|not_logged_in|missing_scopes|scope_missing|'
        r'insufficient_scope|refresh_token_expired|refresh_token_invalid|invalid_grant)\b',
        error.private_detail, re.IGNORECASE))


def run(args, cwd=None, timeout=300):
    env = {k:v for k,v in os.environ.items() if k not in {
        'GH_TOKEN','GITHUB_TOKEN','SOURCE_ACTIONS_TOKEN','STATE_KEY',
        'SOURCE_REPOSITORY','SOURCE_BRANCH'}}
    if os.environ.get('PUBLISHER_HOME'):
        home = state.credential_home()
        env.update(HOME=str(home), XDG_DATA_HOME=str(home/'.local/share'),
                   XDG_CONFIG_HOME=str(home/'.config'))
    try:
        result = subprocess.run(args, cwd=cwd, env=env, capture_output=True,
                                text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError('External operation timed out: '+args[0]) from None
    if result.returncode:
        operation = ' '.join(args[:3]) if args[:2]==['lark-cli','apps'] else args[0]
        raise ExternalOperationError('External operation failed: '+operation+' (exit '+str(result.returncode)+')',
                                     (result.stdout+result.stderr)[-5000:])
    return result.stdout


def dashboard_files():
    root=Path(__file__).resolve().parents[1]/'web'
    return [(path,path.relative_to(root)) for path in sorted(root.rglob('*'))
            if path.suffix in ('.ts','.tsx','.css') and 'node_modules' not in path.relative_to(root).parts]


def dashboard_revision():
    files={str(relative):hashlib.sha256(path.read_bytes()).hexdigest()
           for path,relative in dashboard_files()}
    files['publication.json']=sorted(publication.scene_ids())
    return catalog.digest(files)


class Publisher:
    def __init__(self, payload, sha):
        self.payload, self.sha = payload, sha
        self.app = payload['app_id']
        self._saved_payload = copy.deepcopy(payload)

    def persist(self):
        self.payload['credentials'] = state.capture_credentials()
        if self.payload != self._saved_payload:
            self.sha = state.save(self.payload, self.sha)
            self._saved_payload = copy.deepcopy(self.payload)

    def command(self, args, **kwargs):
        try:
            return run(args, **kwargs)
        except ExternalOperationError as error:
            if authorization_required(error):
                raise AuthorizationRequiredError(
                    'Publisher authorization requires renewal', error.private_detail) from None
            raise
        finally:
            # A request can refresh OAuth before failing or returning malformed JSON.
            # Checkpoint before any subsequent network/build operation uses the token.
            self.persist()

    def check_authorization(self):
        self.api('+get')  # A real user API call triggers the CLI's automatic refresh.
        self.command(['lark-cli', 'auth', 'check', '--scope',
                      'offline_access spark:app:read spark:app:write', '--json'])
        print('Publisher authorization check passed', flush=True)

    def api(self, command, *args):
        result = json.loads(self.command(['lark-cli','apps',command,'--app-id',self.app,
                                 '--as','user',*args], timeout=100))
        if not result.get('ok'):
            error = ExternalOperationError('Miaoda API operation failed: '+command,
                                           json.dumps(result))
            if authorization_required(error):
                raise AuthorizationRequiredError(
                    'Publisher authorization requires renewal', error.private_detail) from None
            raise error
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
                if pending.get('dashboard_revision'):
                    self.payload['dashboard_revision']=pending['dashboard_revision']
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

    def publish(self, data, source_key, *, force=False):
        sources = [item['source_key'] for item in data]
        metadata=self.api('+git-credential-init')
        with tempfile.TemporaryDirectory(prefix='cycle-publisher-') as directory:
            repo=Path(directory)/'app'
            self.command(['git','clone','--depth','1','--branch','sprint/default',
                 metadata['repository_url'],str(repo)])
            destination=repo/'public/reports'
            destination.mkdir(parents=True,exist_ok=True)
            entries=[]
            index=destination/'catalog.json'
            if index.exists():
                entries=json.loads(index.read_text())['runs']
            allowed=publication.scene_ids()
            entries=[selected for entry in entries if (selected:=publication.select(entry,allowed))]
            for item in data:
                selected=publication.select(item['run'],allowed)
                if selected is None:continue
                entries,writes=catalog.append(entries,selected)
                for scene in writes:
                    documents=report.rank_documents(item['reports'][scene['scene_id']],
                                                    [r['rank'] for r in scene['ranks']])
                    for rank,rendered in documents.items():
                        target=destination/scene['details'][rank]
                        target.parent.mkdir(parents=True,exist_ok=True)
                        target.write_text(report.sanitize(rendered,item['run']),encoding='utf-8')
            publication.prune_details(destination,entries)
            report.write_catalog(destination,entries)
            # The public repository owns the dashboard source; the Miaoda repo
            # supplies its platform scaffold and dependencies.
            for file,relative in dashboard_files():
                target=repo/'src'/relative
                target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copy2(file,target)
            files={p.relative_to(destination).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
                   for p in destination.rglob('*') if p.is_file()}
            self.command(['npm','ci','--registry=https://registry.npmjs.org','--no-audit','--no-fund'],cwd=repo,timeout=900)
            self.command(['npm','run','build'],cwd=repo,timeout=900)
            for name,digest in files.items():
                built=repo/'dist/output/reports'/name
                if not built.is_file() or hashlib.sha256(built.read_bytes()).hexdigest()!=digest:
                    raise RuntimeError('Build did not preserve report assets')
            self.command(['git','config','user.name',metadata['commit_author_name']],cwd=repo)
            self.command(['git','config','user.email',metadata['commit_author_email']],cwd=repo)
            self.command(['git','add','--','public/reports','src'],cwd=repo)
            changed=self.command(['git','diff','--cached','--name-only'],cwd=repo).strip()
            if changed:
                self.command(['git','commit','-m','Publish measured cycles'],cwd=repo)
            elif force:
                # A new commit asks the hosting service to build again rather
                # than reuse the deployment associated with an existing SHA.
                self.command(['git','commit','--allow-empty','-m','Rebuild site deployment'],cwd=repo)
            if changed or force:
                self.command(['git','push','origin','HEAD:sprint/default'],cwd=repo)
            commit=self.command(['git','rev-parse','HEAD'],cwd=repo).strip()
        if not force and commit == self.payload.get('published_commit'):
            self.payload['dashboard_revision'] = dashboard_revision()
            self.payload['published_sources'] = list(dict.fromkeys([*self.payload.get('published_sources', []), *sources]))
            self.payload['last_source'] = source_key
            self.persist()
            print('Published content unchanged; release skipped', flush=True)
            return
        self.payload['unconfirmed']={'source':source_key,'sources':sources,'commit':commit,
                                    'dashboard_revision':dashboard_revision(),
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
    if not os.environ.get('PUBLISHER_HOME'):
        raise RuntimeError('PUBLISHER_HOME must name an isolated credential directory')
    state.credential_home()  # Validate before restoring any credential files.
    payload,sha=state.load()
    state.restore_credentials(payload['credentials'])
    publisher=Publisher(payload,sha)
    try:
        publisher.check_authorization()
        payload.pop('diagnostic', None)
        publisher.resume()
        data,transport_errors=collect(source.available(),payload)
        force = os.environ.get('FORCE_SITE_REDEPLOY') == 'true'
        if not data:
            if transport_errors:raise RuntimeError('Artifact download failed; next poll will retry')
            if payload.get('published_sources') and (force or payload.get('dashboard_revision')!=dashboard_revision()):
                publisher.publish([],payload['last_source'],force=force)
            else:
                print('No unpublished measurements or dashboard changes')
            return
        source_key=data[-1]['source_key'].split(':')
        publisher.publish(data,[int(value) for value in source_key],force=force)
        if transport_errors:raise RuntimeError('Some artifact downloads failed; next poll will retry')
        payload.pop('diagnostic',None)
    except Exception as error:
        payload['diagnostic']={'type':type(error).__name__,'operation':str(error)[:300],
                               'detail':getattr(error,'private_detail',str(error))[-5000:]}
        raise
    finally:
        # OAuth refreshes must survive errors, otherwise unattended publishing breaks.
        publisher.persist()

if __name__=='__main__':
    try:
        main()
    except Exception as error:
        # CLI and network exceptions can contain private URLs or credential paths.
        if isinstance(error, AuthorizationRequiredError):
            print('::error::Publisher authorization requires renewal. Update the dedicated CI authorization; automatic retries cannot grant missing consent.')
        else:
            print('Publisher failed ('+type(error).__name__+'). Inspect protected state privately.')
        raise SystemExit(1)
