import copy,unittest
import pymupdf
from test_mls import fixture
from test_mls_boundary import roads
from mls_text import street_name,address,description
from mls_documents import form,map_pdf,signs,worksheet
from mls_service import analysis

class StreetDisplay(unittest.TestCase):
 def test_full_types_and_ordinals(self):
  for raw,expected in [('CRYSTALWOOD DR','Crystalwood Drive'),('MAIN ST','Main Street'),('OLD RD','Old Road'),('N 22ND ST','North 22nd Street'),('McKinney AVE','McKinney Avenue'),('ST JOHN ST','St John Street'),('WEST RD','West Road'),('YALE ST N','Yale Street North')]:
   self.assertEqual(street_name(raw),expected)
   self.assertEqual(street_name(raw,True),expected.upper())
 def test_addresses_keep_units_zip_and_state(self):
  self.assertEqual(address('12103 CRYSTALWOOD DR, HOUSTON, TX 77018'),'12103 Crystalwood Drive, Houston, TX 77018')
  self.assertEqual(address('42 MAIN ST APT 5'),'42 Main Street Apt 5')
  self.assertEqual(address('42 MAIN ST Houston TX 77018'),'42 Main Street, Houston TX 77018')
 def test_existing_manual_description_keeps_qualifiers(self):
  c=fixture();c['details'].update(street='SAMPLE ST',fromStreet='FIRST ST',toStreet='SECOND ST',description='1500 block of SAMPLE ST, north side only (excluding the corner), between FIRST ST and SECOND ST.')
  self.assertEqual(description(c),'1500 block of Sample Street, north side only (excluding the corner), between First Street and Second Street.')
 def test_form_formats_saved_addresses_without_mutating_records(self):
  c=fixture();c['parcels'][0]['street']='1500 SAMPLE ST';c['details'].update(street='SAMPLE ST',fromStreet='FIRST ST',toStreet='SECOND ST',description='1500 block of SAMPLE ST, north and south sides, between FIRST ST and SECOND ST.')
  before=copy.deepcopy(c)
  with pymupdf.open(stream=form(c),filetype='pdf') as doc:
   fields={w.field_name:w.field_value for p in doc for w in (p.widgets() or [])}
   self.assertEqual(fields['address_0_0'],'1500 Sample Street')
   self.assertEqual(fields['boundaryDescription'],description(c))
   self.assertEqual(fields['support_area_0'],description(c))
  self.assertEqual(c,before)
 def test_map_matches_wizard_uppercase_full_street_names(self):
  c=fixture();c['roads']=roads()
  with pymupdf.open(stream=map_pdf(c),filetype='pdf') as doc:
   text=doc[0].get_text()
   for value in ['SAMPLE STREET','FIRST STREET','SECOND STREET']:self.assertIn(value,text)
   self.assertIn('Sample Street',text)
 def test_sign_and_schedule_use_full_street_types(self):
  c=fixture();c['details'].update(street='SAMPLE ST',description='1500 block of SAMPLE ST, north side, between First Street and Second Street.');c['parcels'][0]['street']='1500 SAMPLE ST'
  for raw in [signs(c),worksheet(c,analysis(c))]:
   with pymupdf.open(stream=raw,filetype='pdf') as doc:
    text=''.join(p.get_text() for p in doc);self.assertIn('Sample Street',text);self.assertNotIn('SAMPLE ST',text)
