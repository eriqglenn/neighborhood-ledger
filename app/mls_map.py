"""Applicant map using the MLS wizard's portrait frame, parcel labels and footer."""
import io,math,re,threading
from functools import lru_cache
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from shapely.geometry import shape,box,LineString,Point
from shapely.affinity import affine_transform,rotate
from shapely.ops import unary_union,linemerge
from mls_boundary import street_key
from mls_text import street_name,description as street_description

LOCK=threading.RLock()
FRAME=(22.25,162.25,567,607.5)
USE_LABELS={'SFR':'Single-family','MF':'Multifamily','COM':'Commercial',
            'VAC':'Vacant','EXC':'Excluded use','UNKNOWN':'Use unknown'}

def property_label(row):
    match=re.match(r'^\s*(\d+[A-Za-z]?(?:\s+1/2)?)',row.get('street',''))
    number=match[1] if match else 'Unaddressed'
    try:area=float(row.get('area'))
    except (ValueError,TypeError):area=float('nan')
    area_text=(f'{area:,.2f}'.rstrip('0').rstrip('.')+' sq ft') if math.isfinite(area) and area>0 else 'Area unknown'
    uses={lot.get('use','UNKNOWN') for lot in row.get('lots',[])} if row.get('lots') else {row.get('use','UNKNOWN')}
    if len(uses)==1:use=USE_LABELS.get(next(iter(uses)),'Use unknown')
    elif any(u not in USE_LABELS or u=='UNKNOWN' for u in uses):use='Use partly unknown'
    else:use='Mixed uses'
    return '\n'.join([number,area_text,use])

@lru_cache(maxsize=2048)
def label_layout(value,size):
    """Measure the entire property label, including the smaller detail lines."""
    lines=[];top=0;bottom=0;width=0
    for i,line in enumerate(plain(value).splitlines()):
        font='Helvetica-Bold' if i==0 else 'Helvetica'
        fs=size if i==0 else max(7.5,size*.75)
        ascent,descent=pdfmetrics.getAscentDescent(font,fs)
        baseline=top-ascent;bottom=baseline+descent
        lines.append((line,font,fs,baseline));top=bottom-2
        width=max(width,pdfmetrics.stringWidth(line,font,fs))
    middle=bottom/2
    return [(line,font,fs,y-middle) for line,font,fs,y in lines],width,bottom-middle,-middle

def plain(value):return str(value or '').replace('–','-').replace('—','-')
def angle(degrees):return (degrees+90)%180-90
def label_box(value,x,y,degrees,size):
    if '\n' in value:
        _,width,bottom,top=label_layout(value,size)
        return rotate(box(x-width/2-.3,y+bottom-.3,x+width/2+.3,y+top+.3),degrees,origin=(x,y))
    width=pdfmetrics.stringWidth(value,'Helvetica',size)
    return rotate(box(x-width/2-.2,y-size*.52-.2,x+width/2+.2,y+size*.52+.2),degrees,origin=(x,y))

def fit_address(value,parcel,occupied):
    """MLS-style fitting: keep each address wholly inside its own parcel."""
    anchor=parcel.centroid if '\n' in value and parcel.covers(parcel.centroid) else parcel.representative_point();parts=[parcel] if parcel.geom_type=='Polygon' else list(parcel.geoms)
    orientations=[0,90]
    for part in parts:
        coords=list(part.minimum_rotated_rectangle.exterior.coords)
        for a,b in zip(coords,coords[1:]):
            degrees=angle(math.degrees(math.atan2(b[1]-a[1],b[0]-a[0])))
            if not any(abs(angle(degrees-old))<.1 for old in orientations):orientations.append(degrees)
    candidates=[]
    for degrees in orientations:
        for part in parts:
            aligned=rotate(part,-degrees,origin=(0,0));x0,y0,x1,y1=aligned.bounds;center=aligned.representative_point()
            positions=[(center.x,center.y),(aligned.centroid.x,aligned.centroid.y)]
            positions += [(x0+(x1-x0)*u,y0+(y1-y0)*v) for u in (.2,.35,.5,.65,.8) for v in (.2,.35,.5,.65,.8)]
            a=math.radians(degrees)
            candidates.extend((x*math.cos(a)-y*math.sin(a),x*math.sin(a)+y*math.cos(a),degrees) for x,y in positions)
    inside=parcel.buffer(-.4)
    # Prefer upright property details, with a 7.5-point minimum for small print.
    groups=[[p for p in candidates if abs(p[2])<.1],[p for p in candidates if abs(p[2])>=.1]] if '\n' in value else [candidates]
    for group in groups:
        for half in range(24,17 if '\n' in value else 11,-1):
            size=half/2;choices=[]
            for x,y,degrees in group:
                rect=label_box(value,x,y,degrees,size)
                if inside.covers(rect) and not any(rect.intersection(other).area>.01 for other in occupied):
                    choices.append((math.hypot(x-anchor.x,y-anchor.y)+abs(angle(degrees))*.1,x,y,degrees,size,rect))
            if choices:return min(choices,key=lambda item:item[0])[1:]
    return None

