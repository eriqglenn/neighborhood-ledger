import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import pymupdf
from deed_documents import DocumentLibrary, CountyBrowser, choose_record, pdf_pages

def sample_pdf():
    with pymupdf.open() as doc:
        for n in range(2):
            page=doc.new_page();page.insert_text((72,72),'TEST RECORDING A123 - PAGE '+str(n+1))
        return doc.tobytes()

class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.library=DocumentLibrary(self.temp.name)
        self.record={'fileNumber':'A123','filmCode':'123','instrumentType':'RESTR','viewerUrl':'https://www.cclerk.hctx.net/Applications/WebSearch/EComm/ViewEdocs.aspx?ID=a'}
        self.pdf=sample_pdf()
    def tearDown(self):self.temp.cleanup()
    def test_pdf_validation_rejects_html_truncation_and_encryption(self):
        for content in [b'<html>Sign in</html>',b'%PDF-invalid']:
            with self.assertRaises(ValueError):pdf_pages(content)
        with pymupdf.open(stream=self.pdf,filetype='pdf') as doc:
            locked=doc.tobytes(encryption=pymupdf.PDF_ENCRYPT_AES_256,owner_pw='owner',user_pw='reader')
        with self.assertRaises(ValueError):pdf_pages(locked)
    def test_save_preview_list_and_duplicate_preserve_identity(self):
        a=self.library.save('0730990160019',self.record,self.pdf,self.record['viewerUrl'])
        b=self.library.save('0730990160019',self.record,self.pdf,self.record['viewerUrl'])
        self.assertEqual(a['id'],b['id']);self.assertEqual(a['pages'],2)
        self.assertEqual(len(self.library.list('0730990160019')),1)
        self.assertEqual(self.library.list('1168330120013'),[])
        self.assertTrue(self.library.page(a['id'],2).startswith(b'\x89PNG'))
        self.assertEqual(self.library.content(a['id']),self.pdf)
        with self.assertRaises(ValueError):self.library.page(a['id'],3)
    def test_tampering_and_traversal_rejected(self):
        a=self.library.save('0730990160019',self.record,self.pdf,self.record['viewerUrl'])
        (self.library.root/(a['id']+'.pdf')).write_bytes(b'changed')
        with self.assertRaises(ValueError):self.library.content(a['id'])
        with self.assertRaises(ValueError):self.library.metadata('../outside')
        with self.assertRaises(ValueError):self.library.list('invalid')
    def test_untrusted_pdf_source_rejected(self):
        with self.assertRaises(ValueError):self.library.save('0730990160019',self.record,self.pdf,'https://evil.example/file.pdf')
    def test_copy_requires_confirmation_and_can_be_discarded(self):
        a=self.library.save('0730990160019',self.record,self.pdf,self.record['viewerUrl'])
        self.assertEqual(a['identityStatus'],'unconfirmed')
        self.assertEqual(self.library.confirm(a['id'])['identityStatus'],'user-confirmed')
        with self.assertRaises(ValueError):self.library.discard(a['id'])
        b=self.library.save('1168330120013',self.record,self.pdf,self.record['viewerUrl'])
        self.library.discard(b['id']);self.assertEqual(self.library.list('1168330120013'),[])
    def test_session_cookie_encryption_and_scope(self):
        import county_session
        value=b'fixture-cookie-value'
        protected=county_session.protect(value)
        self.assertNotIn(value,protected)
        self.assertEqual(county_session.protect(protected,decrypt=True),value)
        cookies=[{'domain':'.cclerk.hctx.net','expires':-1},{'domain':'unrelated.example','expires':-1},{'domain':'.cclerk.hctx.net','expires':1}]
        self.assertEqual(county_session.county_cookies(cookies),cookies[:1])
    def test_fresh_link_requires_exact_file_and_film(self):
        fresh={**self.record,'viewerUrl':self.record['viewerUrl']+'fresh'}
        self.assertEqual(choose_record([fresh],self.record),fresh)
        for rows in [[],[fresh,fresh],[{**fresh,'filmCode':'other'}],[{**fresh,'fileNumber':'other'}]]:
            with self.assertRaises(ValueError):choose_record(rows,self.record)
    def test_second_browser_cannot_start_while_one_is_running(self):
        browser=CountyBrowser(self.temp.name)
        with patch('deed_documents.threading.Thread') as thread:
            thread.return_value.is_alive.return_value=True
            browser.start('0730990160019',self.record)
            with self.assertRaises(ValueError):browser.start('0730990160019',self.record)
            browser.close();self.assertTrue(browser.cancel.is_set())

if __name__=='__main__':unittest.main()
