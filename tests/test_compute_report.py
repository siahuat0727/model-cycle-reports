import copy
import tempfile
import unittest
from pathlib import Path
from lxml import html
from publisher import report
from test_catalog import scene

RAW='''<html><head></head><body><div class="metrics"><div>常规 decode 24.7850 ms</div></div>
<section id="blocks"><h2>Block 汇总</h2><table><tr><td>GDN</td><td>9.000</td></tr></table></section>
<section id="modules"><table><tr><td>通信</td><td>13,342.038</td></tr></table></section>
<section id="framework"><table><thead><tr><th>执行阶段</th><th>位置</th><th>时间</th><th>占框架</th></tr></thead><tbody><tr><th>Forward 周边</th><td>graph 外</td><td>24,733.434</td><td>99.79%</td></tr></tbody></table>
<details><summary>完整 kernel</summary><table><thead><tr><th>模块</th><th>Kernel</th><th>调用次数</th><th>μs / step</th></tr></thead><tbody>
<tr><td>通信</td><th>zccl_allreduce_ring_bf16</th><td>258</td><td>13,342.038</td></tr>
<tr><td>GDN</td><th>qwen_pre_attn_norm_gdn_kernel</th><td>96</td><td>11,443.011</td></tr></tbody></table></details></section>
<section id="evidence"></section></body></html>'''

class ComputeReportTests(unittest.TestCase):
    def test_compute_detail_replaces_all_raw_totals_and_filters_collective_kernels(self):
        s=scene();s['parameters']['tp']=2
        s['ranks']=[dict(rank=0,sample_cycles=[9914019,9914019],step_count=2,module_cycles={'GDN':9154409,'通信':10673629},mean_step_cycles=9914019)]
        snapshot=copy.deepcopy(s)
        rendered=report.compute_document(RAW,s,0)
        root=html.document_fromstring(rendered)
        self.assertIn('11.4430',root.text_content())
        self.assertNotIn('24.7850',root.text_content())
        self.assertNotIn('zccl_allreduce',rendered)
        self.assertIn('qwen_pre_attn_norm_gdn_kernel',rendered)
        self.assertIn('100.00%',root.get_element_by_id('modules').text_content())
        self.assertIn('缺测',root.get_element_by_id('framework').text_content())
        self.assertNotIn('24,733.434',rendered)
        self.assertEqual(s,snapshot)

    def test_tp1_phase_values_survive_and_missing_tp2_communication_is_not_zero(self):
        s=scene()
        self.assertIn('24,733.434',report.compute_document(RAW,s,0))
        s['parameters']['tp']=2
        root=html.document_fromstring(report.compute_document(RAW,s,0))
        self.assertIn('缺测',root.xpath('//div[@class="metric primary"]')[0].text_content())

    def test_archived_html_remains_unchanged_and_reused_reports_get_derived_pages(self):
        s=scene();s['details']={'0':'runs/aaaaaaaaaaaaaaaa/short/rank0.html'}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);path=root/s['details']['0'];path.parent.mkdir(parents=True);path.write_text(RAW)
            report.write_compute_details(root,[dict(scenes=[s])])
            self.assertEqual(path.read_text(),RAW)
            self.assertTrue(path.with_name('rank0-compute.html').exists())
