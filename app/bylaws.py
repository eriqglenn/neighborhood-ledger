"""Discover a council's posted bylaws from its official City profile page."""
import datetime as dt
import re
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from communities import profile

def city_url(url):
    parts=urllib.parse.urlsplit(url)
    return (parts.scheme=='https' and parts.hostname in {'www.houstontx.gov','houstontx.gov'}
            and parts.port in {None,443} and not parts.username and not parts.password
            and parts.path.startswith('/superneighborhoods/'))

class CityRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        if not city_url(newurl):raise ValueError('The City link redirected outside its Super Neighborhood pages.')
        return super().redirect_request(req,fp,code,msg,headers,newurl)

def fetch(url,limit):
    if not city_url(url):raise ValueError('This is not an official City Super Neighborhood link.')
    request=urllib.request.Request(url,headers={'User-Agent':'Neighborhood-Ledger/13.6.1 (public bylaws lookup)'})
    with urllib.request.build_opener(CityRedirects()).open(request,timeout=15) as response:
        if not city_url(response.url):raise ValueError('Unexpected document location.')
        return response.read(limit),response.url

class Links(HTMLParser):
    def __init__(self):
        super().__init__();self.links=[];self.current=None;self.text=[]
    def handle_starttag(self,tag,attrs):
        if tag=='a':self.current=[dict(attrs).get('href',''),'']
    def handle_data(self,text):
        self.text.append(text)
        if self.current is not None:self.current[1]+=text
    def handle_endtag(self,tag):
        if tag=='a' and self.current is not None:self.links.append(self.current);self.current=None

def discover(html,page_url,ident):
    parser=Links();parser.feed(html)
    if not re.search(r'Super\s+Neighborhood\s+(?:#\s*)?0?'+re.escape(ident)+r'\b',' '.join(parser.text),re.I):
        raise ValueError('The City response did not identify the selected Super Neighborhood.')
    urls=[]
    for href,text in parser.links:
        if not re.search(r'\bby[\s-]*laws\b',text,re.I):continue
        url=urllib.parse.urljoin(page_url,href.strip())
        parts=urllib.parse.urlsplit(url)
        if parts.scheme=='http' and parts.hostname in {'www.houstontx.gov','houstontx.gov'}:
            url=urllib.parse.urlunsplit(parts._replace(scheme='https'))
        if city_url(url) and urllib.parse.urlsplit(url).path.lower().endswith('.pdf') and url not in urls:urls.append(url)
    return urls

def lookup(transport=fetch):
    p=profile();result={'communityId':p['id'],'communityName':p['name'],'sourceUrl':p['url'],
        'checkedAt':dt.datetime.now(dt.timezone.utc).isoformat(),'documents':[]}
    try:
        raw,final=transport(p['url'],1_000_001)
        if len(raw)>1_000_000:raise ValueError('The City page exceeded the size limit.')
        if urllib.parse.urlsplit(final).path!=urllib.parse.urlsplit(p['url']).path:
            raise ValueError('The City page redirected away from the selected community.')
        urls=discover(raw.decode('utf-8-sig',errors='replace'),final,p['id'])
        if not urls:return {**result,'status':'not_posted','message':'No City-posted bylaws PDF was found on this community’s official page. The council may have a copy that is not posted there.'}
        for url in urls[:5]:
            try:
                sample,document_url=transport(url,1024)
                if not sample.lstrip().startswith(b'%PDF-'):raise ValueError('The link did not return a PDF.')
                result['documents'].append({'url':document_url,'status':'available'})
            except Exception as error:
                result['documents'].append({'url':url,'status':'unavailable','error':str(error)})
        available=sum(d['status']=='available' for d in result['documents'])
        result.update(status='available' if available==len(result['documents']) else 'partial' if available else 'unavailable',
            message='Open the City-posted copy below. Check the document for its adoption or revision date; the City page may not reflect later amendments.' if available else 'The City lists bylaws, but the document could not be opened during this check. Try again or use the official community page.')
    except Exception as error:
        result.update(status='unavailable',message='Could not check the City’s bylaws page. Try again or open the official community page.',error=str(error))
    return result
