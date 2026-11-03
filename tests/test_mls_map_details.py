import unittest
import pymupdf
from shapely.geometry import box
from test_mls import fixture
from test_mls_boundary import roads
from mls_map import property_label,fit_address,map_pdf,label_layout

class MapPropertyDetails(unittest.TestCase):
 def test_address_land_area_and_use_label(self):
  row=fixture()['parcels'][0]
  self.assertEqual(property_label(row),'1500\n6,500 sq ft\nSingle-family')
  row['area']=6500.25;row['use']='COM'
  self.assertEqual(property_label(row),'1500\n6,500.25 sq ft\nCommercial')
 def test_missing_values_are_explicit(self):
  row=fixture()['parcels'][0];row['use']='UNKNOWN'
  for area in [None,0,-10,'bad',float('nan'),float('inf')]:
   row['area']=area;self.assertEqual(property_label(row),'1500\nArea unknown\nUse unknown')
 def test_legal_lot_use_overrides_and_mixed_uses(self):
  row=fixture()['parcels'][0];row['lots']=[{'use':'MF'},{'use':'MF'}]
  self.assertTrue(property_label(row).endswith('Multifamily'))
  row['lots'][1]['use']='VAC';self.assertTrue(property_label(row).endswith('Mixed uses'))
  row['lots'][1]['use']='UNKNOWN';self.assertTrue(property_label(row).endswith('Use partly unknown'))
 def test_full_label_fits_inside_parcel_at_readable_size(self):
  value=property_label(fixture()['parcels'][0]);parcel=box(0,0,50,90)
  position=fit_address(value,parcel,[]);self.assertIsNotNone(position)
  self.assertTrue(parcel.covers(position[-1]));self.assertAlmostEqual(position[2],0)
  self.assertGreaterEqual(min(line[2] for line in label_layout(value,position[3])[0]),7.5)
 def test_rendered_map_includes_selected_property_details(self):
  c=fixture();c['roads']=roads();c['parcels'][0]['use']='MF';c['parcels'][1]['use']='VAC'
  c['parcels'][-1].update(selected=False,area=99999,use='COM')
  with pymupdf.open(stream=map_pdf(c),filetype='pdf') as doc:
   self.assertEqual(len(doc),1);text=doc[0].get_text()
   self.assertIn('6,500 sq ft',text);self.assertIn('Multifamily',text);self.assertIn('Vacant',text)
   self.assertEqual(text.count('Single-family'),5);self.assertNotIn('99,999',text);self.assertNotIn('Commercial',text)
   self.assertIn('land area / land use',text);self.assertEqual(doc[0].get_images(),[])
 def test_narrow_property_keeps_all_details_in_callout(self):
  c=fixture();c['roads']=roads();row=c['parcels'][0];row['area']=123.45;row['use']='COM'
  ring=row['geometry']['coordinates'][0];x=ring[0][0]
  row['geometry']['coordinates']=[[[min(v[0],x+.000003),v[1]] for v in ring]]
  with pymupdf.open(stream=map_pdf(c),filetype='pdf') as doc:
   self.assertIn('123.45 sq ft',doc[0].get_text());self.assertIn('Commercial',doc[0].get_text())
