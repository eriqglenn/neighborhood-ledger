import datetime as dt
import hashlib
import io
import unittest
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from plat_ingestion import Snapshot, IngestionError, discover, ingest, scan, REPORT_PAGE

URL = 'https://www.houstontx.gov/planning/old.xlsx'
STAMP = '2026-07-10T12:00:00+00:00'
HEAD = ['App No.','Subdivision Name','Super Neighborhood','PC Date','Application Status']
GOOD = ['2026-0751','Liberty Green','GREATER FIFTH WARD','2026-07-09','Inactive Application']


def workbook(rows=None, *, sheets=None, epoch1904=False):
    sheets = sheets or [('Plats', rows if rows is not None else [HEAD,GOOD])]
    out=io.BytesIO()
    with zipfile.ZipFile(out,'w') as z:
        z.writestr('xl/workbook.xml','<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><workbookPr date1904="'+str(int(epoch1904))+'"/><sheets>'+''.join(f'<sheet name="{name}" sheetId="{i}" r:id="r{i}"/>' for i,(name,_) in enumerate(sheets,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="r{i}" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(sheets)+1))+'</Relationships>')
        for i,(_,values) in enumerate(sheets,1):
            cells=''.join(f'<row r="{n}">'+''.join(f'<c r="{chr(65+j)}{n}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>' for j,v in enumerate(row))+'</row>' for n,row in enumerate(values,1))
            z.writestr(f'xl/worksheets/sheet{i}.xml','<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'+cells+'</sheetData></worksheet>')
    return out.getvalue()


def snap(content=None, url=URL):
    content = content if content is not None else workbook()
    return Snapshot(content,url,STAMP,hashlib.sha256(content).hexdigest())


