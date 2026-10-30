"""Publish the CI report's layout and measurements as a passive, redacted document."""
from datetime import datetime, timezone
import html
import json
import re
from lxml import etree
from lxml import html as document

TAGS = set('html head body title meta style main header footer section nav div span p a h1 h2 h3 h4 table thead tbody tfoot tr th td details summary pre code strong b small i em br hr ul ol li'.split())
ATTRS = {'class','id','colspan','rowspan','open','role','aria-label','lang'}
SENSITIVE = re.compile(r'(?:ou_|cli_|gh[pousr]_)[A-Za-z0-9_]+|github_pat_[A-Za-z0-9_]+|(?:https?://|/(?:workspace|home|root|opt|tmp|state)/)[^\s<>"\']+')


def metadata(manifest, report_id):
    if not re.fullmatch('[a-f0-9]{16}', report_id):
        raise ValueError('Invalid report identifier')
    commit=manifest.get('commit','')
    if not re.fullmatch('[a-f0-9]{40}',commit):
        raise ValueError('Invalid source version')
    date=datetime.fromisoformat(manifest['created_at'].replace('Z','+00:00'))
    if date.tzinfo is None:
        raise ValueError('Missing timestamp timezone')
    return {'report_id':report_id,'commit':commit,
            'created_at':date.astimezone(timezone.utc).isoformat()}


def sanitize(source, info):
    root=document.document_fromstring(source)
    ids={node.get('id') for node in root.iter()}
    if not {'blocks','modules','framework','evidence'} <= ids:
        raise ValueError('Incomplete full model report')
    # Version/config/diagnostic blocks may contain paths, identities and log excerpts.
    for node in list(root.xpath('//details[.//pre] | //script | //iframe | //object | //embed | //link | //base | //form | //img | //svg')):
        if node.getparent() is not None:
            node.drop_tree()
    for node in root.xpath('//comment()'):
        node.getparent().remove(node)
    for node in list(root.iter()):
        if not isinstance(node.tag,str):
            continue
        if node.tag not in TAGS:
            node.drop_tree()
            continue
        attrs=dict(node.attrib)
        node.attrib.clear()
        for key,value in attrs.items():
            if key in ATTRS and not SENSITIVE.search(value):
                node.set(key,value)
            elif key=='href' and re.fullmatch(r'#[A-Za-z][A-Za-z0-9_-]*',value):
                node.set(key,value)
            elif key=='style':
                if re.search(r'url\s*\(|@import|expression\s*\(|\\|[<]',value,re.I):
                    raise ValueError('Active inline CSS is not allowed')
                node.set(key,value)
        if node.tag=='meta':
            if attrs.get('charset'):
                node.set('charset','utf-8')
            elif attrs.get('name')=='viewport':
                node.set('name','viewport');node.set('content','width=device-width,initial-scale=1')
            else:
                node.drop_tree()
        if node.tag=='style' and re.search(r'url\s*\(|@import|expression\s*\(|\\|[<]',node.text or '',re.I):
            raise ValueError('Active stylesheet is not allowed')
        if node.text:
            node.text=SENSITIVE.sub('[已隐藏]',node.text)
        if node.tail:
            node.tail=SENSITIVE.sub('[已隐藏]',node.tail)
    # Replace private/raw-artifact links with safe collection provenance.
    evidence=root.get_element_by_id('evidence')
    for node in list(evidence.xpath('./p[contains(concat(" ", normalize-space(@class), " "), " hint ")]')):
        node.drop_tree()
    provenance=etree.Element('p',{'class':'hint'})
    provenance.text=f'采集时间 {info["created_at"]} · 版本 {info["commit"][:12]}'
    evidence.insert(1,provenance)
    # The document is passive both in an iframe and when opened directly.
    head=root.find('head')
    policy=etree.Element('meta',{'http-equiv':'Content-Security-Policy',
        'content':"default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'"})
    head.insert(0,policy)
    rendered=document.tostring(root,encoding='unicode',doctype='<!doctype html>')
    if SENSITIVE.search(rendered):
        raise ValueError('Private metadata remained in public HTML')
    return rendered