def outline(c,g,color=.7,width=.45,fill=False,exterior_only=False):
    if g.is_empty:return
    if g.geom_type!='Polygon':
        for part in getattr(g,'geoms',[]):outline(c,part,color,width,fill,exterior_only)
        return
    path=c.beginPath()
    for ring in [g.exterior] if exterior_only else [g.exterior,*g.interiors]:
        coords=list(ring.coords);path.moveTo(*coords[0])
        for point in coords[1:]:path.lineTo(*point)
        path.close()
    c.setStrokeGray(color);c.setLineWidth(width);c.setFillGray(1)
    c.drawPath(path,stroke=1,fill=int(fill),fillMode=0)

def label(c,value,x,y,degrees,size):
    if '\n' in value:
        c.saveState();c.translate(x,y);c.rotate(degrees);c.setFillGray(0)
        for line,font,fs,baseline in label_layout(value,size)[0]:
            c.setFont(font,fs);c.drawCentredString(0,baseline,line)
        c.restoreState();return
    c.saveState();c.translate(x,y);c.rotate(degrees);c.setFillGray(0);c.setFont('Helvetica',size)
    c.drawCentredString(0,-size*.35,plain(value));c.restoreState()

def wrap(value,font,size,width):
    lines=[];line=''
    for word in plain(value).split():
        test=(line+' '+word).strip()
        if line and pdfmetrics.stringWidth(test,font,size)>width:lines.append(line);line=word
        else:line=test
    if line:lines.append(line)
    return lines

def aligned_boundary(selected,context,include_street):
    if not include_street:return selected
    closing=selected.buffer(45,join_style=2).buffer(-45,join_style=2).intersection(selected.convex_hull)
    result=selected.union(closing)
    if context:result=result.difference(unary_union(context))
    return result.union(selected)

def map_pdf(case):
    from mls_service import ensure_map_roads
    case=ensure_map_roads(case)
    with LOCK:return render(case)

