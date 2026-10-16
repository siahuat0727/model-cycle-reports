"""Read one successful CI artifact without executing its contents."""
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from publisher.state import request

LIMIT = 32 * 1024 * 1024

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def download(url, token):
    # Never forward the private repository token to the artifact storage host.
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer '+token,
                                              'Accept': 'application/vnd.github+json'})
    try:
        response = urllib.request.build_opener(NoRedirect).open(req, timeout=60)
    except urllib.error.HTTPError as error:
        if error.code != 302:
            raise RuntimeError('Artifact download authorization failed') from None
        location = error.headers.get('Location', '')
        if urllib.parse.urlsplit(location).scheme != 'https':
            raise RuntimeError('Unsafe artifact redirect') from None
        response = urllib.request.urlopen(location, timeout=90)
    with response:
        content = response.read(LIMIT + 1)
    if len(content) > LIMIT:
        raise RuntimeError('Artifact exceeds download limit')
    return content


def decode(content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        output = []
        for name in ('results.json', 'manifest.json'):
            matches = [item for item in archive.infolist() if item.filename == name]
            if len(matches) != 1 or matches[0].file_size > 4 * 1024 * 1024:
                raise RuntimeError('Unexpected artifact structure')
            output.append(json.loads(archive.read(matches[0])))
        return tuple(output)


def latest():
    repo = os.environ['SOURCE_REPOSITORY']
    branch = os.environ['SOURCE_BRANCH']
    token = os.environ['SOURCE_ACTIONS_TOKEN']
    base = 'https://api.github.com/repos/'+repo
    query = urllib.parse.urlencode({'branch': branch, 'status': 'success', 'per_page': 30})
    result = request('GET', base+'/actions/runs?'+query, token)
    if result is None:
        raise RuntimeError('Source repository is unavailable')
    for run in result['workflow_runs']:
        if run.get('event') != 'workflow_dispatch':
            continue
        artifacts = request('GET', base+'/actions/runs/'+str(run['id'])+'/artifacts?per_page=100', token)
        matches = [a for a in artifacts['artifacts']
                   if a['name'] == 'qwen35-08b-cycles' and not a['expired']]
        if len(matches) == 1:
            return {'run_id': run['id'], 'attempt': run['run_attempt'],
                    'artifact_id': matches[0]['id'], 'commit': run['head_sha'],
                    'url': matches[0]['archive_download_url']}
    return None