def write_report(source, info, destination):
    rendered=sanitize(source,info)
    destination.mkdir(parents=True,exist_ok=True)
    (destination/'report.html').write_text(rendered,encoding='utf-8')
    (destination/'metadata.json').write_text(json.dumps(info,ensure_ascii=False,indent=2)+'\n')


def write_index(root, entries):
    ordered=sorted(entries,key=lambda row:row['created_at'],reverse=True)
    for item in ordered:
        if not re.fullmatch('[a-f0-9]{16}',item['report_id']):
            raise ValueError('Invalid report identifier')
    rows=''.join('<tr><td>'+html.escape(item['created_at'])+'</td><td><code>'+html.escape(item['commit'][:12])+'</code></td><td><a href="runs/'+item['report_id']+'/report.html">打开报告</a></td></tr>' for item in ordered)
    body='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>模型性能观测</title><style>body{font:15px/1.6 system-ui;padding:24px}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}a{color:#3156bc}</style><h1>模型性能观测</h1><table><tr><th>采集时间（UTC）</th><th>版本</th><th>报告</th></tr>'+rows+'</table></html>'
    (root/'index.html').write_text(body,encoding='utf-8')
    (root/'index.json').write_text(json.dumps(ordered,ensure_ascii=False,indent=2)+'\n')


def rank_documents(source, ranks):
    """Unwrap CI rank srcdoc; sanitize each document separately at publication."""
    root=document.document_fromstring(source)
    frames=root.xpath('//section[@data-rank]/iframe[@srcdoc]')
    if not frames:
        if ranks!=[0]:raise ValueError('Missing rank detail pages')
        return {'0':source}
    result={}
    for frame in frames:
        rank=frame.getparent().get('data-rank')
        if rank in result:raise ValueError('Duplicate rank detail')
        result[rank]=frame.get('srcdoc')
    if set(result)!={str(r) for r in ranks}:raise ValueError('Rank detail mismatch')
    return result


