"""Shared, auditable topic rules for Python collection and the existing JS UI."""
import re

POLICY={
 'version':'community-v1',
 'crime':r'\b(murders?|murdered|homicides?|stabbings?|stabbed|shootings?|shot dead|fatally shot|shot and killed|suspects?|arrested|charged with|robbery|robbed|assaulted|found dead)\b',
 'prevention':r'\b((crime|violence) prevention|gun safety|safety (workshop|training|class)|peace march)\b',
 'topics':[
  {'id':'giveaways','label':'Giveaways & food','priority':0,'pattern':r'\b(giveaways?|give[- ]?away|food (distribution|pantry|pantries|bank|drive|boxes?)|free (meals?|groceries|backpacks?|school supplies|diapers?|turkeys|produce)|backpack drive|supply drive|book swap)\b'},
  {'id':'events','label':'Events & workshops','priority':1,'pattern':r'\b(events?|festivals?|workshops?|block part(y|ies)|resource fair|health fair|job fair|career fair|concerts?|story ?time|family (day|night)|open house|lunch n.? learn|community clean[- ]?up|volunteer (day|opportunit))\b'},
  {'id':'resources','label':'Programs & assistance','priority':2,'pattern':r'\b(assistance|scholarships?|youth programs?|senior (programs?|services)|after[- ]school|summer camp|homebuyer|housing counseling|job training|workforce|free (classes|screenings|vaccinations|tax)|enrollment|registration|rent relief|utility assistance)\b'},
  {'id':'civic','label':'Neighborhood & civic updates','priority':3,'pattern':r'\b(public hearings?|town hall|council meeting|community meeting|neighborhood meeting|public comment|budget|grants?|street closure|road closure|boil water|flood warning|evacuation|cooling centers?|warming centers?|voter registration|park improvements?|affordable housing|development|plats?|permits?)\b'},
  {'id':'other','label':'Other news','priority':4,'pattern':None},
  {'id':'crime','label':'Crime reports','priority':5,'pattern':None}
 ]
}

def classify(title,summary='',kind=''):
    def crime(text):
        return bool(re.search(POLICY['crime'],text,re.I)) and not re.search(POLICY['prevention'],text,re.I)
    title=title or '';summary=summary or ''
    if crime(title): return 'crime'
    for text in (title,summary):
        if text==summary and crime(summary): return 'crime'
        for topic in POLICY['topics']:
            if topic['pattern'] and re.search(topic['pattern'],text,re.I):return topic['id']
    return 'events' if kind=='event' else 'civic' if kind in {'development','grant'} else 'other'

def describe(title,summary='',kind=''):
    ident=classify(title,summary,kind)
    topic=next(t for t in POLICY['topics'] if t['id']==ident)
    return {'newsTopic':ident,'newsPriority':topic['priority'],'newsPolicy':POLICY['version']}