def render(case):
    selected=[r for r in case.get('parcels',[]) if r.get('selected')]
    if not selected:raise ValueError('Select properties before downloading the application map.')
    d=case.get('details',{});raw=[shape(r['geometry']) for r in selected];union=unary_union(raw);origin=union.centroid
    sx=364000*math.cos(math.radians(origin.y));sy=364000
    matrix=[sx,0,0,sy,-origin.x*sx,-origin.y*sy]
    feet=lambda g:affine_transform(g,matrix)
    polys=[feet(g) for g in raw];selected_feet=unary_union(polys)
    # A tax account may appear in the original neighborhood search and the later
    # boundary scan. Draw its current geometry once.
    context={str(r.get('account') or r.get('id')):r for r in case.get('nearby',[])}
    context.update({str(r.get('account') or r.get('id')):r for r in case.get('parcels',[])})
    selected_ids={str(r.get('account') or r.get('id')) for r in selected}
    context_shapes=[feet(shape(r['geometry'])) for r in context.values()]
    blockers=[feet(shape(r['geometry'])) for key,r in context.items() if key not in selected_ids]
    boundary=aligned_boundary(selected_feet,blockers,d.get('blockfaces')=='2')
    roads={}
    for r in case.get('roads',[]):
        key=street_key(r.get('name'))
        for path in r.get('paths',[]):
            if len(path)>1:roads.setdefault(key,[]).append(feet(LineString([v[:2] for v in path])))
    from collections import Counter
    from mls_boundary import address_parts,infer
    counts=Counter(address_parts(r.get('street'))[1] for r in selected);counts.pop('',None)
    primary=counts.most_common(1)[0][0] if counts else street_key(d.get('street'))
    inferred=infer(selected,case.get('roads',[]),case.get('address'))['fields']
    names=list(dict.fromkeys(street_key(v) for v in [primary,d.get('fromStreet') or inferred.get('fromStreet'),d.get('toStreet') or inferred.get('toStreet')] if v))
    for r in selected:
        name=street_key(re.sub(r'^\s*\d+[A-Za-z]?(?:\s+1/2)?\s+','',r.get('street','')))
        if name in roads and name not in names:names.append(name)
    framing=[selected_feet]
    main=unary_union(roads.get(primary,[]))
    for name in names[1:3]:
        cross=unary_union(roads.get(name,[]));hits=main.intersection(cross)
        if not hits.is_empty:
            pts=[hits] if hits.geom_type=='Point' else [p for p in getattr(hits,'geoms',[]) if p.geom_type=='Point']
            if pts:framing.append(min(pts,key=lambda p:p.distance(selected_feet)))
    x0,y0,x1,y1=unary_union(framing).bounds;mx,my,mw,mh=FRAME
    scale=min((mw-100)/max(x1-x0,1),(mh-110)/max(y1-y0,1));cx=(x0+x1)/2;cy=(y0+y1)/2
    page=lambda g:affine_transform(g,[scale,0,0,scale,mx+mw/2-cx*scale,my+mh/2-cy*scale])
    view=box(mx+3,my+26,mx+mw-3,my+mh-3);page_polys=[page(g) for g in polys];page_selected=unary_union(page_polys)
    out=io.BytesIO();c=canvas.Canvas(out,pagesize=(612,792),pageCompression=1,invariant=1)
    c.setTitle('Special Minimum Lot Size - Application Boundary Map');c.setAuthor('Neighborhood Ledger MLS (No AI)')
    c.setStrokeGray(0);c.setLineWidth(2);c.rect(17.75,19.25,576,756,fill=0)
    c.saveState();clip=c.beginPath();clip.rect(*FRAME);c.clipPath(clip,stroke=0,fill=0)
    for g in context_shapes:outline(c,page(g))
    outline(c,page_selected,fill=True)
    for g in page_polys:outline(c,g)
    outline(c,page(boundary),color=0,width=1.65,exterior_only=True)
    occupied=[];placed=[];callouts=[]
    for r,g in zip(selected,page_polys):
        value=property_label(r)
        position=fit_address(value,g,occupied)
        if position:
            x,y,degrees,size,rect=position;label(c,value,x,y,degrees,size);occupied.append(rect);placed.append((value,rect))
        else:callouts.append((value,g))
    # Keep all three lines in a linked callout if a parcel cannot fit them.
    for value,g in callouts:
        choices=[];anchor=g.representative_point()
        for x in range(int(mx+25),int(mx+mw-25),12):
            for y in range(int(my+40),int(my+mh-20),12):
                rect=label_box(value,x,y,0,10)
                if view.covers(rect) and not rect.intersects(page_selected.buffer(3)) and not any(rect.intersects(other.buffer(2)) for other in occupied):
                    choices.append((math.hypot(x-anchor.x,y-anchor.y),x,y,rect))
        if not choices:raise ValueError('The map cannot fit every property label legibly. Adjust the boundary or selected properties before exporting.')
        _,x,y,rect=min(choices,key=lambda item:item[0]);c.setLineWidth(.5);c.setStrokeGray(.3);c.line(anchor.x,anchor.y,x,y);outline(c,rect,color=1,width=0,fill=True);label(c,value,x,y,0,10);occupied.append(rect);placed.append((value,rect))
    # Include neighboring streets visible in the frame, even when the applicant
    # has not yet filled cross streets. Never infer their placement from text.
    names+=sorted((name for name in roads if name not in names),key=lambda name:unary_union(roads[name]).distance(selected_feet))
    street_labels=set()
    for name in names:
        parts=roads.get(name,[])
        content=street_name(name,uppercase=True)
        if not parts:continue
        merged=unary_union(parts)
        if merged.geom_type=='MultiLineString':merged=linemerge(merged)
        lines=[merged] if merged.geom_type=='LineString' else list(getattr(merged,'geoms',[]))
        best=None
        for size in [18,16,14,12,10,8]:
            width=pdfmetrics.stringWidth(content,'Helvetica',size);choices=[]
            for raw_line in lines:
                visible=page(raw_line).intersection(view)
                segments=[visible] if visible.geom_type=='LineString' else list(getattr(visible,'geoms',[]))
                for line in segments:
                    if line.geom_type!='LineString' or line.length<width+6:continue
                    for i in range(25):
                        pos=width/2+3+i/24*(line.length-width-6);point=line.interpolate(pos)
                        a=line.interpolate(pos-width/2);b=line.interpolate(pos+width/2)
                        degrees=angle(math.degrees(math.atan2(b.y-a.y,b.x-a.x)));rect=label_box(content,point.x,point.y,degrees,size)
                        if view.covers(rect) and not rect.intersects(page_selected.buffer(.8)) and not any(rect.intersects(other.buffer(2)) for other in occupied):
                            choices.append((point.distance(page_selected.centroid)+point.distance(LineString([a,b]))*5,point.x,point.y,degrees,rect))
            if choices:best=(*min(choices,key=lambda item:item[0])[1:],size);break
        if best:
            x,y,degrees,rect,size=best;c.saveState();outline(c,rect,color=1,width=0,fill=True);c.restoreState();label(c,content,x,y,degrees,size);occupied.append(rect);street_labels.add(name)
    if primary not in street_labels:raise ValueError('The street name could not fit legibly on this map. Check the selected block and its street geometry before downloading.')
    c.restoreState();c.setStrokeGray(0);c.setLineWidth(.8);c.rect(*FRAME,fill=0)
    # Compact north symbol and scale, in the same corner as the MLS wizard.
    c.setFillGray(1);c.rect(466,164,119,23,stroke=0,fill=1)
    c.setFillGray(0);c.circle(480,174,6.5,stroke=0,fill=1)
    c.setFillGray(1);p=c.beginPath();p.moveTo(480,179.4);p.lineTo(475.5,174);p.lineTo(484.5,174);p.close();c.drawPath(p,stroke=0,fill=1)
    c.setFont('Helvetica-Bold',6);c.drawCentredString(480,169.5,'N')
    maximum=65/scale;power=10**math.floor(math.log10(maximum));length=max(n*power for n in [.1,.2,.5,1,2,5] if n*power<=maximum)
    for i in range(4):
        c.setFillGray(0 if i%2==0 else 1);c.setStrokeGray(0);c.setLineWidth(.4);c.rect(501+i*length*scale/4,169,length*scale/4,3.2,stroke=1,fill=1)
    c.setFillGray(0);c.setFont('Helvetica',6.5)
    for i in [0,2,4]:c.drawCentredString(501+i*length*scale/4,176,f'{i*length/4:g}')
    c.drawString(504+length*scale,169,'Feet')
    footer(c,case)
    c.showPage();c.save()
    return out.getvalue()

