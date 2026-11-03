import unittest
from unittest.mock import patch
import deed_search as d

ROW = '''<table><tr><td><span id="r_lblFileNo">A123</span></td><td><span id="r_lblFileDate">01/02/2020</span><a id="r_lnkdetailtest">RESTR</a></td><td><table><tr><td><b>Grantee</b>:</td><td><span id="r_lvOR_0_lblNames">EXAMPLE SEC 2</span></td></tr></table></td><td><span id="r_lvLegal_0_lblSubDivAdd">EXAMPLE</span><span id="r_lvLegal_0_lblSection">2</span><span id="r_lvLegal_0_lblLot">1-8</span><span id="r_lvLegal_0_lblBlock">4</span><span id="r_lvLegal_1_lblSubDivAdd">EXAMPLE</span><span id="r_lvLegal_1_lblSection">3</span></td><td><span id="r_lblPgs">4</span><a id="r_HyperLinkFCEC" href="EComm/ViewEdocs.aspx?ID=test">111222</a></td></tr></table>'''

class DeedTests(unittest.TestCase):
    def test_parser_preserves_multiple_legals_and_observed_link(self):
        rows,limited=d.parse_records(ROW)
        self.assertFalse(limited)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['grantees'],['EXAMPLE SEC 2'])
        self.assertEqual([x['section'] for x in rows[0]['legalDescriptions']],['2','3'])
        self.assertEqual(rows[0]['viewerUrl'],d.CLERK.rsplit('/',1)[0]+'/EComm/ViewEdocs.aspx?ID=test')

    def test_wrong_host_link_rejected(self):
        for url in ['https://evil.example/doc','javascript:alert(1)','https://www.cclerk.hctx.net@evil.example/a','http://www.cclerk.hctx.net/a']:
            with self.subTest(url=url),self.assertRaises(ValueError):
                d.parse_records(ROW.replace('EComm/ViewEdocs.aspx?ID=test',url))

    def test_unrecognized_page_is_not_empty_success(self):
        for body in ['<h1>Sign in</h1>','<h1>Access denied</h1>','<html>Changed form</html>']:
            with self.assertRaises(ValueError):d.parse_records(body)
        self.assertEqual(d.parse_records('<p>No records found.</p>'),([],False))

    def test_more_pages_are_disclosed(self):
        self.assertTrue(d.parse_records(ROW+'<a href="javascript:next()">Next</a>')[1])

    def test_address_normalization_preserves_direction(self):
        n,street,variants=d.address_parts('1200 North Main Street, Houston, TX')
        self.assertEqual(n,1200);self.assertEqual(street,'1200 N MAIN ST')
        self.assertIn('MAIN',variants)
        self.assertNotEqual(d.canonical('1200 S Main St'),street)

    def test_invalid_queries_do_not_call_services(self):
        with patch.object(d,'parcel_query') as query:
            for text in ['','Main Street','a'*181]:
                with self.assertRaises(ValueError):d.find_properties(text)
            for account in ['123',"' OR 1=1",None]:
                with self.assertRaises(ValueError):d.get_property(account)
            query.assert_not_called()

    def test_partial_failure_is_not_unrestricted(self):
        prop={'searchName':'EXAMPLE','section':'2','account':'1234567890123'}
        def search(name,field,kind):
            if kind=='AMEND':raise ValueError('Unavailable')
            return {'records':d.parse_records(ROW)[0],'limited':False,'field':field,'type':kind,'name':name,'retrievedAt':'2026-10-27'}
        with patch.object(d,'get_property',return_value=prop),patch.object(d,'clerk_search',side_effect=search):
            result=d.search_restrictions(prop['account'])
        self.assertEqual(result['status'],'partial');self.assertEqual(len(result['errors']),2)
        self.assertEqual(len(result['records']),1)
        self.assertEqual(len(result['records'][0]['foundBy']),2)
        self.assertIn('No results does not mean unrestricted',result['limitation'])

    def test_multiple_conflicting_parcels_are_rejected(self):
        a={'HCAD_NUM':'1234567890123','site_str_num':1,'site_str_name':'MAIN','legal_dscr_2':'EXAMPLE SEC 1'}
        with patch.object(d,'parcel_query',return_value={'features':[{'attributes':a},{'attributes':{**a,'legal_dscr_2':'OTHER'}}]}):
            with self.assertRaises(ValueError):d.get_property(a['HCAD_NUM'])

if __name__=='__main__':unittest.main()
