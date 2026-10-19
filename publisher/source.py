"""Read one successful CI artifact without executing its contents."""
import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from publisher.state import request

LIMIT = 128 * 1024 * 1024

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
        for name in ('results.json', 'manifest.json', 'report.html'):
            matches = [item for item in archive.infolist() if item.filename == name]
            if len(matches) != 1 or matches[0].file_size > 4 * 1024 * 1024:
                raise RuntimeError('Unexpected artifact structure')
            raw=archive.read(matches[0]).decode('utf-8')
            output.append(raw if name.endswith('.html') else json.loads(raw))
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
                   if a['name'] == 'model-cycles' and not a['expired']]
        if len(matches) == 1:
            return {'run_id': run['id'], 'attempt': run['run_attempt'],
                    'artifact_id': matches[0]['id'], 'commit': run['head_sha'],
                    'url': matches[0]['archive_download_url']}
    return None


def bundle(content):
    """Read bounded named members without extracting or executing archive files."""
    from publisher import catalog
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names=[f.filename for f in archive.infolist()]
        if len(names)!=len(set(names)):raise RuntimeError('Duplicate artifact member')
        def read(name, limit=8*1024*1024):
            info=archive.getinfo(name)
            if info.file_size>limit:raise RuntimeError('Artifact member exceeds limit')
            return archive.read(info).decode('utf-8')
        if 'measurement-summary.json' in names:
            summary=json.loads(read('measurement-summary.json'))
            reports={}
            for scene in summary['scenes']:
                ident=catalog.identifier(scene['scene_id'])
                if scene['status']=='passed':reports[ident]=read(ident+'/report.html')
            return summary,reports
        raw,manifest,rendered=decode(content)
        cfg=manifest['scene'];fw=raw.get('framework') or {}
        if fw.get('status')!='measured' or fw.get('errors') or not raw.get('regular_decode'):
            raise ValueError('Legacy artifact is not a complete measurement')
        # Migration reads upstream aggregate values. Never reconstruct from logs
        # or infer a fake earlier timestamp from the new run.
        params={k:cfg[k] for k in ('batch','context','dtype','tp','seed','decode_steps','geometry')}
        params.update(layers=cfg['layers'],token=cfg['token'],precision=cfg.get('precision',{}),ep=cfg.get('ep',1),quantization=cfg.get('quantization','none'),
                      fixture=cfg.get('framework',{}).get('fixture','synthetic'))
        model_id=cfg.get('model_id')
        if model_id is None:
            if cfg['adapter']!='qwen35' or cfg['model']!='Qwen3.5-0.8B':
                raise ValueError('Legacy model has no stable identity')
            model_id='qwen35-08b'
        protocol=catalog.PROTOCOL if fw.get('manifest',{}).get('coverage_version')==1 else 'legacy-regular-decode-v0'
        comparison=dict(model_id=model_id,parameters=params,protocol=protocol,frequency_mhz=cfg['frequency_mhz'])
        fm=fw.get('manifest',{});view=raw['regular_decode']
        env={k:manifest.get(k) for k in ('torch','triton','simulator_sha256','native_extension_sha256','sgl_adapter_sha256')}
        env['toolchain_fingerprint']=catalog.digest({k:manifest.get(k) for k in ('release_metadata','compiler_flags','simulator_sha256')})
        env.update({k+'_commit':fm.get(k,{}).get('commit') for k in ('sglang','devexample')})
        scene=dict(scene_id=cfg['id'],model_id=model_id,model=cfg['model'],parameters=params,
            protocol=protocol,comparison_key=catalog.digest(comparison),frequency_mhz=cfg['frequency_mhz'],
            status='passed',environment=env,probe_baseline_cycles=raw.get('weighted_total_cycles'),probe_rank=0,
            ranks=[dict(rank=0,step_count=view['step_count'],sample_cycles=view['sample_cycles'],
                        module_cycles=view['modules'],mean_step_cycles=view['mean_step_cycles'])])
        return dict(schema_version=1,suite_id='legacy-single-scene',run=dict(commit=manifest['commit'],
                    created_at=manifest['created_at'],run_id=manifest.get('run_id'),attempt=manifest.get('run_attempt','1')),scenes=[scene]),{scene['scene_id']:rendered}


def available():
    """Oldest first; include partial failures, paginate past more than one poll."""
    repo,branch,token=(os.environ[k] for k in ('SOURCE_REPOSITORY','SOURCE_BRANCH','SOURCE_ACTIONS_TOKEN'))
    base='https://api.github.com/repos/'+repo
    runs=[]
    for page in range(1,11):
        query=urllib.parse.urlencode(dict(branch=branch,status='completed',per_page=100,page=page))
        result=request('GET',base+'/actions/runs?'+query,token)
        if result is None:raise RuntimeError('Source repository unavailable')
        batch=result['workflow_runs'];runs.extend(batch)
        if len(batch)<100:break
    else:
        raise RuntimeError('History exceeds discovery window; backfill before continuing')
    found=[]
    for run in runs:
        if run.get('event')!='workflow_dispatch' or run.get('conclusion') not in ('success','failure','timed_out'):continue
        result=request('GET',base+'/actions/runs/'+str(run['id'])+'/artifacts?per_page=100',token)
        if result is None:raise RuntimeError('Cannot read source artifacts')
        matches=[a for a in result['artifacts'] if re.fullmatch(r'model-cycles(?:-[1-9][0-9]*)?',a['name']) and not a['expired']]
        for artifact in matches:
            suffix=artifact['name'].removeprefix('model-cycles')
            attempt=int(suffix[1:]) if suffix else None
            found.append(dict(run_id=run['id'],attempt=attempt,artifact_id=artifact['id'],
                commit=run['head_sha'],url=artifact['archive_download_url'],created_at=artifact.get('created_at',run['created_at'])))
    return sorted(found,key=lambda r:(r['created_at'],r['run_id'],r['attempt'] or 1))
