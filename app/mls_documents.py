"""Printable applicant packet on the supplied City template; no signatures fabricated."""
import csv,io,json,math,zipfile
from pathlib import Path
import pymupdf as fitz
from shapely.geometry import shape,box,LineString
from mls_service import analysis,project_dir,clean,stamp
from mls_text import document_case,address,street_text

BLUE=(.10,.22,.36);GRAY=(.35,.39,.44)
def safe(value):return str(value or '').replace('\u2014','-').replace('\u2013','-')
def text(page,rect,value,size=11,color=BLUE,bold=False,align=0):
 value=safe(value);rect=fitz.Rect(rect)
 for fs in [size,size-1,size-2,size-3,6]:
  if fs<=0:continue
  shape_=page.new_shape();remaining=shape_.insert_textbox(rect,value,fontsize=fs,fontname='hebo' if bold else 'helv',color=color,align=align)
  if remaining>=0:shape_.commit();return
 raise ValueError('Some document text is too long for its space. Shorten the boundary description or applicant details.')
def field(page,name,rect,value,size=10):
 value=safe(value)
 w=fitz.Widget();w.field_name=name;w.field_type=fitz.PDF_WIDGET_TYPE_TEXT;w.rect=fitz.Rect(rect);w.field_value=value;w.text_font='Helv';w.text_fontsize=size;w.text_color=(0,0,0);w.fill_color=(1,1,1);w.border_width=0
 # Size to the actual single-line field instead of depending on viewer auto sizing.
 if value:w.text_fontsize=min(size,max(5,((w.rect.width-4)/max(fitz.get_text_length(value,fontsize=1),1))))
 page.add_widget(w)
def form(c):
 c=document_case(c)
 source=Path(__file__).parent/'mls-assets/application.pdf';template=fitz.open(source);doc=fitz.open();doc.insert_pdf(template,from_page=1,to_page=1);p=doc[0];d=c.get('details',{})
 field(p,'boundaryDescription',(40,190,570,217),d.get('description'),9)
 field(p,'preliminaryMeeting',(352,235,572,249),d.get('meetingDate'),9)
 # Preserve the original Yes/No/Unknown boxes and mark only the user's answer.
 for name,x in [('Yes',402),('No',435),('Unknown',472)]:
  if d.get('restrictions')==name:p.insert_text((x,258.8),'X',fontsize=9,color=(0,0,0))
 if any(a['kind']=='Deed restrictions' for a in c.get('attachments',[])):p.insert_text((338,274),'X',fontsize=9)
 field(p,'restrictionExplanation',(40,298,572,311),d.get('restrictionExplanation'),9)
 for prefix,data,offset in [('applicant',c.get('applicant',{}),0),('coapplicant',c.get('coapplicant',{}),150.6)]:
  for key,rect in [('name',(137,345,570,359)),('role',(384,367,566,381)),('phone',(120,389,264,403)),('email',(347,389,573,403)),('address',(82,412,572,426))]:
   field(p,prefix+'_'+key,(rect[0],rect[1]+offset,rect[2],rect[3]+offset),data.get(key),10)
 # Repeat the official support page as needed, retaining its wording and blank signatures.
 owners=[p for p in c.get('parcels',[]) if p.get('selected')]
 needed=max(1,math.ceil(len(owners)/4))
 for i in range(needed):doc.insert_pdf(template,from_page=min(6+i,8),to_page=min(6+i,8))
 for i in range(needed):
  page=doc[1+i];field(page,f'support_area_{i}',(222,150,572,164),d.get('description'),8)
  for j,owner in enumerate(owners[i*4:i*4+4]):
   offset=[0,121.5,242.7,363.7][j]
   field(page,f'owner_{i}_{j}',(258,273+offset,534,287+offset),owner.get('owner'),9)
   field(page,f'address_{i}_{j}',(109,299+offset,534,313+offset),owner.get('street'),10)
 # Staff fields and all signing dates remain untouched.
 return doc.tobytes(garbage=4,deflate=True)

def page_header(doc,title,subtitle=''):
 p=doc.new_page(width=612,height=792);text(p,(38,30,574,64),title,20,bold=True);text(p,(38,68,574,104),subtitle,10,color=GRAY);p.draw_line((38,110),(574,110),color=BLUE,width=1);return p
def map_pdf(c):
 from mls_map import map_pdf as render
 return render(c)

def submission(c):
 doc=fitz.open(stream=form(c),filetype='pdf')
 doc.insert_pdf(fitz.open(stream=map_pdf(c),filetype='pdf'))
 # Use a continuous packet page count while retaining the official form text.
 for i,page in enumerate(doc):
  if i<len(doc)-1:
   page.add_redact_annot((575,725,590,747),fill=(1,1,1));page.apply_redactions(images=0,graphics=0)
  page.insert_text((275,785),f'Page {i+1} of {len(doc)}',fontsize=8,color=(.3,.3,.3))
 return doc.tobytes(garbage=4,deflate=True)

