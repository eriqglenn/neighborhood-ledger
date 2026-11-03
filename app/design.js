// Build 13 presentation layer. Retains existing controls, handlers and stored records.
const iconPaths={today:'M3 10l9-7 9 7M5 9v12h14V9M9 21v-7h6v7',news:'M4 4h16v16H4zM8 8h8M8 12h8M8 16h5',calendar:'M4 6h16v15H4zM8 3v6M16 3v6M4 11h16',request:'M4 4h16v13H9l-5 4zM8 8h8M8 12h5',follow:'M9 6h12M9 12h12M9 18h12M2 5l2 2 3-4M2 11l2 2 3-4M2 17l2 2 3-4',meeting:'M4 21v-4a4 4 0 014-4h8a4 4 0 014 4v4M8 7a4 4 0 118 0 4 4 0 01-8 0',documents:'M6 3h8l4 4v14H6zM14 3v5h4M9 12h6M9 16h6',funding:'M12 2v20M17 6H9a3 3 0 000 6h6a3 3 0 010 6H6',plats:'M3 21V8l7-5v18M10 10l7-4v15M17 13l4-2v10M1 21h22M6 9v1M6 14v1M13 12v1M13 17v1',map:'M3 5l6-2 6 2 6-2v16l-6 2-6-2-6 2zM9 3v16M15 5v16',settings:'M4 7h16M4 17h16M8 4v6M16 14v6',help:'M9 8a3 3 0 116 0c0 2-3 2-3 5M12 17v.1M22 12a10 10 0 11-20 0 10 10 0 0120 0'};
const uiIcon=name=>`<svg class="ui-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${iconPaths[name]||iconPaths.today}"/></svg>`;
const viewNames={dashboard:'Today',intelligence:'News',calendar:'Calendar',issues:'Resident requests',office:'Follow-ups',meetings:'Meetings',newsletter:'Newsletter',ceremonial:'Letters & certificates',grants:'Funding',projects:'Plats & permits',neighborhood:'Neighborhood map',data:'Settings & backup'};
const navItems=[['Everyday work',[['dashboard','Today','today'],['intelligence','News & events','news'],['issues','Resident requests','request'],['office','Follow-ups','follow']]],['Office work',[['meetings','Meetings','meeting'],['newsletter','Documents','documents'],['grants','Funding','funding']]],['Neighborhood',[['projects','Plats & permits','plats'],['neighborhood','Neighborhood map','map']]]];
$('.brand').innerHTML=`<div class="brandmark">L</div><div><b>Neighborhood<br>Ledger</b><small>Community office</small></div>`;
$('.nav').innerHTML=navItems.map(([label,items])=>`<div class="nav-group">${label}</div>${items.map(([id,label,icon])=>`<button data-view="${id}">${uiIcon(icon)}<span>${label}</span></button>`).join('')}`).join('');
$$('.nav [data-view]').forEach(b=>b.onclick=()=>showView(b.dataset.view));
const bottom=document.createElement('div');bottom.className='side-bottom';bottom.innerHTML=`<button data-go="data">${uiIcon('settings')}Settings & backup</button><button id="deskHelp">${uiIcon('help')}Help & getting started</button><small>Greater Fifth Ward · SN 55</small>`;$('.sidebar').append(bottom);$('[data-go="data"]',bottom).onclick=()=>showView('data');$('#deskHelp').onclick=()=>openModal('ledgerHelp');
$('.place h1').textContent='Greater Fifth Ward';$('.place p').textContent='Super Neighborhood 55 · Houston';$('#menuBtn').textContent='Menu';$('#menuBtn').setAttribute('aria-label','Open navigation menu');
const oldHelp=$('.topactions button:not(#globalSync)');if(oldHelp)oldHelp.remove();
const textControl=document.createElement('label');textControl.className='text-control';textControl.innerHTML='Text size <select id="deskTextSize" aria-label="Text size"><option value="">Standard</option><option value="large">Large</option><option value="extra">Extra large</option><option value="double">200%</option></select>';$('.topactions').prepend(textControl);
function setTextSize(value){if(value)document.documentElement.dataset.textSize=value;else delete document.documentElement.dataset.textSize;try{localStorage.setItem('ledger.text-size',value)}catch{}setTimeout(()=>{map?.invalidateSize();projectMap?.invalidateSize()},100)}
try{$('#deskTextSize').value=localStorage.getItem('ledger.text-size')||'';setTextSize($('#deskTextSize').value)}catch{}
$('#deskTextSize').onchange=e=>setTextSize(e.target.value);
document.body.insertAdjacentHTML('afterbegin','<a class="skip-link" href="#ledgerContent">Skip to main content</a>');$('.content').id='ledgerContent';$('.content').tabIndex=-1;
$('#saveBadge').setAttribute('role','status');$('#toast').setAttribute('role','status');$('#toast').setAttribute('aria-live','polite');
function subnav(ids){for(const id of ids){const bar=document.createElement('nav');bar.className='subnav';bar.setAttribute('aria-label','Related tools');bar.innerHTML=ids.map(v=>`<button data-subview="${v}" ${v===id?'aria-current="page"':''}>${viewNames[v]}</button>`).join('');$('#'+id).prepend(bar);$$('button',bar).forEach(b=>b.onclick=()=>showView(b.dataset.subview))}}
subnav(['intelligence','calendar']);subnav(['newsletter','ceremonial']);

