import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from unittest.mock import patch
from publisher import catalog, report, source


def scene():
    parameters=dict(batch=1,context=18,dtype='bfloat16',tp=1,ep=1,quantization='none',fixture='synthetic',seed=42,decode_steps=3,geometry={'hidden':1024})
    compare=dict(model_id='qwen35-08b',parameters=parameters,protocol=catalog.PROTOCOL,frequency_mhz=400)
    return dict(scene_id='short',model_id='qwen35-08b',model='Qwen3.5-0.8B',parameters=parameters,protocol=catalog.PROTOCOL,
        frequency_mhz=400,comparison_key=catalog.digest(compare),status='passed',environment={'triton':'3.6.0','simulator_sha256':'a'*64},
        ranks=[dict(rank=0,sample_cycles=[100,102],step_count=2,module_cycles={'GDN':200,'辅助':2},mean_step_cycles=101)],probe_baseline_cycles=95,probe_rank=0)


def run(ident,scenes=None):
    return dict(report_id=ident*16,commit='c'*40,created_at='2026-10-19T01:00:00+00:00',scenes=scenes or [scene()])


class CatalogTests(unittest.TestCase):
    def test_identical_new_run_retains_timepoint_and_reuses_details(self):
        entries,writes=catalog.append([],run('a'))
        self.assertEqual(len(writes),1)
        entries,writes=catalog.append(entries,run('b'))
        self.assertEqual(len(entries),2);self.assertEqual(writes,[])
        self.assertEqual(entries[-1]['scenes'][0]['same_as'],'a'*16)
        self.assertEqual(entries[-1]['scenes'][0]['details'],entries[0]['scenes'][0]['details'])
        self.assertEqual(catalog.append(entries,run('b'))[0],entries)

    def test_rounding_is_not_used_for_equality_and_toolchain_change_is_not_hidden(self):
        entries,_=catalog.append([],run('a'))
        changed=scene();changed['ranks'][0].update(sample_cycles=[100,103],module_cycles={'GDN':201,'辅助':2},mean_step_cycles=101.5)
        _,writes=catalog.append(entries,run('b',[changed]));self.assertEqual(len(writes),1)
        changed=scene();changed['environment']['triton']='new'
        _,writes=catalog.append(entries,run('b',[changed]));self.assertEqual(len(writes),1)

    def test_missing_and_nonfinite_measurements_never_become_zero(self):
        for value in (float('nan'),-1,1.1):
            invalid=scene();invalid['ranks'][0]['sample_cycles'][0]=value
            with self.assertRaises(ValueError):catalog.validate_scene(invalid)
        invalid=scene();invalid['ranks']=[]
        with self.assertRaises(ValueError):catalog.validate_scene(invalid)
        invalid.update(status='dependency_unavailable')
        self.assertEqual(catalog.validate_scene(invalid)['ranks'],[])
        invalid=scene();invalid['ranks'][0]['module_cycles']['GDN']=201
        with self.assertRaises(ValueError):catalog.validate_scene(invalid)

    def test_failed_scene_does_not_hide_success_and_paths_are_rejected(self):
        passed=scene();failed=copy.deepcopy(passed);failed.update(scene_id='long',status='failed',ranks=[])
        data=run('a',[passed,failed]);entries,writes=catalog.append([],data)
        self.assertEqual(len(entries[0]['scenes']),2);self.assertEqual(len(writes),1)
        for unsafe in ('../escape','https://secret','ou_personal'):
            invalid=scene();invalid['model']=unsafe
            with self.assertRaises(ValueError):catalog.validate_scene(invalid)

    def test_rank_srcdoc_is_unwrapped_then_sanitized(self):
        import html
        from test_publisher import HTML,INFO
        raw=''.join(f'<section data-rank="{r}"><iframe srcdoc="{html.escape(HTML,quote=True)}"></iframe></section>' for r in range(2))
        docs=report.rank_documents(raw,[0,1]);self.assertEqual(set(docs),{'0','1'})
        self.assertNotIn('PRIVATE_CANARY',report.sanitize(docs['1'],INFO))
        with self.assertRaises(ValueError):report.rank_documents(raw,[0])

    def test_suite_archive_reads_only_passed_scene_details(self):
        data=dict(schema_version=1,run=dict(commit='c'*40),scenes=[scene(),dict(scene_id='pending',status='dependency_unavailable')])
        raw=io.BytesIO()
        with zipfile.ZipFile(raw,'w') as archive:
            archive.writestr('measurement-summary.json',json.dumps(data));archive.writestr('short/report.html','<html>safe</html>')
        summary,docs=source.bundle(raw.getvalue());self.assertEqual(len(summary['scenes']),2);self.assertEqual(set(docs),{'short'})

    def test_discovery_includes_failed_runs_and_oldest_first(self):
        env=dict(SOURCE_REPOSITORY='owner/repo',SOURCE_BRANCH='branch',SOURCE_ACTIONS_TOKEN='test')
        rows=[dict(id=i,run_attempt=1,head_sha='a'*40,created_at=f'2026-10-{i:02}T00:00:00Z',event='workflow_dispatch',conclusion='failure') for i in (2,1)]
        def request(method,url,token):
            if '/artifacts?' not in url:return {'workflow_runs':rows}
            i=int(url.split('/runs/')[1].split('/')[0]);return {'artifacts':[dict(id=i,name='model-cycles',expired=False,archive_download_url='https://example.test')]}
        with patch.dict('os.environ',env),patch('publisher.source.request',side_effect=request):
            self.assertEqual([r['run_id'] for r in source.available()],[1,2])
