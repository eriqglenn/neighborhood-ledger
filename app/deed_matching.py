"""Rank index candidates without treating a similar subdivision name as a match."""
import re

NUMBERS={'ONE':'1','FIRST':'1','TWO':'2','SECOND':'2','THREE':'3','THIRD':'3','FOUR':'4','FOURTH':'4','FIVE':'5','FIFTH':'5','SIX':'6','SIXTH':'6','SEVEN':'7','SEVENTH':'7','EIGHT':'8','EIGHTH':'8','NINE':'9','NINTH':'9','TEN':'10','TENTH':'10'}
def part(v):return str(v or '').strip().upper().lstrip('0')
def subdivision(value):
    value=re.sub(r'[^A-Z0-9 ]',' ',str(value or '').upper())
    value=re.sub(r'\bSEC(?:TION|T)?\s+([A-Z]+|\d+)\b',' ',value)
    value=re.sub(r'\b(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH)\s+(?:SECTION|SEC)\b',' ',value)
    return ' '.join(value.split())
def section(value):
    m=re.search(r'\bSEC(?:TION|T)?\.?\s+([A-Z]+|\d+)\b',str(value or '').upper())
    return NUMBERS.get(m[1],part(m[1])) if m else ''
def lot_match(indexed,wanted):
    if part(indexed)==part(wanted):return True
    m=re.fullmatch(r'(\d+)\s*(?:-|THRU|THROUGH|TO)\s*(\d+)',str(indexed).strip(),re.I)
    return bool(m and str(wanted).isdigit() and int(m[1])<=int(wanted)<=int(m[2]))
def rank_record(record,prop):
    target=subdivision(prop.get('searchName') or prop.get('subdivision'))
    ranks={'lot':0,'section':1,'subdivision':2,'section-unknown':3,'other-section':4,'other-lot':5,'other-subdivision':6}
    choices=[]
    for legal in record.get('legalDescriptions') or [{}]:
        name=subdivision(legal.get('subdivision'))
        if name and name!=target:
            scope='other-subdivision';label='Different indexed subdivision: '+legal['subdivision']
        elif not name:
            scope='section-unknown';label='Subdivision is missing from the indexed legal description; inspect the document'
        else:
            sec=part(legal.get('section')) or section(legal.get('subdivision'))
            comment=str(legal.get('comment','')).strip().upper()
            comment_match=re.fullmatch(re.escape(target)+r'\s+(?:SEC(?:TION)?\s*)?(\d+)\s*(?:B(?:LK)?\s*(\w+))?',comment)
            if not sec and comment_match:sec=part(comment_match[1])
            block=part(legal.get('block')) or (part(comment_match[2]) if comment_match else '')
            lot=legal.get('lot','')
            if sec and prop.get('section') and sec!=part(prop['section']):
                scope='other-section';label='Same subdivision, different indexed section: '+sec
            elif (block and prop.get('block') and block!=part(prop['block'])) or (lot and prop.get('lot') and not lot_match(lot,prop['lot'])):
                scope='other-lot';label='Same subdivision, different indexed lot or block'
            elif lot and prop.get('lot') and lot_match(lot,prop['lot']) and block and prop.get('block') and block==part(prop['block']):
                scope='lot';label='Subdivision, lot and block match the index; document review still required'
            elif lot or block:
                scope='section-unknown';label='Subdivision matches; incomplete lot/block index needs review'
            elif sec and prop.get('section'):
                scope='section';label='Subdivision and section match the index; document review still required'
            else:
                scope='subdivision';label='Subdivision name matches; section and coverage need document review'
        choices.append({'scope':scope,'label':label,'rank':ranks[scope]})
    return min(choices,key=lambda r:r['rank'])
