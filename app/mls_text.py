"""Display street names without changing County records or lookup keys."""
import copy
import re

STREET_TYPES = {
 'ST':'Street','DR':'Drive','RD':'Road','AVE':'Avenue','AV':'Avenue',
 'BLVD':'Boulevard','LN':'Lane','CT':'Court','PL':'Place','CIR':'Circle',
 'PKWY':'Parkway','TER':'Terrace','TRL':'Trail','HWY':'Highway',
 'FWY':'Freeway','EXPY':'Expressway','TRCE':'Trace','BND':'Bend',
 'CV':'Cove','XING':'Crossing','PT':'Point','SQ':'Square','WAY':'Way',
}
DIRECTIONS={'N':'North','S':'South','E':'East','W':'West','NE':'Northeast',
 'NW':'Northwest','SE':'Southeast','SW':'Southwest'}

def title_words(value):
 value=str(value or '').strip()
 # Keep intentional internal capitalization in names such as McKinney.
 value=re.sub(r"[A-Za-z]+(?:['’][A-Za-z]+)?",lambda m:m[0].capitalize() if m[0].isupper() or m[0].islower() else m[0],value)
 return re.sub(r'\b(\d+)(St|Nd|Rd|Th)\b',lambda m:m[1]+m[2].lower(),value)

def street_name(value,uppercase=False):
 words=str(value or '').strip().split()
 if not words:return ''
 # Expand the street type at its suffix position, never Saint in St John Street.
 suffix=len(words)-1
 if words[-1].rstrip('.').upper() in DIRECTIONS:suffix-=1
 for i,word in enumerate(words):
  key=word.rstrip('.').upper()
  if i==suffix and i>0 and key in STREET_TYPES:words[i]=STREET_TYPES[key]
  elif (i==0 or i==len(words)-1) and len(words)>1 and key in DIRECTIONS:words[i]=DIRECTIONS[key]
 result=title_words(' '.join(words))
 return result.upper() if uppercase else result

def address(value):
 parts=str(value or '').split(',')
 if len(parts)==1:parts=re.split(r'\s+(?=Houston\s+(?:TX|Texas)\b)',parts[0],maxsplit=1,flags=re.I)
 # A unit designation is not part of the street suffix.
 unit=re.split(r'(\s+(?:APT\.?|UNIT|SUITE|STE\.?|#)\s*.*)$',parts[0],maxsplit=1,flags=re.I)
 parts[0]=street_name(unit[0])+(' '+title_words(unit[1]).strip() if len(unit)>1 else '')
 for i in range(1,len(parts)):
  parts[i]=re.sub(r'\bTx\b','TX',title_words(parts[i]))
 return ', '.join(p.strip() for p in parts)

def street_pattern(value):
 aliases={**STREET_TYPES,**DIRECTIONS}
 tokens=[]
 for word in re.findall(r"[\w'’]+",str(value or '')):
  full=aliases.get(word.upper(),word)
  variants={full,word,*[key for key,val in aliases.items() if val.upper()==full.upper()]}
  tokens.append('(?:'+'|'.join(re.escape(v) for v in sorted(variants,key=len,reverse=True))+')')
 return r'(?<!\w)'+r'\.?\s+'.join(tokens)+r'(?!\w)' if tokens else None

def street_text(value,case):
 d=case.get('details',{});value=str(value or '')
 names=sorted({str(d.get(k) or '') for k in ['street','fromStreet','toStreet']},key=len,reverse=True)
 for name in names:
  pattern=street_pattern(name)
  if pattern:value=re.sub(pattern,lambda m:street_name(name),value,flags=re.I)
 return value

def description(case):
 value=str(case.get('details',{}).get('description') or '')
 if value and value.upper()==value:value=value.lower()
 return street_text(value,case)

def document_case(case):
 result=copy.deepcopy(case);d=result.setdefault('details',{})
 d['description']=description(case)
 if result.get('title'):result['title']=street_text(result['title'],case)
 for key in ['street','fromStreet','toStreet']:d[key]=street_name(d.get(key))
 for row in result.get('parcels',[]):row['street']=address(row.get('street'))
 for key in ['applicant','coapplicant']:
  if result.get(key):result[key]['address']=address(result[key].get('address'))
 return result