def write_catalog(root, entries):
    """Public index contains only the validator's explicit projection."""
    root.mkdir(parents=True,exist_ok=True)
    (root/'catalog.json').write_text(json.dumps(dict(schema_version=1,runs=entries),ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def compute_document(source, scene, rank_id):
    """Derive a non-communication view from sanitized HTML; keep archives unchanged."""
    root=document.document_fromstring(source)
    rank=next(r for r in scene['ranks'] if r['rank']==rank_id)
    modules={k:v for k,v in rank['module_cycles'].items() if k!='通信'}
    known=scene['parameters']['tp']==1 or '通信' in rank['module_cycles']
    communication=rank['module_cycles'].get('通信',0)
    total=sum(rank['sample_cycles'])-communication
    known=known and total>=0
    frequency=scene['frequency_mhz'];steps=rank['step_count']
    def us(cycles):return f'{cycles/steps/frequency:,.3f}'
    def ms(cycles):return f'{cycles/steps/frequency/1000:,.4f}'
    def share(cycles):return f'{cycles/total*100:.2f}%' if known and total else '—'
    e=html.escape
    blocks=root.get_element_by_id('blocks',None)
    blocks=document.tostring(blocks,encoding='unicode') if blocks is not None else '<section id="blocks"><h2>Block 汇总</h2><p>缺测</p></section>'
    module_rows=''.join(f'<tr><th>{e(name)}</th><td>{us(value)}</td><td>{share(value)}</td></tr>' for name,value in sorted(modules.items(),key=lambda pair:-pair[1]))
    # The old HTML exposes aggregate phase time, not communication per phase.
    # Preserve phase names but never infer a split from graph/eager mode.
    phase_rows=[]
    kernel_rows=[]
    for table in root.xpath('//*[@id="framework"]//table'):
        headers=[''.join(c.itertext()).strip() for c in table.xpath('./thead/tr/th')]
        if headers[:2]==['执行阶段','位置']:
            for row in table.xpath('./tbody/tr'):
                cells=[''.join(c.itertext()).strip() for c in row]
                if len(cells)>=4:
                    cost=cells[2] if known and communication==0 else '缺测'
                    # Recalculate percentages using the derived total.
                    percent=share(float(cost.replace(',',''))*steps*frequency) if cost!='缺测' else '—'
                    phase_rows.append(f'<tr><th>{e(cells[0])}</th><td>{e(cells[1])}</td><td>{e(cost)}</td><td>{percent}</td></tr>')
        elif headers[:2]==['模块','Kernel']:
            for row in table.xpath('./tbody/tr'):
                cells=[''.join(c.itertext()).strip() for c in row]
                if len(cells)==4 and cells[0]!='通信':
                    kernel_rows.append('<tr>'+''.join(f'<td>{e(c)}</td>' for c in cells)+'</tr>')
    if not phase_rows:phase_rows.append('<tr><td colspan="4">缺测</td></tr>')
    if not kernel_rows:kernel_rows.append('<tr><td colspan="4">缺测</td></tr>')
    phase_note='历史记录未提供各执行阶段的通信分项，无法可靠扣除的阶段耗时显示缺测。' if communication or not known else ''
    primary=ms(total) if known else '缺测'
    baseline=scene.get('probe_baseline_cycles')
    baseline_value=f'{baseline/frequency/1000:,.4f}' if baseline is not None else '缺测'
    styles=''.join(document.tostring(n,encoding='unicode') for n in root.xpath('//head/style'))
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'">
{styles}<style>body{{font:14px/1.6 system-ui;margin:20px}}section{{margin:24px 0}}table{{width:100%;border-collapse:collapse}}th,td{{padding:8px;text-align:left;border-bottom:1px solid #ddd}}.metrics{{display:flex;gap:32px}}.metric strong{{display:block;font-size:26px}}</style></head><body><main>
<h1>{e(scene['model'])} · Context {scene['parameters']['context']} · Rank {rank_id}</h1>
<div class="metrics"><div class="metric primary"><span>非通信 kernel</span><strong>{primary} <small>ms / step</small></strong></div><div class="metric"><span>独立算子加权参考 · Rank {scene.get('probe_rank',0)}</span><strong>{baseline_value} <small>ms / step</small></strong></div></div>
{blocks}
<section id="modules"><h2>模块时间与占比</h2><table><thead><tr><th>模块</th><th>μs / step</th><th>占比</th></tr></thead><tbody>{module_rows}</tbody><tfoot><tr><th>非通信合计</th><td>{us(total) if known else '缺测'}</td><td>{share(total)}</td></tr></tfoot></table></section>
<section id="framework"><h2>执行阶段与 kernel 明细</h2><p>{phase_note}</p><table><thead><tr><th>执行阶段</th><th>位置</th><th>μs / step</th><th>占比</th></tr></thead><tbody>{''.join(phase_rows)}</tbody></table>
<h3>常规 decode 非通信 kernel</h3><table><thead><tr><th>模块</th><th>Kernel</th><th>{steps} 个常规 step 调用次数</th><th>μs / step</th></tr></thead><tbody>{''.join(kernel_rows)}</tbody></table></section>
<section id="evidence"><p>{steps} 个常规 step · {frequency} MHz · 各 rank 独立统计</p></section></main></body></html>'''


def write_compute_details(destination, entries):
    written=set()
    for entry in entries:
        for scene in entry['scenes']:
            for rank,relative in scene.get('details',{}).items():
                path=destination/relative
                if path in written:continue
                rendered=compute_document(path.read_text(encoding='utf-8'),scene,int(rank))
                path.with_name(path.stem+'-compute.html').write_text(rendered,encoding='utf-8')
                written.add(path)
