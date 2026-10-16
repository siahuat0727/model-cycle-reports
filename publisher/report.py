"""Allowlisted numeric reports only: never republish source HTML, logs or manifests."""
import csv
from datetime import datetime, timezone
import html
import io
import json
from pathlib import Path
import re

CASES = {'embedding':'Embedding', 'rmsnorm':'Norm', 'add_rmsnorm':'Norm',
         'gdn_in':'GDN', 'gdn_recurrent':'GDN', 'gdn_out':'GDN',
         'gqa_qkv':'GQA', 'gqa_attention':'GQA', 'gqa_out':'GQA',
         'dense_ffn':'DenseFFN', 'lm_head':'LMHead', 'greedy':'Sampling'}


def number(value):
    if value is None:
        return None
    if type(value) is not int or not 0 <= value <= 2**63-1:
        raise ValueError('Invalid cycle counter')
    return value


def sanitize(raw, manifest, report_id):
    if not re.fullmatch('[a-f0-9]{16}', report_id):
        raise ValueError('Invalid report identifier')
    cases = []
    seen = set()
    for row in raw.get('cases', []):
        cid = row.get('id')
        if cid not in CASES or cid in seen:
            raise ValueError('Unexpected or duplicate case')
        seen.add(cid)
        measured = row.get('status') == 'measured'
        cycles = number(row.get('cycles')) if measured else None
        if measured and cycles is None:
            raise ValueError('Missing cycle counter')
        cases.append({'id':cid, 'module':CASES[cid], 'cycles':cycles,
                      'status':'measured' if measured else 'missing'})
    if seen != set(CASES):
        raise ValueError('Incomplete case inventory')
    launches = []
    for row in raw.get('launches', []):
        cid = row.get('case')
        if cid not in CASES:
            raise ValueError('Unexpected launch case')
        name = row.get('kernel', '')
        if not re.fullmatch('[A-Za-z_][A-Za-z0-9_]{0,159}', name) or re.search(r'(?:ou_|cli_|gh[pousr]_)', name):
            raise ValueError('Invalid kernel label')
        measured = row.get('status') == 'measured'
        launches.append({'case':cid, 'module':CASES[cid], 'kernel':name,
            **{field:number(row.get(field)) if measured else None
               for field in ['core0_cycles','core1_cycles','max_cycles']}})
    for case in cases:
        values = [r['max_cycles'] for r in launches if r['case'] == case['id']]
        if case['status']=='measured' and (not values or any(v is None for v in values) or sum(values)!=case['cycles']):
            raise ValueError('Case and launch counters disagree')
    date = datetime.fromisoformat(manifest['created_at'].replace('Z','+00:00'))
    if date.tzinfo is None:
        raise ValueError('Missing timestamp timezone')
    commit = manifest.get('commit','')
    if not re.fullmatch('[a-f0-9]{40}',commit):
        raise ValueError('Invalid source version')
    # Do not copy free-form version labels, URLs, local paths, errors or raw metadata.
    return {'report_id':report_id, 'model':'Qwen3.5-0.8B',
            'created_at':date.astimezone(timezone.utc).isoformat(), 'commit':commit,
            'measurement':'C++ CycleSim', 'cases':cases, 'launches':launches}


def write_report(data, destination):
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'results.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    with (destination/'results.csv').open('w',newline='',encoding='utf-8-sig') as stream:
        w=csv.DictWriter(stream,fieldnames=['module','case','kernel','core0_cycles','core1_cycles','max_cycles'])
        w.writeheader();w.writerows(data['launches'])
    e=lambda x:html.escape(str(x),quote=True)
    fmt=lambda x:'—' if x is None else f'{x:,}'
    maximum=max((r['cycles'] for r in data['cases'] if r['cycles'] is not None),default=0)
    sections=[]
    for module in dict.fromkeys(CASES.values()):
        bars=[]
        for case in [r for r in data['cases'] if r['module']==module]:
            width=100*case['cycles']/maximum if maximum and case['cycles'] is not None else 0
            bars.append(f'<div class="case"><b>{e(case["id"])}</b><span>{fmt(case["cycles"])} cycles</span><div class="track"><div style="width:{width:.3f}%"></div></div></div>')
        sections.append('<section><h2>'+module+'</h2>'+''.join(bars)+'</section>')
    rows=''.join('<tr>'+''.join('<td>'+e(fmt(row[k]) if k.endswith('cycles') else row[k])+'</td>' for k in ['module','case','kernel','core0_cycles','core1_cycles','max_cycles'])+'</tr>' for row in data['launches'])
    body=f'''<p><a href="../../index.html">全部结果</a> · <a href="results.csv">CSV</a> · <a href="results.json">结果数据</a></p><h1>Qwen3.5-0.8B · Cycles</h1>
<p>{e(data['created_at'])} · 版本 <code>{e(data['commit'][:12])}</code></p>
<p>固定 B1 / TP1 / BF16 算子探针。GQA attention 历史长度为1500。每次 launch 取各 core cycles 最大值，多 launch case 按执行顺序相加。包含 CT 与 kernel 内部 DMA，不含初始化、编译、H2D/D2H。不是完整模型耗时，不作数值正确性验收。</p>
{''.join(sections)}<section><h2>Kernel 明细</h2><div class="scroll"><table><tr><th>模块</th><th>Case</th><th>Kernel</th><th>Core0</th><th>Core1</th><th>Max cycles</th></tr>{rows}</table></div></section>'''
    (destination/'report.html').write_text(page('Qwen3.5-0.8B cycles',body),encoding='utf-8')


def page(title, body):
    return '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+html.escape(title)+'</title><style>body{font:15px/1.6 system-ui,sans-serif;margin:0;background:#f4f6fa;color:#182233}main{max-width:1100px;margin:auto;padding:28px}section{background:white;margin:18px 0;padding:20px;border-radius:12px}.case{margin:15px 0}.case span{float:right}.track{height:10px;background:#edf0f6;margin:6px 0;border-radius:5px}.track div{height:10px;background:#466ae7;border-radius:5px}table{border-collapse:collapse;width:100%;font-size:13px}td,th{padding:8px;text-align:left;border-bottom:1px solid #ddd;overflow-wrap:anywhere}.scroll{overflow:auto}a{color:#3156bc}code{overflow-wrap:anywhere}</style><main>'+body+'</main></html>'


def write_index(root, entries):
    ordered=sorted(entries,key=lambda x:x['created_at'],reverse=True)
    rows=''.join('<tr><td>'+html.escape(item['created_at'])+'</td><td><code>'+html.escape(item['commit'][:12])+'</code></td><td><a href="runs/'+item['report_id']+'/report.html">打开报告</a></td></tr>' for item in ordered)
    latest='<p><a href="runs/'+ordered[0]['report_id']+'/report.html">打开最新结果</a></p>' if ordered else '<p>尚无结果</p>'
    body='<h1>模型性能观测</h1><p>每次测速单独保存，不作历史涨跌比较。时间为 UTC。</p>'+latest+'<section><table><tr><th>运行时间</th><th>版本</th><th>结果</th></tr>'+rows+'</table></section>'
    (root/'index.html').write_text(page('模型性能观测',body),encoding='utf-8')
    (root/'index.json').write_text(json.dumps(ordered,ensure_ascii=False,indent=2)+'\n')