class PlatTests(unittest.TestCase):
    def test_exact_geography_only(self):
        names=['GREATER FIFTH WARD',' greater  fifth ward ','FIFTH WARD','GREATER FIFTH WARD EAST','55','77026','','GREATER FIFTH WARD / OTHER']
        rows=[HEAD]+[[str(i),'Name',name,'2026-07-09',''] for i,name in enumerate(names)]
        data=ingest(snap(workbook(rows)))
        self.assertEqual(len(data['results']),2)
        self.assertEqual(len(data['rejected']),6)

    def test_missing_schema_fails_not_zero(self):
        with self.assertRaises(IngestionError): ingest(snap(workbook([['Wrong'],['55']])))

    def test_zero_matches_is_success(self):
        row=GOOD.copy(); row[2]='OTHER'
        result=ingest(snap(workbook([HEAD,row])))
        self.assertEqual(result['results'],[])
        self.assertEqual(result['status'],'success')

    def test_header_only_valid_empty(self):
        self.assertEqual(ingest(snap(workbook([HEAD])))['totalRows'],0)

    def test_cover_sheet_and_preamble(self):
        data=ingest(snap(workbook(sheets=[('Cover',[['Notes']]),('Data',[['Title'],[],HEAD,GOOD])])))
        p=data['results'][0]['provenance'][0]
        self.assertEqual((p['sheet'],p['row']),('Data',4))

    def test_ambiguous_columns_fail(self):
        with self.assertRaises(IngestionError): ingest(snap(workbook([HEAD+['Super Neighborhood'],GOOD+['OTHER']])))

    def test_similar_geography_column_not_alias(self):
        head=HEAD.copy();head[2]='Prior Super Neighborhood'
        with self.assertRaises(IngestionError): ingest(snap(workbook([head,GOOD])))

    def test_blank_identity_quarantined(self):
        row=GOOD.copy();row[0]=''
        data=ingest(snap(workbook([HEAD,row])))
        self.assertEqual(data['results'],[])
        self.assertEqual(data['rejected'][0]['reason'],'missing_identity')

    def test_bad_date_quarantined(self):
        row=GOOD.copy();row[3]='2026-02-30'
        self.assertEqual(ingest(snap(workbook([HEAD,row])))['rejected'][0]['reason'],'invalid_pc_date')

    def test_both_excel_epochs(self):
        target=dt.datetime(2026,7,9)
        for epoch,flag in [(dt.datetime(1899,12,30),False),(dt.datetime(1904,1,1),True)]:
            row=GOOD.copy();row[3]=str((target-epoch).days)
            self.assertEqual(ingest(snap(workbook([HEAD,row],epoch1904=flag)))['results'][0]['date'],'2026-07-09')

    def test_no_invented_coordinates(self):
        record=ingest(snap())['results'][0]
        self.assertNotIn('lat',record)
        self.assertNotIn('lng',record)

    def test_identical_duplicate_has_all_evidence(self):
        data=ingest(snap(workbook([HEAD,GOOD,GOOD])))
        self.assertEqual(len(data['results']),1)
        self.assertEqual(len(data['results'][0]['provenance']),2)

    def test_conflicting_duplicate_fails(self):
        changed=GOOD.copy();changed[4]='Approved'
        with self.assertRaises(IngestionError): ingest(snap(workbook([HEAD,GOOD,changed])))

    def test_discovery_orders_dates_and_ignores_bad_links(self):
        links=['Plat-Current-Agenda-Spreadsheet-09-14-2026.xlsx','Plat-Current-Agenda-Spreadsheet-13-40-2026.xlsx','Plat-Current-Agenda-Spreadsheet-07-09-2026.xlsx','https://evil.example/Plat-Current-Agenda-Spreadsheet-12-31-2026.xlsx']
        self.assertTrue(discover(''.join(f'<a href="{u}">x</a>' for u in links)).endswith('09-14-2026.xlsx'))

    def test_discovery_failure_is_explicit(self):
        with self.assertRaises(IngestionError): discover('<a href="/new-portal">Current report</a>')

    def test_cache_keeps_real_url_and_original_time(self):
        new='Plat-Current-Agenda-Spreadsheet-09-14-2026.xlsx'
        def fetch(url):
            if url==REPORT_PAGE: return f'<a href="{new}">x</a>'.encode()
            raise OSError('offline')
        data=scan(fetch,cache=snap())
        self.assertEqual(data['status'],'cached')
        self.assertEqual(data['sourceUrl'],URL)
        self.assertEqual(data['retrievedAt'],STAMP)
        self.assertNotEqual(data['attemptedUrl'],URL)
        self.assertEqual(data['results'][0]['provenance'][0]['sourceUrl'],URL)
        self.assertTrue(data['warnings'])

    def test_corrupt_download_can_use_labeled_cache(self):
        def fetch(url):
            return b'<a href="Plat-Current-Agenda-Spreadsheet-09-14-2026.xlsx">x</a>' if url==REPORT_PAGE else b'HTML error page'
        self.assertEqual(scan(fetch,cache=snap())['status'],'cached')

    def test_failure_without_cache(self):
        with self.assertRaises(IngestionError): scan(lambda url: b'No workbook')

    def test_tampered_cache_rejected(self):
        with self.assertRaises(IngestionError): ingest(Snapshot(workbook(),URL,STAMP,'wrong'))

    def test_nonofficial_snapshot_rejected(self):
        with self.assertRaises(IngestionError): ingest(snap(url='https://untrusted.example/report.xlsx'))

    def test_invalid_timestamp_rejected(self):
        s=snap()
        with self.assertRaises(IngestionError): ingest(Snapshot(s.content,s.source_url,'2026-07-10',s.sha256))

    def test_live_archive_does_not_claim_current_agenda(self):
        def fetch(url):
            return b'<a href="Plat-Current-Agenda-Spreadsheet-09-14-2026.xlsx">x</a>' if url==REPORT_PAGE else workbook()
        data=scan(fetch,now=STAMP)
        self.assertEqual(data['status'],'success')
        self.assertIn('not_current_agenda',data['freshness'])

    def test_packaged_real_fixture(self):
        content=(Path(__file__).parent/'fixtures'/'plat_cache_2026-07-09.xlsx').read_bytes()
        result=ingest(snap(content))
        self.assertEqual(result['totalRows'],138)
        self.assertEqual([r['caseNo'] for r in result['results']],['2026-0751'])

    def test_newer_real_fixture_date_header(self):
        content=(Path(__file__).parent/'fixtures'/'plat_2026-09-14.xlsx').read_bytes()
        result=ingest(snap(content))
        self.assertEqual(result['totalRows'],122)
        self.assertEqual({r['caseNo'] for r in result['results']},{'2026-1470','2026-1452','2026-1439'})
        self.assertTrue(all(r['date']=='2026-09-17' for r in result['results']))

    def test_packaged_retrieval_time_not_invented(self):
        s=snap()
        data=ingest(Snapshot(s.content,s.source_url,None,s.sha256),mode='cache')
        self.assertIsNone(data['retrievedAt'])
        self.assertTrue(data['warnings'])


if __name__=='__main__': unittest.main()