// Move the map and demographic reference off the daily task screen.
const mapView=document.createElement('section');mapView.id='neighborhood';mapView.className='view';mapView.innerHTML='<div class="pagehead"><div><h2>Neighborhood map</h2><p>Explore the official Greater Fifth Ward boundary and neighborhood reference information.</p></div></div>';$('.content').append(mapView);
const overviewGrid=$('#map').closest('.grid.two');mapView.append(overviewGrid);
const legacyHome=document.createElement('div');legacyHome.hidden=true;while($('#dashboard').firstChild)legacyHome.append($('#dashboard').firstChild);$('#dashboard').append(legacyHome);
$('#dashboard').insertAdjacentHTML('afterbegin',`<div class="today-heading"><div><div class="eyebrow" id="deskDate"></div><h2>Welcome to your neighborhood office.</h2><p>A clear place to plan your day and keep work moving.</p></div></div><div class="today-actions"><button class="today-action" data-start="request">${uiIcon('request')}<strong>Add a resident request</strong><span>Help a neighbor with a concern →</span></button><button class="today-action" data-start="follow">${uiIcon('follow')}<strong>Create a follow-up</strong><span>Set a next step and due date →</span></button><button class="today-action" data-start="meeting">${uiIcon('meeting')}<strong>Prepare a meeting</strong><span>Build your agenda and minutes →</span></button><button class="today-action" data-start="news">${uiIcon('news')}<strong>Read community news</strong><span>Events, programs and giveaways →</span></button></div><div class="today-grid"><div class="today-panel"><div class="panel-heading"><h3>Follow-ups due soon</h3><span class="count" id="deskDueCount">0</span></div><div id="deskTasks"></div><div class="today-list"><button class="btn" data-go="office">View all follow-ups</button></div></div><div class="today-panel"><div class="panel-heading"><h3>Coming up</h3><button class="btn ghost small" data-go="calendar">Calendar →</button></div><div id="deskUpcoming"></div></div></div><div class="quiet-status"><div><b id="deskUpdateTitle">Your public-source updates</b><p id="deskUpdateStatus">Use Check for updates to get the latest available records.</p><button class="btn ghost small" data-go="data">Source status & settings →</button></div><div id="deskRefresh"></div></div>`);
$('#deskRefresh').append($('#globalSync'));$('#globalSync').textContent='Check for updates';$('#deskTasks').append($('#taskList'));
$('#deskDate').textContent=new Date().toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric',year:'numeric'});
$$('[data-start]').forEach(b=>b.onclick=()=>{switch(b.dataset.start){case 'request':showView('issues');$('#issueLocation')?.focus();break;case 'follow':showView('office');editOffice();break;case 'meeting':showView('meetings');break;case 'news':showView('intelligence')}});
$$('[data-go]').forEach(b=>b.onclick=()=>showView(b.dataset.go));
function renderToday(){
 const due=state.office.records.filter(r=>!closed(r)&&r.due&&r.due<=new Date(Date.now()+7*86400000).toLocaleDateString('en-CA'));const tasks=state.tasks.filter(t=>!t.done);$('#deskDueCount').textContent=due.length+tasks.length;
 $('#deskTaskEmpty')?.remove();if(!due.length&&!tasks.length)$('#deskTasks').insertAdjacentHTML('beforeend','<div class="empty-state" id="deskTaskEmpty"><h4>No follow-ups due this week.</h4><p>Add a task and a due date to keep your next steps in one place.</p></div>');
 const events=state.events.filter(e=>/^\d{4}-\d{2}-\d{2}$/.test(e.date||'')&&e.date>=localDate()).sort((a,b)=>(a.date+(a.time||'')).localeCompare(b.date+(b.time||''))).slice(0,3);
 $('#deskUpcoming').innerHTML=events.length?`<div class="today-list">${events.map(e=>{const d=new Date(e.date+'T12:00:00');return `<div class="today-row"><div class="date-tile"><span>${d.toLocaleDateString('en-US',{month:'short'})}</span><b>${d.getDate()}</b></div><div><h4>${esc(e.title)}</h4><p>${esc(friendlyDate(e.date))}${e.time?' · '+esc(e.time):''}<br>${esc(e.location||'Location not recorded')}</p></div></div>`}).join('')}</div>`:'<div class="empty-state"><h4>Your calendar is ready.</h4><p>Add a confirmed meeting or event. Its date and location will appear here.</p><button class="btn" id="deskAddEvent">Add an event</button></div>';
 if($('#deskAddEvent'))$('#deskAddEvent').onclick=()=>{showView('calendar');openModal('eventModal')};
 const h=officeHealth,bad=h.sources.filter(s=>s.status!=='success'),news=state.intelligence.filter(i=>currentFinding(i)&&communityNews(i));
 $('#deskUpdateTitle').textContent=h.running?'Checking public sources…':news.length?`${news.length} community ${news.length===1?'update':'updates'} available`:'Your public-source updates';
 $('#deskUpdateStatus').textContent=h.running?`Currently checking ${sourceName(h.current)}.`:!h.sources.length?'Sources have not been checked yet.':bad.length?`${bad.length} ${bad.length===1?'source needs':'sources need'} attention. Open source status for details.`:'Source checks completed. Publication and event dates are shown with each record.';
}
const beforeToday=renderDashboard;renderDashboard=function(){beforeToday();renderToday();accessibleControls()};const beforeHealth=renderHealth;renderHealth=function(){beforeHealth();if(!$('.modalback.open'))renderToday()};

