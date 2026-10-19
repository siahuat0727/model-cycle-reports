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
