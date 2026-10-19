import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from publisher.report import metadata, sanitize, write_report
from publisher.source import decode
from publisher.state import seal, unseal

INFO={'report_id':'a'*16,'commit':'b'*40,'created_at':'2026-10-16T07:00:00+00:00'}
HTML='''<!doctype html><html><head><style>.metric>span{color:red}</style></head><body>
<section id="blocks"><h2>Block 汇总</h2><p>缺测 —，0 cycles</p></section>
<section id="modules"><h2>模块时间与占比</h2></section>
<section id="framework"><h2>首次准备开销</h2><h3>请求完成阶段</h3>
<a href="#phase_graph" onclick="alert(1)">Graph</a><div id="phase_graph">86.683 μs</div></section>
<section id="evidence"><p class="hint"><a href="https://private.example/log">CI</a></p>
<details><summary>版本</summary><pre>PRIVATE_CANARY ou_secret123 /workspace/private</pre></details></section>
<script>PRIVATE_CANARY</script></body></html>'''

class PublisherTests(unittest.TestCase):
    def test_full_report_layout_and_measurements_survive(self):
        result=sanitize(HTML,INFO)
        for text in ['Block 汇总','模块时间与占比','首次准备开销','请求完成阶段','86.683 μs','缺测 —，0 cycles','href="#phase_graph"']:
            self.assertIn(text,result)
        self.assertIn("default-src 'none'",result)

    def test_private_metadata_and_active_content_are_removed(self):
        result=sanitize(HTML,INFO)
        for text in ['PRIVATE_CANARY','ou_secret123','/workspace/private','private.example','<script','onclick=']:
            self.assertNotIn(text,result)

    def test_external_css_is_rejected(self):
        with self.assertRaises(ValueError):
            sanitize(HTML.replace('color:red','background:url(https://private.example)'),INFO)

    def test_incomplete_report_is_not_published(self):
        with self.assertRaises(ValueError):sanitize('<html><p>partial</p></html>',INFO)

    def test_only_redacted_html_and_provenance_are_written(self):
        with tempfile.TemporaryDirectory() as folder:
            write_report(HTML,INFO,Path(folder))
            self.assertEqual({p.name for p in Path(folder).iterdir()},{'report.html','metadata.json'})

    def test_version_requires_timestamp_timezone(self):
        with self.assertRaises(ValueError):metadata({'commit':'a'*40,'created_at':'2026-10-16T00:00:00'},'a'*16)

    def test_complete_state_including_identity_is_encrypted(self):
        payload={'ou_PRIVATE_CANARY.enc':'PRIVATE_CANARY'}
        encrypted=seal(payload,b'a'*32)
        self.assertNotIn('PRIVATE_CANARY',json.dumps(encrypted))
        self.assertEqual(unseal(encrypted,b'a'*32),payload)
        with self.assertRaises(Exception):unseal(encrypted,b'b'*32)

    def test_duplicate_artifact_files_rejected(self):
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('results.json','{}')
            archive.writestr('folder/manifest.json','{}')
        with self.assertRaises(RuntimeError):decode(data.getvalue())

if __name__=='__main__':unittest.main()