// A short description and a small number of meaningful actions on each screen.
const pageCopy={issues:['Resident requests','Prepare a 311 request, save the case number, and track a response.'],office:['Follow-ups','Keep track of the next step, the person responsible, and the due date.'],projects:['Plats & permits','Review official development activity verified for Greater Fifth Ward.'],meetings:['Meetings','Prepare your agenda, confirm the details, and record decisions.'],newsletter:['Newsletter','Choose reviewed updates and upcoming events, then preview your newsletter.'],ceremonial:['Letters & certificates','Prepare a letter, certificate, or community proclamation.'],grants:['Funding','Find opportunities and keep track of applications.'],intelligence:['Community news','Find events, giveaways, programs and updates worth sharing.'],calendar:['Calendar','Keep confirmed meetings, community events and deadlines in one place.'],data:['Settings & backup','Manage updates, your saved records, and source information.']};
for(const [id,[title,description]] of Object.entries(pageCopy)){const heading=$('#'+id+' .pagehead h2');if(heading)heading.textContent=title;const p=$('#'+id+' .pagehead p');if(p)p.textContent=description}
function disclose(node,title){if(!node)return;const d=document.createElement('details');d.className='disclosure';const summary=document.createElement('summary');summary.textContent=title;d.append(summary);node.before(d);d.append(node);return d}
// News: show the actual items first; put process details one click away.
const sourceDetails=disclose($('#scanSummary'),'About these news sources');$('#intelligence').append(sourceDetails);const newsNote=$('#intelligence>.meta');if(newsNote)sourceDetails.append(newsNote);
for(const [id,label] of [['newsTopics','Category'],['feedSearch','Search news'],['officeSearch','Search follow-ups'],['officeType','Record type']]){const input=$('#'+id);if(!input)continue;const field=document.createElement('div');field.className='filter-field'+(input.matches('input')?' search-field':'');const l=document.createElement('label');l.htmlFor=id;l.textContent=label;input.before(field);field.append(l,input)}
// Plats: list first, optional map, technical evidence always reachable.
disclose($('#projects .strictnote'),'How neighborhood locations are verified');disclose($('#projects>.grid.two'),'Sources, check results and file imports');
$('#scanPlats2').hidden=true;$('#scanPermits2').hidden=true;
const activityMapCard=$('#projectMap').closest('.card'),activityTableCard=$('#developmentTable').closest('.card');activityMapCard.before(activityTableCard);
const activityViews=document.createElement('nav');activityViews.className='subnav';activityViews.setAttribute('aria-label','Development view');activityViews.innerHTML='<button data-activity-view="records" aria-current="page">Records</button><button data-activity-view="map">Map</button>';activityTableCard.before(activityViews);activityMapCard.hidden=true;
$$('button',activityViews).forEach(b=>b.onclick=()=>{const useMap=b.dataset.activityView==='map';activityMapCard.hidden=!useMap;activityTableCard.hidden=useMap;$$('button',activityViews).forEach(x=>{if(x===b)x.setAttribute('aria-current','page');else x.removeAttribute('aria-current')});if(useMap)setTimeout(()=>{projectMap?.invalidateSize();if(projectMap&&currentBoundaryFeature)projectMap.fitBounds(L.geoJSON(currentBoundaryFeature).getBounds())},30)});
// Settings: routine controls first, data tools and destructive actions separate.
const advanced=disclose($('#data .datagrid'),'Advanced sources and neighborhood settings');advanced.append($('#data .connectorstrip'));advanced.append($('#sourceTable').closest('.card'));advanced.append($('#auditLog').closest('.card'));
const reset=$('#resetWorkspace');const resetWrap=document.createElement('div');resetWrap.innerHTML='<p>Clearing removes records from the active workspace. Ledger creates a safety backup before proceeding.</p>';$('#data').append(resetWrap);resetWrap.append(reset);disclose(resetWrap,'Clear this workspace');
disclose($('#officeSourceHealth'),'Source status, dates and coverage');
$('#officeStop').textContent='Save and close Ledger';$('#officeBrief').textContent='Weekly summary';$('#officeHandoff').textContent='Handoff notes';$('#officeNew').textContent='Add a follow-up';$('#runScan').textContent='Check for news';
$('#ofTitle').previousElementSibling.textContent='What needs to be done?';$('#ofOwner').previousElementSibling.textContent='Person or committee responsible';$('#ofNotes').previousElementSibling.textContent='Details and notes';$('#ofNext').previousElementSibling.textContent='Next step';$('#ofDue').previousElementSibling.textContent='Follow-up date';$('#ofUpdate').previousElementSibling.textContent='Progress since the last update';
$('#generate311').textContent='Prepare 311 request';$('#saveIssue').textContent='Save resident request';$('#generateEscalation').textContent='Prepare a follow-up message';$('#templateGrid').previousElementSibling.textContent='1. Choose the type of request';$('#issues .formgrid').insertAdjacentHTML('beforebegin','<h3 class="form-step" style="margin-top:28px">2. Record the details</h3>');$('#issues .actions:not(.pagehead .actions)')?.insertAdjacentHTML('beforebegin','<h3 class="form-step" style="margin-top:28px">3. Save or prepare a message</h3>');
$('#meetingTitle').closest('.card').insertAdjacentHTML('afterbegin','<h3 class="form-step">1. Meeting details and agenda</h3>');const agendaPane=document.createElement('div');$('#agendaPreview').before(agendaPane);agendaPane.innerHTML='<h3 class="form-step">2. Preview your agenda</h3>';agendaPane.append($('#agendaPreview'));
$('#newsletterTitle').closest('.card').insertAdjacentHTML('afterbegin','<h3 class="form-step">1. Choose what to include</h3>');const newsletterPane=document.createElement('div');$('#newsletterPreview').before(newsletterPane);newsletterPane.innerHTML='<h3 class="form-step">2. Preview your newsletter</h3>';newsletterPane.append($('#newsletterPreview'));

