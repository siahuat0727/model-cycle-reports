"""Validate upstream facts and retain CI observations independently of detail pages."""
from datetime import datetime, timezone
import hashlib
import json
import math
import re

PROTOCOL='cpp-cycles-regular-decode-v1'
SAFE_ID=re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,119}')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def text(value, limit=160):
    if not isinstance(value,str) or len(value)>limit or re.search(r'[<>\x00-\x1f]|\.\./|https?://|/(?:workspace|home|root|tmp|opt)/|(?:ou_|cli_|gh[pousr]_|github_pat_)',value):
        raise ValueError('Unsafe public text')
    return value


def identifier(value):
    if not isinstance(value,str) or not SAFE_ID.fullmatch(value):raise ValueError('Invalid identifier')
    return value


def number(value):
    if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<2**53:
        raise ValueError('Invalid finite measurement')
    return value


def cycles(value):
    if type(value) is not int:raise ValueError('Integer cycles required')
    return number(value)


def timestamp(value):
    date=datetime.fromisoformat(value.replace('Z','+00:00'))
    if date.tzinfo is None:raise ValueError('Timestamp timezone required')
    return date.astimezone(timezone.utc).isoformat()


def validate_scene(raw):
    status=raw['status']
    if status not in ('passed','failed','dependency_unavailable'):raise ValueError('Invalid scene status')
    params=raw['parameters']
    expected=('batch','context','dtype','tp','ep','quantization','fixture','seed','decode_steps','geometry','token','precision')
    clean={k:params[k] for k in expected}
    for key in ('batch','context','tp','ep','decode_steps'):
        if type(clean[key]) is not int or not 0<clean[key]<2**31:raise ValueError('Invalid scene dimension')
    if type(clean['seed']) is not int or not 0<=clean['seed']<2**53:raise ValueError('Invalid seed')
    clean['token']=cycles(clean['token'])
    if set(clean['precision'])-{'cuda_route_rounding','gdn_conv_tlayout','gdn_silu_mode'}:raise ValueError('Unknown precision setting')
    for key,value in clean['precision'].items():
        if key=='gdn_silu_mode':cycles(value)
        elif type(value) is not bool:raise ValueError('Invalid precision flag')
    for key in ('dtype','quantization','fixture'):clean[key]=identifier(clean[key])
    if not isinstance(clean['geometry'],dict) or len(clean['geometry'])>50:raise ValueError('Invalid geometry')
    clean['geometry']={identifier(k):cycles(v) for k,v in clean['geometry'].items()}
    model_id=identifier(raw['model_id']); frequency=number(raw['frequency_mhz'])
    if frequency<=0:raise ValueError('Positive frequency required')
    protocol=identifier(raw['protocol'])
    comparison=dict(model_id=model_id,parameters=clean,protocol=protocol,frequency_mhz=frequency)
    if raw['comparison_key']!=digest(comparison):raise ValueError('Comparison key mismatch')
    environment={k:text(v) if v is not None else None for k,v in raw.get('environment',{}).items()
                 if k in ('torch','triton','simulator_sha256','native_extension_sha256','sgl_adapter_sha256','sglang_commit','devexample_commit','kernel_commit','toolchain_fingerprint')}
    ranks=[]
    for rank in raw['ranks']:
        samples=[cycles(v) for v in rank['sample_cycles']]
        modules={text(k,50):cycles(v) for k,v in rank['module_cycles'].items()}
        n=rank['step_count'];total=sum(samples)
        if type(n) is not int or not n or n!=len(samples) or n>10000 or sum(modules.values())!=total or not total:
            raise ValueError('Incomplete measured samples or module totals')
        if number(rank['mean_step_cycles'])!=total/n:raise ValueError('Mean mismatch')
        ranks.append(dict(rank=cycles(rank['rank']),sample_cycles=samples,step_count=n,
                          module_cycles=modules,mean_step_cycles=total/n))
    if status=='passed' and {r['rank'] for r in ranks}!=set(range(clean['tp'])):raise ValueError('Missing rank')
    if len(ranks)!=len({r['rank'] for r in ranks}) or status!='passed' and ranks:raise ValueError('Invalid rank results')
    baseline=raw.get('probe_baseline_cycles')
    if baseline is not None:baseline=cycles(baseline)
    return dict(scene_id=identifier(raw['scene_id']),model_id=model_id,model=text(raw['model']),
        parameters=clean,protocol=protocol,comparison_key=raw['comparison_key'],frequency_mhz=frequency,
        status=status,reason='upstream_dependency_pending' if status=='dependency_unavailable' else ('measurement_failed' if status=='failed' else None),
        ranks=ranks,probe_baseline_cycles=baseline,probe_rank=cycles(raw.get('probe_rank',0)),environment=environment)


def validate(document, info):
    if document['schema_version']!=1:raise ValueError('Unsupported summary schema')
    if document['run']['commit']!=info['commit']:raise ValueError('Artifact commit mismatch')
    scenes=[validate_scene(raw) for raw in document['scenes']]
    if not scenes or len(scenes)>100 or len({s['scene_id'] for s in scenes})!=len(scenes):raise ValueError('Invalid scene collection')
    return dict(**info,scenes=scenes)


def fingerprint(scene):
    # Source commits remain in each observation. Only toolchain changes prevent
    # detail reuse when measured values are identical across code changes.
    return digest(dict(comparison=scene['comparison_key'],ranks=scene['ranks'],
        baseline=scene['probe_baseline_cycles'],probe_rank=scene['probe_rank'],
        toolchain={k:scene['environment'].get(k) for k in ('torch','triton','simulator_sha256','toolchain_fingerprint')}))


def append(catalog, run):
    previous=[entry for entry in catalog if entry['report_id']!=run['report_id']]
    if any(entry['report_id']==run['report_id'] for entry in catalog):
        return catalog, []  # immutable observations; a retry has a different ID
    writes=[]
    for scene in run['scenes']:
        if scene['status']!='passed':continue
        match=None
        for old in sorted(previous,key=lambda r:r['created_at'],reverse=True):
            match=next((s for s in old['scenes'] if s['scene_id']==scene['scene_id'] and s['status']=='passed'),None)
            if match:break
        scene['fingerprint']=fingerprint(scene)
        if match and fingerprint(match)==scene['fingerprint']:
            scene['same_as']=old['report_id']
            scene['details']=match['details']
        else:
            scene['same_as']=None
            scene['details']={str(r['rank']):f"runs/{run['report_id']}/{scene['scene_id']}/rank{r['rank']}.html" for r in scene['ranks']}
            writes.append(scene)
    return sorted([*previous,run],key=lambda r:r['created_at']), writes
