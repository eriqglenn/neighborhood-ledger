import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import neighborops_server as app
import plat_service
from plat_ingestion import REPORT_PAGE
from test_plat_ingestion import workbook


class ServiceTests(unittest.TestCase):
    def test_live_then_offline_retains_original_evidence(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            def fetch(url):
                return b'<a href="Plat-Current-Agenda-Spreadsheet-09-14-2026.xlsx">Report</a>' if url==REPORT_PAGE else workbook()
            live=plat_service.scan_archive(root=root,fetch=fetch)
            pointer=(root/'plat_evidence'/'latest.json').read_bytes()
            def offline(url): raise OSError('offline')
            cached=plat_service.scan_archive(root=root,fetch=offline)
            self.assertEqual(cached['status'],'cached')
            for k in ('sourceUrl','sha256','retrievedAt'):
                self.assertEqual(cached[k],live[k])
            self.assertEqual(pointer,(root/'plat_evidence'/'latest.json').read_bytes())
            self.assertNotEqual(live['runId'],cached['runId'])

    def test_packaged_cache_hash_is_pinned(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)
            (root/'plat_cache_2026-07-09.xlsx').write_bytes((Path(__file__).parent/'fixtures'/'plat_cache_2026-07-09.xlsx').read_bytes())
            snapshot=plat_service.cached_snapshot(root)
            self.assertIsNone(snapshot.retrieved_at)
            self.assertEqual(snapshot.sha256,plat_service.PACKAGED_HASH)

    def test_app_calls_reliable_scanner(self):
        with patch.object(plat_service,'scan_plats',return_value={'results':[],'status':'success'}) as mocked:
            self.assertEqual(app.scan_plats()['status'],'success')
            mocked.assert_called_once()

    def test_plat_ingestion_does_not_depend_on_boundary(self):
        with tempfile.TemporaryDirectory() as d, patch.object(app,'get_boundary',side_effect=AssertionError('must not geocode')):
            def fetch(url):
                return b'<a href="Plat-Current-Agenda-Spreadsheet-09-14-2026.xlsx">Report</a>' if url==REPORT_PAGE else workbook()
            data=plat_service.scan_archive(root=Path(d),fetch=fetch)
            self.assertEqual(len(data['results']),1)
            self.assertNotIn('lat',data['results'][0])


if __name__=='__main__': unittest.main()