def worksheet(c,a):
 c=document_case(c)
 doc=fitz.open();p=page_header(doc,'Property schedule & calculation','Preliminary applicant worksheet - Planning staff confirms eligibility and the final minimum.');y=126
 text(p,(38,y,574,y+52),f"{a['propertyCount']} properties / {a['lotCount']} listed lots. Single-family use: {a['singleFamilyPercent']}% of non-excluded lots.\nArea threshold: {a['threshold']}%. Proposed minimum: {a['minimum']:,.0f} sq ft." if a['minimum'] else 'Lot sizes are missing; no minimum can be calculated.',11);y+=60
 for i,row in enumerate([r for r in c.get('parcels',[]) if r.get('selected')],1):
  if y>656:p=page_header(doc,'Property schedule (continued)',c['title']);y=126
  value=f"{i}. {row.get('street','Address unavailable')} | HCAD {row['account']}\n{row.get('legalDescription','')}\n{row.get('area') or 'Unknown'} sq ft | {row.get('use','UNKNOWN')} | Tax year {row.get('taxYear','unknown')}"
  text(p,(38,y,574,y+74),value,10);y+=79
 p=page_header(doc,'Minimum lot size calculation',f"Largest to smallest; cumulative land area threshold {a['threshold']}%. Not a count of owners or lots.");y=126
 text(p,(38,y,574,y+20),'Address / lot                       Size (sq ft)           Area %           Cumulative %',10,bold=True);y+=26
 for row in a['table']:
  if y>710:p=page_header(doc,'Calculation (continued)',c['title']);y=126
  text(p,(38,y,310,y+31),address(row.get('address',''))+' / '+clean(row.get('label'),55),9)
  for x,val in [(315,f"{row['area']:,.2f}"),(415,f"{row['percent']:.2f}%"),(492,f"{row['cumulative']:.2f}%")]:text(p,(x,y,x+78,y+28),val,9)
  y+=34
 return doc.tobytes(garbage=4,deflate=True)
def signs(c):
 c=document_case(c)
 doc=fitz.open();p=doc.new_page(width=36*72,height=24*72);d=c.get('details',{});ready=bool(d.get('signLetterDate'))
 if not ready:text(p,(100,30,2492,100),'DRAFT - DO NOT POST UNTIL PLANNING STAFF SENDS SIGN INSTRUCTIONS',28,color=(.7,.15,.1),align=1)
 p.draw_rect((70,120,2522,1648),color=(0,0,0),width=4)
 text(p,(150,180,2442,380),'NOTICE OF\nSPECIAL MINIMUM LOT SIZE BLOCK APPLICATION',65,bold=True,align=1,color=(0,0,0))
 text(p,(180,450,2412,710),'The Planning and Development Department has received an application\nfor the establishment of a Special Minimum Lot Size Block\n(Section 42-197 of the Code of Ordinances) for',49,align=1,color=(0,0,0))
 text(p,(180,800,2412,1150),d.get('description') or '[Complete the boundary description]',65,bold=True,align=1,color=(0,0,0))
 text(p,(180,1300,2412,1535),'For information, contact the City of Houston Planning and Development\nDepartment at (832) 393-6600.',48,align=1,color=(0,0,0))
 return doc.tobytes(garbage=4,deflate=True)
def cover(c,a):
 c=document_case(c)
 doc=fitz.open();p=page_header(doc,'Your MLS application packet',c['title']);y=126
 lines=['Prepared '+stamp()[:10]+'. Keep the editable application with your records.','1. Complete the preliminary meeting with Planning staff.','2. Confirm the property schedule, deed answers and applicant details.','3. Collect the applicant signature and any support signatures.','4. Submit the application and supporting documents to Planning.','5. Post signs only after written instructions from Planning staff.',f"Sign plan: {a['signCount']} signs for {c.get('details',{}).get('blockfaces','1')} blockface(s), unless staff directs otherwise. Print 36 x 24 inches at actual size."]
 lines+=['TO COMPLETE: '+s for s in a['issues']]+['PLEASE CONFIRM: '+s for s in a['notes']]
 for line in lines:
  if y>680:p=page_header(doc,'Before you submit (continued)',c['title']);y=126
  text(p,(38,y,574,y+48),street_text(line,c),11);y+=53
 return doc.tobytes(garbage=4,deflate=True)
def packet(c,root):
 a=analysis(c);pieces={'01-Application-and-map.pdf':submission(c),'Map/Boundary-map.pdf':map_pdf(c),'Working files/Before-you-submit.pdf':cover(c,a),'Working files/Property-schedule-and-calculation.pdf':worksheet(c,a),'Signs/Notification-sign-36x24.pdf':signs(c),'Reference/City-application-instructions.pdf':(Path(__file__).parent/'mls-assets/application.pdf').read_bytes()}
 buffer=io.BytesIO()
 with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
  for name,raw in pieces.items():z.writestr(name,raw)
  z.writestr('Application-record.json',json.dumps(c,ensure_ascii=False,indent=2))
  z.writestr('Read-me.txt','The submission PDF is 01-Application-and-map.pdf: application information, needed support/signature sheets and an address-labeled map.\nThe form remains editable. Signatures and staff-only fields are blank.\nReference, Working files and Signs are separate preparation materials, not pages of the submission PDF.\nKeep supporting recordings or other attachments available separately.\nThe sign PDF is 36 x 24 inches. Print at actual size after City instructions.\nSource form: https://houstontx.gov/planning/docs_pdfs/MLS-MBL-Application2026/SMLS-Block-NewApp-0821.pdf\n')
  for i,a_ in enumerate(c.get('attachments',[]),1):
   path=project_dir(root)/c['id']/(a_['id']+a_['ext'])
   if path.is_file():z.write(path,f'Attachments/{i:02d}-{a_["kind"].replace(" ","-")}{a_["ext"]}')
 return buffer.getvalue()