def footer(c,case):
    c.setStrokeGray(0);c.setLineWidth(1);c.rect(22.25,22.75,567,135,fill=0)
    c.setFillGray(0);c.setFont('Helvetica-Bold',16);c.drawString(27,139,'Special Minimum Lot Size')
    from collections import Counter
    from mls_boundary import address_parts
    names=Counter(address_parts(r.get('street'))[1] for r in case.get('parcels',[]) if r.get('selected'));names.pop('',None)
    fallback='Selected properties on '+street_name(names.most_common(1)[0][0]) if names else 'Application boundary'
    description=street_description(case) or fallback
    for size in [12,11,10,9]:
        lines=wrap(description,'Helvetica-Bold',size,404)
        if len(lines)<=4:break
    if len(lines)>4:raise ValueError('Shorten the boundary description to fit the MLS map footer.')
    c.setFont('Helvetica-Bold',size)
    for i,line in enumerate(lines):c.drawString(27,119-i*15,line)
    c.setFont('Helvetica',8);c.drawString(27,61,'Property labels: address / land area / land use.')
    c.drawString(27,49,'Applicant-prepared map - parcel boundaries are not a survey.')
    c.setLineWidth(1.5);c.rect(30,29.5,23,14,fill=0);c.setFont('Helvetica',9);c.drawString(57,33.5,'Proposed application boundary')
    c.setFont('Helvetica-Oblique',7)
    for y,value in [(147.5,'Source: HCAD / Harris County'),(138,'Retrieved: '+str(case.get('retrievedAt') or 'not recorded')[:10]),(128.5,'Reference: Applicant map')]:c.drawString(449,y,value)
    c.setFont('Helvetica',6.5)
    for i,line in enumerate(wrap('Reference only. Confirm property and legal lot boundaries against the recorded plat.', 'Helvetica',6.5,130)):c.drawString(449,111-i*8,line)
    if any('Excluded use' in property_label(r) for r in case.get('parcels',[]) if r.get('selected')):
        for i,line in enumerate(wrap('Excluded use: park, library, place of worship or school.', 'Helvetica',6.5,130)):c.drawString(449,80-i*8,line)
