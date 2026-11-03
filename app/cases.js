// City-reported status is kept separately from the officer's follow-up status.
const casePanel=document.createElement('section');casePanel.className='card pad';casePanel.id='caseLookupPanel';casePanel.style.marginBottom='18px';
casePanel.innerHTML=`<h3>Check an existing 311 case</h3><p>Enter the full Houston 311 case number to check the City’s public record.</p><form id="caseLookupForm" class="actions"><div class="field" style="flex:1;min-width:220px"><label for="caseLookupNumber">311 case number</label><input id="caseLookupNumber" maxlength="64" autocomplete="off" placeholder="Enter the complete case number" required></div><button class="btn primary" id="caseLookupButton" type="submit">Check status</button></form><div id="caseLookupResult" role="status" aria-live="polite" style="margin-top:18px"></div>`;
$('#issues .pagehead').after(casePanel);
let caseLookupBusy=false,caseLookupFound=null;
const normalizedCase=value=>String(value||'').trim().toUpperCase();
function caseSnapshotHtml(row){
 const snapshot=row.city311,attempt=row.city311Attempt;
 return `${snapshot?`<p class="meta"><b>City status: ${esc(snapshot.record.cityStatus)}</b><br>Last checked ${esc(friendlyDate(snapshot.checkedAt,true))} · <a class="source" target="_blank" rel="noopener" href="${esc(safeUrl(snapshot.record.url))}">City case details ↗</a></p>`:''}${attempt&&attempt.status!=='found'?`<p class="meta">Latest lookup: ${esc(friendlyDate(attempt.checkedAt,true))}. ${esc(attempt.message||'No current status retrieved.')}</p>`:''}`;
}
function is311Record(row){return /\b311\b/.test(row.agency||'')&&row.caseNo}
function matching311(number,record=null){
 const keys=new Set([number,record?.caseNumber,record?.alternateCaseNumber].filter(Boolean).map(normalizedCase));
 return [...state.issues,...state.office.records.filter(is311Record)].filter(r=>keys.has(normalizedCase(r.caseNo)));
}
async function lookupCase(number){
 if(caseLookupBusy||communitySwitching)return;
 number=normalizedCase(number);$('#caseLookupNumber').value=number;
 if(!/^[A-Z0-9][A-Z0-9-]{3,63}$/.test(number)||!/[0-9]/.test(number)){$('#caseLookupResult').textContent='Enter the complete case number using letters, numbers and hyphens.';return}
 caseLookupBusy=true;caseLookupFound=null;$('#caseLookupButton').disabled=true;$('#caseLookupResult').textContent='Checking Houston 311…';
 try{
  const result=await officeApi('/api/311/status',{caseNumber:number});if(communitySwitching)return;
  if(result.caseNumber!==number)throw Error('The lookup returned a different case number. Please retry.');
  const matches=matching311(number,result.record);
  for(const row of matches){row.city311Attempt={status:result.status,checkedAt:result.checkedAt,message:result.message||''};if(result.status==='found')row.city311=result}
  if(matches.length){await saveState('311 lookup saved');renderIssues();renderOffice()}
  const official=`<p><a class="source" href="${esc(safeUrl(result.sourceUrl))}" target="_blank" rel="noopener">Open Houston’s official case lookup ↗</a></p>`;
  if(result.status!=='found'){$('#caseLookupResult').innerHTML=`<p>${esc(result.message)}</p><p class="meta">Checked ${esc(friendlyDate(result.checkedAt,true))}</p>${official}`;return}
  caseLookupFound=result;const r=result.record;
  $('#caseLookupResult').innerHTML=`<h3>Case ${esc(r.caseNumber)}</h3><p><b>City status: ${esc(r.cityStatus)}</b></p><p>${esc(r.serviceType||'Service type not listed')}<br>${esc(r.address||'Address not listed')}</p>${r.alternateCaseNumber?`<p>Alternate number: ${esc(r.alternateCaseNumber)}</p>`:''}${r.createdAt?`<p>Opened: ${esc(r.createdAt)}</p>`:''}<p class="meta">Checked ${esc(friendlyDate(result.checkedAt,true))}</p><p><a class="btn" href="${esc(safeUrl(r.url))}" target="_blank" rel="noopener">Open City case details ↗</a></p>`;
 }catch(error){$('#caseLookupResult').textContent='Could not check the case: '+error.message}
 finally{caseLookupBusy=false;$('#caseLookupButton').disabled=false}
}
$('#caseLookupForm').onsubmit=e=>{e.preventDefault();lookupCase($('#caseLookupNumber').value)};
function openCaseLookup(number){showView('issues');casePanel.scrollIntoView({block:'start'});lookupCase(number)}
const issuesBefore311=renderIssues;renderIssues=function(){
 issuesBefore311();
 $$('[data-delete-issue]').forEach(button=>{
  const row=state.issues.find(r=>r.id===button.dataset.deleteIssue);if(!row?.caseNo)return;
  const check=document.createElement('button');check.className='btn small';check.textContent='Check 311 status';check.dataset.check311=row.id;check.onclick=()=>openCaseLookup(row.caseNo);button.before(check);
  button.closest('tr').children[4].insertAdjacentHTML('beforeend',caseSnapshotHtml(row));
 });
};
const officeBefore311=renderOffice;renderOffice=function(){
 officeBefore311();
 $$('[data-office-edit]').forEach(button=>{
  const row=state.office.records.find(r=>r.id===button.dataset.officeEdit);if(!row||!is311Record(row))return;
  const check=document.createElement('button');check.className='btn small';check.textContent='Check 311 status';check.dataset.officeCheck311=row.id;check.onclick=()=>openCaseLookup(row.caseNo);button.after(check);
  button.closest('article').insertAdjacentHTML('beforeend',caseSnapshotHtml(row));
 });
};
renderIssues();renderOffice();
