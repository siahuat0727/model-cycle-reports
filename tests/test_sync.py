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
