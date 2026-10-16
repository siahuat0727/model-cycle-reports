"""Opaque encrypted state: no identity-bearing filenames in the public repository."""
import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

BRANCH = 'actions/state'
PATH = 'sealed.json'
AAD = b'model-cycle-reports-state-v1'


def key():
    value = base64.b64decode(os.environ['STATE_KEY'], validate=True)
    if len(value) != 32:
        raise RuntimeError('Invalid publisher state key')
    return value


def seal(payload, secret):
    nonce = os.urandom(12)
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()
    return {'version': 1, 'nonce': base64.b64encode(nonce).decode(),
            'ciphertext': base64.b64encode(AESGCM(secret).encrypt(nonce, raw, AAD)).decode()}


def unseal(envelope, secret):
    if envelope.get('version') != 1:
        raise RuntimeError('Unsupported state version')
    raw = AESGCM(secret).decrypt(base64.b64decode(envelope['nonce'], validate=True),
                                base64.b64decode(envelope['ciphertext'], validate=True), AAD)
    return json.loads(raw)


def request(method, url, token, payload=None):
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, method=method, headers={
        'Authorization': 'Bearer '+token, 'Accept': 'application/vnd.github+json',
        'Content-Type': 'application/json', 'X-GitHub-Api-Version': '2022-11-28'})
    try:
        with urllib.request.urlopen(req, timeout=45) as response:
            return json.load(response) if response.status != 204 else None
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise RuntimeError('GitHub API operation failed (HTTP '+str(error.code)+')') from None
    except (OSError, ValueError):
        raise RuntimeError('GitHub API transport failed') from None


def github(method, path, payload=None):
    return request(method, 'https://api.github.com/repos/'+os.environ['GITHUB_REPOSITORY']+path,
                   os.environ['GH_TOKEN'], payload)


def load():
    result = github('GET', '/contents/'+PATH+'?ref='+BRANCH)
    if result is None:
        raise RuntimeError('Publisher state is not configured')
    envelope = json.loads(base64.b64decode(result['content']))
    return unseal(envelope, key()), result['sha']


def save(payload, sha):
    result = github('PUT', '/contents/'+PATH, {
        'message': 'Update encrypted publisher state', 'branch': BRANCH, 'sha': sha,
        'content': base64.b64encode(json.dumps(seal(payload, key())).encode()).decode()})
    if not result:
        raise RuntimeError('Could not save publisher state')
    return result['content']['sha']


def capture_credentials():
    home = Path.home()
    config = home/'.lark-cli/config.json'
    store = home/'.local/share/lark-cli'
    if not config.is_file() or not (store/'master.key').is_file():
        raise RuntimeError('CLI credentials are missing')
    files = {'config': base64.b64encode(config.read_bytes()).decode()}
    for file in store.iterdir():
        if file.is_file() and (file.suffix == '.enc' or file.name == 'master.key'):
            files[file.name] = base64.b64encode(file.read_bytes()).decode()
    return files


def restore_credentials(files):
    home = Path.home()
    config = home/'.lark-cli/config.json'
    store = home/'.local/share/lark-cli'
    config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    store.mkdir(mode=0o700, parents=True, exist_ok=True)
    for name, value in files.items():
        if name != 'config' and (Path(name).name != name or not (name.endswith('.enc') or name == 'master.key')):
            raise RuntimeError('Invalid credential entry')
        path = config if name == 'config' else store/name
        path.write_bytes(base64.b64decode(value, validate=True))
        path.chmod(0o600)


def public_id(run_id, attempt):
    return hmac.new(key(), (str(run_id)+':'+str(attempt)).encode(), hashlib.sha256).hexdigest()[:16]
