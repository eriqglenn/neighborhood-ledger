import base64,json,unittest
from case_status import lookup,case_number,official_url,PAGE

CASE='12345678'
DETAIL='/en-US/checkcasestatus/casedetail/'
def record(number=CASE,alternate='',status='Resolved - Service Completed',ident='11111111-1111-1111-1111-111111111111'):
    fields={'coh_casenumber':number,'coh_alternatecasenumber':alternate,'statuscode':status,'ava_servicerequesttypeid':'Street repair','ava_addressline':'100 Test Street','createdon':'October 1, 2026','coh_customeremailaddress':'private@example.test'}
    return {'Id':ident,'EntityName':'incident','Attributes':[{'Name':k,'DisplayValue':v} for k,v in fields.items()]}
def response(rows,more=False,page=1,cookie=None):return {'Records':rows,'MoreRecords':more,'PageNumber':page,'NextPagePagingCookie':cookie}
class FakeClient:
    def __init__(self,replies=None,detail=DETAIL,entity='incident'):
        self.replies=replies or [response([])];self.calls=[];self.detail=detail;self.entity=entity
    def request(self,url,data=None,token=None):
        self.calls.append((url,data))
        if url==PAGE:
            layout={'Id':'view','Base64SecureConfiguration':'public-signed-config','Configuration':{'EntityName':self.entity,'DetailsActionLink':{'URL':{'PathWithQueryString':self.detail}}}}
            encoded=base64.b64encode(json.dumps([layout]).encode()).decode()
            return f'<div data-selected-view="view" data-get-url="/_services/entity-grid-data.json/11111111-1111-1111-1111-111111111111" data-view-layouts="{encoded}"></div>'.encode()
        if url.endswith('/tokenhtml'):return b'<input name="__RequestVerificationToken" value="test-token">'
        value=self.replies.pop(0)
        if isinstance(value,Exception):raise value
        return json.dumps(value).encode()

class CaseStatusTests(unittest.TestCase):
    def test_exact_match_only_and_private_fields_excluded(self):
        c=FakeClient([response([record(CASE+'9'),record()])]);result=lookup(CASE,c)
        self.assertEqual(result['status'],'found');self.assertEqual(result['record']['cityStatus'],'Resolved - Service Completed')
        self.assertNotIn('private',json.dumps(result));self.assertNotIn('coh_customeremailaddress',json.dumps(result))
        self.assertEqual(c.calls[-1][1]['search'],CASE)
        self.assertEqual(result['record']['url'],PAGE+'casedetail/?id=11111111-1111-1111-1111-111111111111')
    def test_alternate_number_and_case_normalization(self):
        result=lookup(' sr-1234 ',FakeClient([response([record(alternate='SR-1234')])]))
        self.assertEqual(result['status'],'found');self.assertEqual(result['caseNumber'],'SR-1234')
    def test_partial_and_address_matches_not_accepted(self):
        result=lookup(CASE,FakeClient([response([record(CASE+'9')])]))
        self.assertEqual(result['status'],'not_found');self.assertNotIn('record',result)
    def test_no_match_and_unavailable_are_distinct(self):
        self.assertEqual(lookup(CASE,FakeClient())['status'],'not_found')
        for reply in [TimeoutError(),{'error':'denied'},'login required',response([record(status='')])]:
            result=lookup(CASE,FakeClient([reply]));self.assertEqual(result['status'],'unavailable');self.assertNotIn('record',result)
    def test_pagination_exact_match_on_second_page(self):
        c=FakeClient([response([record(CASE+'1')],True,cookie='next'),response([record()],page=2)])
        self.assertEqual(lookup(CASE,c)['status'],'found');self.assertEqual(c.calls[-1][1]['pagingCookie'],'next')
    def test_ambiguity_and_incomplete_search_do_not_choose_case(self):
        self.assertEqual(lookup(CASE,FakeClient([response([record(),record(ident='22222222-2222-2222-2222-222222222222')])]))['status'],'ambiguous')
        replies=[response([record(CASE+str(p))],True,page=p,cookie='next') for p in (1,2,3)]
        self.assertEqual(lookup(CASE,FakeClient(replies))['status'],'ambiguous')
    def test_number_validation_prevents_broad_searches(self):
        for value in ['','*1234','1234*','name@example.com','100 Test Street','a'*65,'abcd','123']:
            with self.assertRaises(ValueError):case_number(value)
    def test_source_validation(self):
        for url in ['https://evil.example/','http://houston311.powerappsportals.us/','https://user@houston311.powerappsportals.us/']:
            with self.assertRaises(ValueError):official_url(url)
        for client in [FakeClient(detail='https://evil.example/case'),FakeClient(entity='contact')]:
            self.assertEqual(lookup(CASE,client)['status'],'unavailable')
    def test_lookup_uses_no_saved_result_after_failure(self):
        self.assertEqual(lookup(CASE,FakeClient([response([record()])]))['status'],'found')
        result=lookup(CASE,FakeClient([TimeoutError()]));self.assertEqual(result['status'],'unavailable');self.assertNotIn('record',result)
