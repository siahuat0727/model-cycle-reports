import unittest
from unittest.mock import Mock, patch
from publisher.sync import Publisher

class SyncTests(unittest.TestCase):
    def test_completed_release_records_source_after_commit_verification(self):
        payload={'app_id':'test','pending':{'release_id':'release',
                 'commit':'a'*40,'source':[1,1,2],'files':{}}}
        publisher=Publisher(payload,'sha')
        publisher.api=Mock(return_value={'status':'finished','commit_id':'a'*40})
        publisher.persist=Mock()
        publisher.complete()
        self.assertEqual(payload['last_source'],[1,1,2])
        self.assertNotIn('pending',payload)

    def test_wrong_release_commit_does_not_mark_result_published(self):
        payload={'app_id':'test','pending':{'release_id':'release',
                 'commit':'a'*40,'source':[1,1,2],'files':{}}}
        publisher=Publisher(payload,'sha')
        publisher.api=Mock(return_value={'status':'finished','commit_id':'b'*40})
        publisher.persist=Mock()
        with self.assertRaises(RuntimeError):publisher.complete()
        self.assertNotIn('last_source',payload)
        self.assertIn('pending',payload)

    def test_ambiguous_release_is_not_submitted_again(self):
        payload={'app_id':'test','unconfirmed':{'started_ms':1}}
        publisher=Publisher(payload,'sha')
        publisher.api=Mock(return_value={'releases':[]})
        with self.assertRaises(RuntimeError):publisher.resume()
        publisher.api.assert_called_once_with('+release-list')

if __name__=='__main__':unittest.main()

class ExternalOperationTests(unittest.TestCase):
    def test_credential_urls_do_not_escape_failure_or_timeout(self):
        import subprocess
        from publisher.sync import run
        for failure in [Mock(returncode=1,stdout='https://user:PRIVATE_TOKEN@example.test',stderr=''),subprocess.TimeoutExpired(['git','https://user:PRIVATE_TOKEN@example.test'],1)]:
            with patch('publisher.sync.subprocess.run',**({'side_effect':failure} if isinstance(failure,Exception) else {'return_value':failure})):
                with self.assertRaises(RuntimeError) as error:run(['git','https://user:PRIVATE_TOKEN@example.test'])
                self.assertNotIn('PRIVATE_TOKEN',str(error.exception))

class DashboardRevisionTests(unittest.TestCase):
    def test_release_records_ui_revision_only_after_completion(self):
        payload={'app_id':'test','pending':{'release_id':'release','commit':'a'*40,'source':[1,1,2],
                 'sources':[],'files':{},'dashboard_revision':'revision'}}
        publisher=Publisher(payload,'sha');publisher.api=Mock(return_value={'status':'finished','commit_id':'a'*40});publisher.persist=Mock()
        publisher.complete();self.assertEqual(payload['dashboard_revision'],'revision')
        self.assertEqual(payload['published_sources'],[])

class RecoveryTests(unittest.TestCase):
    def test_forced_redeploy_creates_fresh_commit_but_regular_noop_skips_release(self):
        from pathlib import Path
        import shutil
        for force in (False,True):
            with self.subTest(force=force):
                calls=[]
                def command(args,cwd=None,**kwargs):
                    calls.append(args)
                    if args[:2]==['git','clone']:
                        (Path(args[-1])/'public/reports').mkdir(parents=True)
                    elif args[:3]==['npm','run','build']:
                        shutil.copytree(cwd/'public/reports',cwd/'dist/output/reports')
                    elif args[:2]==['git','rev-parse']:
                        return ('b' if force else 'a')*40
                    return ''
                payload=dict(app_id='test',published_commit='a'*40,published_sources=['old'],last_source=[1,1,2])
                publisher=Publisher(payload,'sha')
                publisher.command=Mock(side_effect=command)
                publisher.api=Mock(side_effect=lambda cmd,*args:dict(repository_url='https://example.test/app',commit_author_name='test',commit_author_email='test@example.test') if cmd=='+git-credential-init' else {'release_id':'new-release'})
                publisher.persist=Mock();publisher.complete=Mock()
                with patch('publisher.sync.dashboard_files',return_value=[]),patch('publisher.publication.scene_ids',return_value={'short'}):
                    publisher.publish([],[1,1,2],force=force)
                commits=[c for c in calls if c[:2]==['git','commit']]
                pushes=[c for c in calls if c[:2]==['git','push']]
                if force:
                    self.assertEqual(commits,[['git','commit','--allow-empty','-m','Rebuild site deployment']])
                    self.assertEqual(len(pushes),1)
                    self.assertEqual(payload['pending']['commit'],'b'*40)
                    publisher.complete.assert_called_once()
                    self.assertEqual(payload['published_commit'],'a'*40)
                else:
                    self.assertEqual(commits,[]);self.assertEqual(pushes,[])
                    publisher.complete.assert_not_called()
                    self.assertNotIn('pending',payload)
                    self.assertIn('dashboard_revision',payload)
                    self.assertEqual(payload['published_sources'],['old'])


class SharedContractRetryTests(unittest.TestCase):
    def test_old_comparison_rejection_is_rechecked_once_and_valid_result_is_recovered(self):
        from publisher.sync import collect
        from test_catalog import scene
        from test_publisher import HTML
        candidate=dict(run_id=2,attempt=1,artifact_id=20,commit='c'*40,url='https://example.test')
        document=dict(schema_version=1,run=dict(commit='c'*40,created_at='2026-10-19T01:00:00Z'),scenes=[scene()])
        payload=dict(rejected_sources={'20':dict(type='ValueError',reason='Comparison key mismatch')})
        with patch.dict('os.environ',{'SOURCE_ACTIONS_TOKEN':'test'}),patch('publisher.sync.source.download',return_value=b'data') as download,patch('publisher.sync.source.bundle',return_value=(document,{'short':HTML})),patch('publisher.sync.state.public_id',return_value='b'*16):
            data,errors=collect([candidate],payload)
        self.assertEqual(len(data),1);self.assertEqual(errors,[])
        self.assertNotIn('20',payload['rejected_sources']);download.assert_called_once()
        payload=dict(rejected_sources={'20':dict(type='ValueError',reason='Comparison key mismatch')})
        with patch.dict('os.environ',{'SOURCE_ACTIONS_TOKEN':'test'}),patch('publisher.sync.source.download',return_value=b'data') as download,patch('publisher.sync.source.bundle',side_effect=ValueError('Comparison key mismatch')):
            self.assertEqual(collect([candidate],payload),([],[]))
            self.assertEqual(collect([candidate],payload),([],[]))
            download.assert_called_once()
        payload=dict(rejected_sources={'20':dict(type='ValueError',reason='Unsafe public text')})
        with patch('publisher.sync.source.download') as download:
            self.assertEqual(collect([candidate],payload),([],[]));download.assert_not_called()
