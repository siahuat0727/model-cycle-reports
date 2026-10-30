import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import Mock, patch
from publisher import catalog, publication
from publisher.sync import Publisher, dashboard_revision
from test_catalog import run, scene
from test_publisher import HTML


class PublicationTests(unittest.TestCase):
    def test_invalid_scene_configuration_is_rejected_before_publication(self):
        with tempfile.TemporaryDirectory() as tmp:
            config=Path(tmp)/'publication.json'
            for value in ({'scene_ids':[]},{'scene_ids':['short','short']},{'scene_ids':'short'},{'scene_ids':['../unsafe']},{'unexpected':[]}):
                config.write_text(json.dumps(value))
                with patch('publisher.publication.CONFIG',config):
                    with self.assertRaises(ValueError):publication.scene_ids()

    def test_select_preserves_real_observations_and_never_renames_scenes(self):
        old=scene();old['scene_id']='retired-context'
        original=run('a',[scene(),old]);snapshot=copy.deepcopy(original)
        selected=publication.select(original,{'short'})
        self.assertEqual(selected,dict(original,scenes=[original['scenes'][0]]))
        self.assertEqual(original,snapshot)
        self.assertIsNone(publication.select(run('b',[old]),{'short'}))

    def test_pruning_preserves_reused_detail_and_removes_retired_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);keep=root/'runs/shared/short/rank0.html'
            retired=root/'runs/old/retired-context/rank0.html'
            metadata=root/'runs/old/retired-context/info.json'
            for path in (keep,retired,metadata):
                path.parent.mkdir(parents=True,exist_ok=True);path.write_text('detail')
            entries=[dict(scenes=[dict(details={'0':'runs/shared/short/rank0.html'})])]*2
            publication.prune_details(root,entries)
            self.assertTrue(keep.is_file());self.assertFalse((root/'runs/old').exists())
            with self.assertRaises(ValueError):
                publication.prune_details(root,[dict(scenes=[dict(details={'0':'../outside.html'})])])

    def test_policy_changes_trigger_release_without_new_measurements(self):
        with patch('publisher.sync.dashboard_files',return_value=[]):
            with patch('publisher.publication.scene_ids',return_value={'short'}):first=dashboard_revision()
            with patch('publisher.publication.scene_ids',return_value={'short','long'}):second=dashboard_revision()
        self.assertNotEqual(first,second)

    def test_publish_filters_existing_and_new_catalog_and_build_assets(self):
        retired=scene();retired['scene_id']='retired-context'
        entries,_=catalog.append([],run('a',[scene(),retired]))
        latest=run('b',[scene(),copy.deepcopy(retired)])
        observed={}
        def command(args,cwd=None,**kwargs):
            if args[:2]==['git','clone']:
                reports=Path(args[-1])/'public/reports';reports.mkdir(parents=True)
                (reports/'catalog.json').write_text(json.dumps({'schema_version':1,'runs':entries}))
                for item in entries[0]['scenes']:
                    path=reports/item['details']['0'];path.parent.mkdir(parents=True,exist_ok=True);path.write_text(HTML)
            elif args[:3]==['npm','run','build']:
                reports=cwd/'public/reports'
                observed['catalog']=json.loads((reports/'catalog.json').read_text())
                observed['paths']=[str(p.relative_to(reports)) for p in reports.rglob('*') if p.is_file()]
                shutil.copytree(reports,cwd/'dist/output/reports')
            elif args[:3]==['git','diff','--cached']:return 'public/reports/catalog.json'
            elif args[:2]==['git','rev-parse']:return 'c'*40
            return ''
        publisher=Publisher({'app_id':'test'},'sha')
        publisher.api=Mock(side_effect=lambda cmd,*args:dict(repository_url='https://example.test/app',commit_author_name='test',commit_author_email='test@example.test') if cmd=='+git-credential-init' else {'release_id':'release'})
        publisher.persist=Mock();publisher.complete=Mock()
        with patch('publisher.sync.run',side_effect=command), patch('publisher.sync.dashboard_files',return_value=[]), patch('publisher.publication.scene_ids',return_value={'short'}):
            publisher.publish([dict(run=latest,reports={},source_key='2:1:20')],[2,1,20])
        self.assertEqual(len(observed['catalog']['runs']),2)
        self.assertTrue(all([s['scene_id'] for s in r['scenes']]==['short'] for r in observed['catalog']['runs']))
        self.assertFalse(any('retired-context' in path for path in observed['paths']))
        self.assertEqual(observed['catalog']['runs'][1]['scenes'][0]['same_as'],'a'*16)
        publisher.complete.assert_called_once()