const priorShow=showView;showView=function(id){if(!$('#'+id))return;priorShow(id);const primary=id==='calendar'?'intelligence':id==='ceremonial'?'newsletter':id;$$('.nav button').forEach(b=>{const active=b.dataset.view===primary;b.classList.toggle('active',active);if(active)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current')});document.title=(viewNames[id]||'Neighborhood Ledger')+' · Neighborhood Ledger';$('#menuBtn').setAttribute('aria-expanded','false');const title=$('#'+id+' h2');if(title){title.tabIndex=-1;title.focus({preventScroll:true})}if(id==='neighborhood')setTimeout(()=>{map?.invalidateSize();if(map&&currentBoundaryFeature)map.fitBounds(L.geoJSON(currentBoundaryFeature).getBounds())},50)};
$('#menuBtn').setAttribute('aria-controls','sidebar');$('#menuBtn').onclick=()=>{const open=$('#sidebar').classList.toggle('open');$('#menuBtn').setAttribute('aria-expanded',String(open));if(open)$('.nav button').focus()};

// Name controls, make dialogs keyboard-friendly, and preserve source access.
function accessibleControls(){
 for(const input of $$('input,select,textarea')){if(input.type==='hidden'||input.hidden)continue;const label=input.closest('.field')?.querySelector('label');if(label&&input.id&&!label.htmlFor)label.htmlFor=input.id;if(!input.labels?.length&&!input.getAttribute('aria-label'))input.setAttribute('aria-label',input.placeholder||input.id.replace(/([A-Z])/g,' $1')||'Value')}
 for(const b of $$('.close')){b.textContent='Close';b.setAttribute('aria-label','Close dialog')}
 for(const item of $$('#taskList .task[data-id]')){item.tabIndex=0;item.setAttribute('role','checkbox');item.setAttribute('aria-checked',String(item.classList.contains('done')));item.onkeydown=e=>{if(e.key===' '||e.key==='Enter'){e.preventDefault();item.click()}}}
 for(const table of $$('table')){const parent=table.parentElement;if(parent){parent.classList.add('table-scroll');parent.tabIndex=0;parent.setAttribute('role','region');parent.setAttribute('aria-label',(parent.querySelector('h3')?.textContent||'Records')+' table — scroll horizontally for more columns')}}
}
accessibleControls();
const originalRenderAll=renderAll;renderAll=function(){originalRenderAll();accessibleControls()};
let previousDialog=null,returnFocus=null,lastOpener=null;
function requestDiscard(m){let prompt=$('.discard-prompt',m);if(!prompt){prompt=document.createElement('div');prompt.className='discard-prompt';prompt.setAttribute('role','alert');prompt.innerHTML='<p><b>You have unfinished changes.</b><br>Keep editing, or discard these changes and close the form.</p><button class="btn primary" data-keep>Keep editing</button><button class="btn danger" data-discard>Discard changes</button>';$('.modalhead',m).after(prompt);$('[data-keep]',prompt).onclick=()=>{prompt.remove();($('input',m)||$('button',m))?.focus()};$('[data-discard]',prompt).onclick=()=>{formDirty=false;prompt.remove();closeModal(m)}}prompt.scrollIntoView({block:'nearest'});$('[data-keep]',prompt).focus()}

document.addEventListener('click',e=>{if(!$('.modalback.open')&&e.target.closest('button'))lastOpener=e.target.closest('button');const m=$('.modalback.open');if(m&&formDirty&&(e.target===m||e.target.closest('.close,#officeCancel'))){e.preventDefault();e.stopImmediatePropagation();requestDiscard(m)}},true);
function updateDialogAccess(){const active=$('.modalback.open');if(active!==previousDialog){if(active){formDirty=false;returnFocus=lastOpener||document.activeElement;const box=$('.modal',active);box.setAttribute('role','dialog');box.setAttribute('aria-modal','true');const title=$('h3',box);if(title){if(!title.id)title.id=active.id+'Title';box.setAttribute('aria-labelledby',title.id)}$('.app').inert=true;setTimeout(()=>{($('input:not([hidden]),select,textarea',active)||$('button',active))?.focus()},40)}else{$('.app').inert=false;const target=returnFocus?.isConnected&&returnFocus.getClientRects().length?returnFocus:$('.nav button.active');target?.focus({preventScroll:true})}previousDialog=active}}
const dialogObserver=new MutationObserver(updateDialogAccess);$$('.modalback').forEach(m=>dialogObserver.observe(m,{attributes:true,attributeFilter:['class']}));
document.addEventListener('keydown',e=>{const m=$('.modalback.open');if(m&&e.key==='Escape'&&formDirty){e.preventDefault();e.stopImmediatePropagation();requestDiscard(m);return}if(m&&e.key==='Tab'){const elements=$$('button,a[href],input,select,textarea,summary,[tabindex="0"]',m).filter(x=>!x.disabled&&x.getClientRects().length);const first=elements[0],last=elements.at(-1);if(e.shiftKey&&(document.activeElement===first||!m.contains(document.activeElement))){e.preventDefault();last?.focus()}else if(!e.shiftKey&&(document.activeElement===last||!m.contains(document.activeElement))){e.preventDefault();first?.focus()}}else if(e.key==='Escape'&&$('#sidebar').classList.contains('open')){$('#sidebar').classList.remove('open');$('#menuBtn').focus()}},true);
toast=function(message){clearTimeout(toast.designTimer);$('#toast').textContent=message;$('#toast').classList.add('show');toast.designTimer=setTimeout(()=>$('#toast').classList.remove('show'),7000)};
showView('dashboard');
// Official development layers on both maps. Labels and outlines share the verified source.
const developmentLayers=new Map();
function mapLayers(target){
 if(!developmentLayers.has(target)){
  const groups={Plat:L.featureGroup().addTo(target),Permit:L.featureGroup().addTo(target)};
  L.control.layers(null,{'Plat outlines & markers':groups.Plat,'Permit addresses':groups.Permit},{collapsed:false}).addTo(target);
  developmentLayers.set(target,groups);
 }
 return developmentLayers.get(target);
}
function drawActivity(target,d){
 const groups=mapLayers(target),color=d.kind==='Plat'?'#a75d09':'#17678e',historical=d.kind==='Plat'&&d.onLatestAgenda===false;
 const label=`${esc(d.kind)}: ${esc(d.title)} · ${esc(d.caseNo)}${historical?' · Earlier agenda':''}`;
 if(d.mapVerification?.policy==='official-plat-outline-v1'&&d.mapGeometry){
  const outline=L.geoJSON(d.mapGeometry,{style:{color,weight:3,fillColor:color,fillOpacity:.18,dashArray:historical?'5 4':null}}).addTo(groups[d.kind]);
  outline.bindTooltip(label);outline.on('click',()=>openActivityDetail(d.id));
 }
 const marker=L.marker([Number(d.lat),Number(d.lng)],{title:`${d.kind}: ${d.title} (${d.caseNo})`,alt:`${d.kind}: ${d.title}`,icon:L.divIcon({className:'activity-pin '+(d.kind==='Plat'?'plat-pin':'permit-pin'),html:d.kind==='Plat'?'P':'B',iconSize:[32,32],iconAnchor:[16,16]}),keyboard:true}).addTo(groups[d.kind]);
 const nameMarker=()=>marker.getElement()?.setAttribute('aria-label',`${d.kind}: ${d.title} (${d.caseNo})`);marker.on('add',nameMarker);nameMarker();marker.bindTooltip(label,{direction:'top',offset:[0,-14]});marker.on('click',()=>openActivityDetail(d.id));
}
renderProjectMarkers=function(){
 if(!window.L||!projectMap||!map)return;
 projectMarkers.forEach(m=>projectMap.removeLayer(m));projectMarkers=[];
 for(const target of [map,projectMap]){const groups=mapLayers(target);groups.Plat.clearLayers();groups.Permit.clearLayers()}
 const all=developmentRows().filter(d=>['Plat','Permit'].includes(d.kind)&&activityHasCoordinates(d));
 const type=$('#activityTypeFilter').value,mapFilter=$('#activityMapFilter').value,q=$('#activitySearch').value.toLowerCase();
 const filtered=all.filter(d=>(type==='all'||d.kind===type)&&mapFilter!=='unmapped'&&`${d.title} ${d.caseNo} ${d.location} ${d.activity} ${d.source}`.toLowerCase().includes(q));
 for(const d of all)drawActivity(map,d);for(const d of filtered)drawActivity(projectMap,d);
 const missing=developmentRows().filter(d=>!activityHasCoordinates(d)).length;
 $('#activityMapNote').textContent=`${filtered.filter(d=>d.kind==='Plat').length} plats · ${filtered.filter(d=>d.kind==='Permit').length} permits mapped. ${missing} records still need a verified location. Select a marker for its source and details.`;
 $('#neighborhoodActivityStatus').textContent=`${all.filter(d=>d.kind==='Plat').length} plats · ${all.filter(d=>d.kind==='Permit').length} permits mapped. P = plat; B = building permit. ${missing} records need a verified location.`;
 $('#neighborhoodActivityList').innerHTML=all.length?all.map(d=>`<button class="btn" data-map-record="${esc(d.id)}">${esc(d.kind)}: ${esc(d.title)} · ${esc(d.caseNo)}</button>`).join(''):'<p>No verified development locations yet. Use Check plats & permits to retrieve current public records.</p>';
 $$('[data-map-record]').forEach(b=>b.onclick=()=>{const d=state.development.find(x=>x.id===b.dataset.mapRecord);if(d){map.setView([d.lat,d.lng],17);openActivityDetail(d.id)}});
};
const mapTools=document.createElement('div');mapTools.className='map-tools';mapTools.innerHTML='<p id="neighborhoodActivityStatus" role="status">Checking saved map locations…</p><div class="actions"><button class="btn primary" id="mapCheckSources">Check plats & permits</button><button class="btn" id="mapShowActivity">Show mapped activity</button><button class="btn" id="mapShowBoundary">Show whole neighborhood</button></div><details><summary>Mapped records — choose one for details</summary><div class="actions" id="neighborhoodActivityList"></div></details>';
$('#map').before(mapTools);$('#mapCheckSources').onclick=()=>startScan('development');
function fitActivities(target){const rows=developmentRows().filter(activityHasCoordinates);if(rows.length)target.fitBounds(L.latLngBounds(rows.map(d=>[d.lat,d.lng])),{padding:[40,40],maxZoom:16});else if(currentBoundaryFeature)target.fitBounds(L.geoJSON(currentBoundaryFeature).getBounds())}
$('#mapShowActivity').onclick=()=>fitActivities(map);$('#mapShowBoundary').onclick=()=>{if(currentBoundaryFeature)map.fitBounds(L.geoJSON(currentBoundaryFeature).getBounds())};
const mapEvidenceHtml=activityDetailHtml;activityDetailHtml=function(d){return mapEvidenceHtml(d)+`<div class="detailsection"><h3>Map location</h3><p>${esc(d.mapStatus||'Verified permit address, when available.')}</p>${d.mapVerification?.policy==='official-plat-outline-v1'?`<p>The outline is the City's GIS geometry for this exact case. The marker is a display point inside that outline. Agenda and GIS dates may differ; the agenda date remains authoritative for this listing.</p><a class="source" href="${esc(d.mapVerification.sourceUrl)}" target="_blank" rel="noopener">Official map feature and source fields ↗</a><details><summary>Map verification evidence</summary><pre style="white-space:pre-wrap;overflow-wrap:anywhere">${esc(JSON.stringify(d.mapVerification,null,2))}</pre></details>`:''}</div>`};
const detailMapButton=document.createElement('button');detailMapButton.className='btn';detailMapButton.textContent='Show on map';detailMapButton.id='showActivityOnMap';$('#locateActivity').before(detailMapButton);detailMapButton.onclick=()=>{const d=state.development.find(x=>x.id===activeActivityId);if(!d||!activityHasCoordinates(d))return;closeModal($('#activityDetailModal'));showView('neighborhood');setTimeout(()=>{map.invalidateSize();if(d.mapGeometry)map.fitBounds(L.geoJSON(d.mapGeometry).getBounds(),{maxZoom:18,padding:[60,60]});else map.setView([d.lat,d.lng],17)},100)};
const mappedDetail=openActivityDetail;openActivityDetail=function(id){mappedDetail(id);detailMapButton.hidden=!activityHasCoordinates(state.development.find(x=>x.id===id))};

// Give the map the full page width; keep the neighborhood profile available below.
const neighborhoodGrid=$('#neighborhood .grid.two');const profileCard=$$('.card',neighborhoodGrid).find(c=>!c.contains($('#map')));if(profileCard)disclose(profileCard,'Neighborhood profile and demographics');$('#mapCheckSources').parentElement.append($('#refreshBoundary'));$('#map').closest('.card').querySelector('.sectiontitle').hidden=true;

$('#map').nextElementSibling.innerHTML='<span><i class="legenddot" style="background:#a75d09"></i>P · Plat outline and marker</span><span><i class="legenddot" style="background:#17678e"></i>B · Verified permit address</span><span><i class="legenddot" style="background:#143f31"></i>Community reference point</span><span id="mapSourceNote">Official boundary verification</span>';

// News has one category selector and a text search.
$('#feedSearch').placeholder='Search news';$('#intelligence .toolbar').classList.add('news-search');
$('#runScan').textContent='Refresh';
$('#intelligence .pagehead p').textContent='Choose a category or search recent stories and upcoming events. Refresh checks the news sources.';
const newsStatus=document.createElement('div');newsStatus.className='news-status';newsStatus.innerHTML='<div><strong id="newsCheckTitle">Your community updates</strong><p id="newsCheckText" role="status" aria-live="polite">Checking the news sources for recent stories and upcoming events.</p></div><button class="btn ghost" id="newsSourceDetails">Source details</button>';
$('#intelligence .pagehead').after(newsStatus);
$('#newsSourceDetails').onclick=()=>{sourceDetails.open=true;sourceDetails.scrollIntoView({block:'start',behavior:'smooth'})};
const newsSourceList=document.createElement('div');newsSourceList.id='newsSourceList';sourceDetails.append(newsSourceList);
let newsRequest=false,newsQueued=false,newsRequestError='';
function activeNewsHealth(){const ids=officeHealth.newsSources;if(!ids)return officeHealth.sources.filter(s=>!['plats','permits'].includes(s.source));return ids.map(id=>officeHealth.sources.find(s=>s.source===id)||{source:id,status:'not_checked',count:0,coverage:'This source has not been checked on this computer.'})}

function renderNewsCheck(){
 const sources=activeNewsHealth();const busy=newsRequest||officeHealth.running;const bad=sources.filter(s=>!['success','partial'].includes(s.status));const dates=sources.map(s=>s.checkedAt).filter(Boolean).sort();
 $('#runScan').disabled=busy;$('#runScan').textContent=busy?'Checking…':'Refresh';
 $('#newsCheckTitle').textContent=busy?'Checking public sources…':newsRequestError?'Could not start a check':bad.length?'Some news sources are unavailable':sources.length?'News sources checked':'Your community updates';
 $('#newsCheckText').textContent=newsRequestError|| (busy?(newsQueued?'News will be checked after the current source check.':'Checking '+sourceName(officeHealth.current||'news')+' for news.'):(sources.length?`Last checked ${friendlyDate(dates.at(-1),true)}. ${bad.length?bad.length+' sources have older information, no public dated source, or a connection problem. Some news may be missing; open Source details.':'Choose All news to see every category from these sources.'}`:'Open News to check for updates.'));
 newsSourceList.innerHTML=`<p>Neighborhood Ledger ${esc(officeHealth.version||'')} · This computer checks each source independently. All news includes every category from these sources, not every article on the web.</p>`+sources.map(s=>`<p><b>${esc(sourceName(s.source))} · ${esc(statusName(s.status))}</b><br>${esc(friendlyDate(s.checkedAt,true))} · ${s.count} items${s.latestPublication?' · latest publication '+esc(friendlyDate(s.latestPublication)):''}<br>${esc(s.coverage)} ${esc(s.error||'')} ${esc((s.warnings||[]).join(' '))}<br><a class="source" href="/api/source-report?source=${encodeURIComponent(s.source)}&community=${community.id}" target="_blank">Source evidence ↗</a>${s.sourceUrl?` · <a class="source" href="${esc(safeUrl(s.sourceUrl))}" target="_blank" rel="noopener">Official source ↗</a>`:''}</p>`).join('');
}
async function checkNewsOnOpen(){
 if(newsRequest)return;
 newsRequest=true;newsRequestError='';renderNewsCheck();
 try{const r=await officeApi('/api/scan',{source:'news'});newsQueued=!r.started;await refreshOffice()}
 catch(e){newsRequestError='The news sources could not be checked. Use Refresh to try again; Source details shows the latest connection problems.';newsQueued=false}
 finally{newsRequest=false;renderNewsCheck()}
}
const newsHealth=renderHealth;renderHealth=function(){newsHealth();renderNewsCheck();if(newsQueued&&!officeHealth.running&&!newsRequest){newsQueued=false;checkNewsOnOpen()}};
const newsShow=showView;showView=function(id){newsShow(id);if(id==='intelligence'){const dates=activeNewsHealth().map(s=>Date.parse(s.checkedAt)||0);if(!dates.length||Math.min(...dates)<Date.now()-20*60000)checkNewsOnOpen()}};
$('#runScan').onclick=checkNewsOnOpen;
renderNewsCheck();renderFeed();
