import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from publisher.report import CASES, sanitize, write_report
from publisher.source import decode
from publisher.state import seal, unseal

class PublisherTests(unittest.TestCase):
    def sample(self):
        rows = [{'id': case, 'status': 'measured', 'cycles': 0} for case in CASES]
        launches = [{'case': case, 'kernel': 'probe', 'core0_cycles': 0,
                     'core1_cycles': 0, 'max_cycles': 0, 'status': 'measured'} for case in CASES]
        return {'cases': rows, 'launches': launches}, {
            'created_at': '2026-10-13T10:00:00+00:00', 'commit': 'a'*40}

    def test_only_whitelisted_data_is_published(self):
        raw, manifest = self.sample()
        raw['private'] = 'PRIVATE_CANARY'
        raw['cases'][0]['error'] = 'PRIVATE_CANARY'
        manifest['run_url'] = 'PRIVATE_CANARY'
        result = sanitize(raw, manifest, 'a'*16)
        with tempfile.TemporaryDirectory() as directory:
            write_report(result, Path(directory))
            for path in Path(directory).iterdir():
                self.assertNotIn('PRIVATE_CANARY', path.read_text(encoding='utf-8-sig'))
        self.assertEqual(result['cases'][0]['cycles'], 0)

    def test_missing_is_not_zero(self):
        raw, manifest = self.sample()
        raw['cases'][0].update(status='failed', cycles=None)
        self.assertIsNone(sanitize(raw, manifest, 'a'*16)['cases'][0]['cycles'])

    def test_invalid_measurement_fails_closed(self):
        for value in (-1, True, 1.5):
            raw, manifest = self.sample()
            raw['cases'][0]['cycles'] = value
            with self.assertRaises((ValueError, RuntimeError)):
                sanitize(raw, manifest, 'a'*16)

    def test_complete_state_including_identity_is_encrypted(self):
        payload = {'ou_PRIVATE_CANARY.enc': 'PRIVATE_CANARY'}
        encrypted = seal(payload, b'a'*32)
        self.assertNotIn('PRIVATE_CANARY', json.dumps(encrypted))
        self.assertEqual(unseal(encrypted, b'a'*32), payload)
        with self.assertRaises(Exception):
            unseal(encrypted, b'b'*32)

    def test_duplicate_artifact_files_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as archive:
            archive.writestr('results.json', '{}')
            archive.writestr('folder/manifest.json', '{}')
        with self.assertRaises(RuntimeError):
            decode(data.getvalue())

if __name__ == '__main__':
    unittest.main()
