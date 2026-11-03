import unittest
from unittest.mock import patch
import deed_search as d

def search(name,field,kind):
    record={'fileNumber':'TEST-1','filmCode':'123','fileDate':'01/01/2000','instrumentType':'RESTR','legalDescriptions':[{'subdivision':'OAK FOREST','section':'1'}]}
    return {'records':[record] if kind=='RESTR' else [],'limited':False,'field':field,'type':kind,'name':name,'retrievedAt':'2026-10-29'}

class SubdivisionTests(unittest.TestCase):
    def test_search_without_property_deduplicates_and_ranks(self):
        with patch.object(d,'get_property') as parcel,patch.object(d,'clerk_search',side_effect=search) as clerk:
            result=d.search_subdivision(' Oak Forest ','1')
        parcel.assert_not_called()
        self.assertEqual(clerk.call_count,4)
        self.assertIsNone(result['property'])
        self.assertEqual(result['subdivision'],{'name':'OAK FOREST','section':'1'})
        self.assertEqual(result['searchMode'],'subdivision')
        self.assertEqual(len(result['records']),1)
        self.assertEqual(result['records'][0]['match']['scope'],'section')
        self.assertEqual(len(result['records'][0]['foundBy']),2)

    def test_optional_and_embedded_section(self):
        with patch.object(d,'clerk_search',side_effect=search):
            self.assertEqual(d.search_subdivision('Oak Forest')['subdivision']['section'],'')
            self.assertEqual(d.search_subdivision('Oak Forest Section One')['subdivision'],{'name':'OAK FOREST','section':'1'})

    def test_invalid_or_conflicting_inputs_do_not_search(self):
        with patch.object(d,'clerk_search') as clerk:
            for name,section in [('', ''),('ab',''),('a'*141,''),('123',''),('Oak Forest','x'),('Oak Forest Sec 1','2')]:
                with self.subTest(name=name),self.assertRaises(ValueError):d.search_subdivision(name,section)
            clerk.assert_not_called()

    def test_failures_remain_visible(self):
        with patch.object(d,'clerk_search',side_effect=ValueError('Unavailable')):
            result=d.search_subdivision('Oak Forest')
        self.assertEqual(result['status'],'partial')
        self.assertEqual(len(result['errors']),4)
        self.assertEqual(result['records'],[])
        self.assertIn('No results does not mean unrestricted',result['limitation'])
