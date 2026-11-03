import unittest
from communities import selected,profile
from bylaws import discover,lookup,city_url

class BylawsTests(unittest.TestCase):
    def page(self,ident,link='bylaws/55.pdf'):
        return f'<title>Super Neighborhood {ident} - Test</title><table><tr><td>BYLAWS:</td><td><a href="{link}"><b>Bylaws</b></a></td></tr></table>'
    def test_discovery_uses_actual_link_including_shared_document(self):
        url='https://www.houstontx.gov/superneighborhoods/88.html'
        self.assertEqual(discover(self.page('88','bylaws/64_88.pdf'),url,'88'),['https://www.houstontx.gov/superneighborhoods/bylaws/64_88.pdf'])
    def test_wrong_community_page_is_not_a_missing_document(self):
        with self.assertRaises(ValueError):discover(self.page('15'),'https://www.houstontx.gov/superneighborhoods/55.html','55')
    def test_unrelated_and_external_links_are_not_council_bylaws(self):
        page=self.page('55','https://unrelated.example/bylaws.pdf')+'<a href="sna-bylaws.pdf">Alliance</a>'
        self.assertEqual(discover(page,profile()['url'],'55'),[])
        for url in ['http://www.houstontx.gov/superneighborhoods/bylaws/55.pdf','https://www.houstontx.gov.evil.test/superneighborhoods/55.pdf','https://user@www.houstontx.gov/superneighborhoods/55.pdf','https://www.houstontx.gov:8443/superneighborhoods/55.pdf']:
            self.assertFalse(city_url(url))
    def test_missing_document_is_distinct_from_connection_failure(self):
        r=lookup(lambda url,limit:(b'<title>Super Neighborhood 55</title><p>BYLAWS: Not submitted</p>',url))
        self.assertEqual(r['status'],'not_posted');self.assertEqual(r['documents'],[])
        def offline(url,limit):raise OSError('Connection blocked')
        r=lookup(offline);self.assertEqual(r['status'],'unavailable');self.assertIn('Connection blocked',r['error'])
    def test_selected_community_and_pdf_validation(self):
        calls=[]
        def transport(url,limit):
            calls.append(url)
            return (self.page('25','bylaws/25.pdf').encode() if url.endswith('.html') else b'%PDF-1.7\n',url)
        with selected('25'):r=lookup(transport)
        self.assertEqual(r['communityId'],'25');self.assertEqual(r['status'],'available')
        self.assertEqual(calls,['https://www.houstontx.gov/superneighborhoods/25.html','https://www.houstontx.gov/superneighborhoods/bylaws/25.pdf'])
        r=lookup(lambda url,limit:(self.page('55').encode() if url.endswith('.html') else b'<html>Not found</html>',url))
        self.assertEqual(r['status'],'unavailable');self.assertEqual(r['documents'][0]['status'],'unavailable')
    def test_redirected_profile_does_not_borrow_another_councils_document(self):
        r=lookup(lambda url,limit:(self.page('15').encode(),'https://www.houstontx.gov/superneighborhoods/15.html'))
        self.assertEqual(r['status'],'unavailable');self.assertEqual(r['documents'],[])
