// Per-community defaults and per-draft overrides; registered HTML remains a snapshot.
const originalDocumentPalette={main:'#143F31',accent:'#D6A13D',text:'auto'};
function validColor(value){return typeof value==='string'&&/^#[0-9a-f]{6}$/i.test(value)}
function cleanPalette(value,fallback=originalDocumentPalette){return {main:validColor(value?.main)?value.main.toUpperCase():fallback.main,accent:validColor(value?.accent)?value.accent.toUpperCase():fallback.accent,text:validColor(value?.text)?value.text.toUpperCase():'auto'}}
function documentColorState(){
 const raw=state.documentColors;
 const overrides={};for(const kind of ['newsletter','proclamation','certificate','support'])if(raw?.overrides?.[kind]&&validColor(raw.overrides[kind].main)&&validColor(raw.overrides[kind].accent))overrides[kind]=cleanPalette(raw.overrides[kind]);
 state.documentColors={version:1,default:cleanPalette(raw?.default),overrides};return state.documentColors;
}
function paletteFor(kind){const colors=documentColorState();return colors.overrides[kind]||colors.default}
function colorLuminance(hex){const rgb=hex.slice(1).match(/../g).map(x=>parseInt(x,16)/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4);return rgb[0]*.2126+rgb[1]*.7152+rgb[2]*.0722}
function contrast(a,b){const x=colorLuminance(a),y=colorLuminance(b);return (Math.max(x,y)+.05)/(Math.min(x,y)+.05)}
function readableOnWhite(hex){let rgb=hex.slice(1).match(/../g).map(x=>parseInt(x,16));while(contrast(hex,'#FFFFFF')<4.5){rgb=rgb.map(x=>Math.floor(x*.9));hex='#'+rgb.map(x=>x.toString(16).padStart(2,'0')).join('')}return hex}
function paletteInk(p){const text=contrast(p.main,'#FFFFFF')>=contrast(p.main,'#000000')?'#FFFFFF':'#000000';const explicit=validColor(p.text)?p.text:null;return {...p,text:explicit||text,body:explicit||'#202830',heading:explicit||readableOnWhite(p.main),accentInk:explicit||readableOnWhite(p.accent),headerAccent:explicit||(contrast(p.main,p.accent)>=4.5?p.accent:text)}}
function newsletterColorCSS(p,root='#newsletterPreview'){const c=paletteInk(p);return `${root}{background:#FFFFFF;color:${c.body};print-color-adjust:exact;-webkit-print-color-adjust:exact}${root} .mast{background:${c.main};color:${c.text}}${root} .mast h2,${root} .mast p{color:${c.text}}${root} .mast small{color:${c.headerAccent}}${root} .newsbody h3{color:${c.heading};border-color:${c.accent}}${root} .newsbody a{color:${c.heading}}${root} .newsbody p,${root} .newsbody h4{color:${c.body}}`}
function ceremonialColorCSS(p,root='#ceremonialPreview'){const c=paletteInk(p);return `${root}{background:#FFFFFF;color:${c.body};print-color-adjust:exact;-webkit-print-color-adjust:exact}${root}:before{border-color:${c.accent}}${root}:after{border-color:${c.main}}${root} .docseal{border-color:${c.accent};outline-color:${c.main};color:${c.heading};background:#FFFFFF}${root} .dockicker,${root} .doctitle,${root} .whereas b,${root} .honoree,${root} .letterhead h3{color:${c.heading}}${root} .docsubtitle,${root} .certificatebody .presented,${root} .certificatebody p[style]{color:${c.accentInk}!important}${root} .honoree,${root} .letterhead{border-color:${c.accent}}${root} .docbody,${root} .letterbody,${root} .reason,${root} .signatureline{color:${c.body}}${root} .docfooter,${root} .letterhead p{color:${c.body}}`}
const documentPreviewStyles=document.createElement('style');documentPreviewStyles.id='documentColorStyles';document.head.append(documentPreviewStyles);
function applyDocumentColors(){documentPreviewStyles.textContent=newsletterColorCSS(paletteFor('newsletter'))+ceremonialColorCSS(paletteFor(ceremonialType))}

const colorSwatches=['#FFFFFF','#000000','#E7E6E6','#44546A','#4472C4','#ED7D31','#A5A5A5','#FFC000','#5B9BD5','#70AD47','#F2F2F2','#7F7F7F','#D0CECE','#D6DCE4','#D9E2F3','#FBE5D6','#EDEDED','#FFF2CC','#DDEBF7','#E2EFDA','#D9D9D9','#595959','#AEAAAA','#ADB9CA','#B4C6E7','#F8CBAD','#DBDBDB','#FFE699','#BDD7EE','#C6E0B4','#BFBFBF','#3F3F3F','#757171','#333F50','#2F5496','#C55A11','#7B7B7B','#BF9000','#2E75B6','#548235','#143F31','#17365D','#742C46','#563777','#343A40','#D6A13D','#CDAA76','#C7A5DB','#A3B8C8','#202830'];
const standardSwatches=['#C00000','#FF0000','#FFC000','#FFFF00','#92D050','#00B050','#00B0F0','#0070C0','#002060','#7030A0'];
function closeColorMenus(except){document.querySelectorAll('.document-color-controls details[open]').forEach(d=>{if(d!==except)d.open=false})}
function makeColorControls(id,kind){
 const box=document.createElement('section');box.className='document-color-controls';box.id=id;box.setAttribute('aria-label','Document colors');box.kind=kind;
 const swatches=items=>items.map(hex=>`<button type="button" class="color-swatch" data-swatch="${hex}" style="background:${hex}" title="${hex}" aria-label="${hex}" aria-pressed="false"></button>`).join('');
 box.innerHTML=`<div class="document-color-toolbar"><span class="document-color-label">Colors</span>${['main','accent','text'].map(key=>`<details class="color-picker" data-picker="${key}"><summary aria-label="${key[0].toUpperCase()+key.slice(1)} color"><span class="color-chip" aria-hidden="true"></span>${key[0].toUpperCase()+key.slice(1)}<span aria-hidden="true">▾</span></summary><div class="color-dropdown" role="group" aria-label="${key} color palette">${key==='text'?'<button type="button" class="color-auto" data-auto>Automatic text color</button>':''}<span class="color-section-label">Theme colors</span><div class="color-swatch-grid">${swatches(colorSwatches)}</div><span class="color-section-label">Standard colors</span><div class="color-swatch-grid">${swatches(standardSwatches)}</div><div class="color-custom-row"><label for="${id}-${key}">More colors</label><input type="color" id="${id}-${key}" data-color="${key}" aria-label="Custom ${key} color"><input type="text" data-hex="${key}" aria-label="${key} hex color" maxlength="7" spellcheck="false" placeholder="#17365D"><button type="button" data-apply="${key}">Apply</button></div><p class="document-color-error" role="status"></p></div></details>`).join('')}<details class="color-options"><summary aria-label="Color options" title="Color options">⋯</summary><div class="color-dropdown color-options-menu"><button type="button" data-color-action="default">Use neighborhood default</button><button type="button" data-color-action="save">Save as neighborhood default</button><button type="button" data-color-action="reset">Reset colors</button></div></details></div><span class="document-color-status" role="status"></span>`;
 box.querySelectorAll('details').forEach(d=>{
  d.querySelector('summary').addEventListener('click',()=>{if(!d.open)closeColorMenus(d)});
  d.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();d.open=false;d.querySelector('summary').focus()}});
 });
 box.querySelectorAll('[data-picker]').forEach(picker=>{
  const key=picker.dataset.picker;
  const choose=value=>{setDocumentPalette(kind(),{...paletteFor(kind()),[key]:value},box);picker.open=false;picker.querySelector('summary').focus()};
  picker.querySelectorAll('[data-swatch]').forEach(button=>button.onclick=()=>choose(button.dataset.swatch));
  picker.querySelector('[data-auto]')?.addEventListener('click',()=>choose('auto'));
  picker.querySelector('[data-color]').oninput=e=>{documentColorState().overrides[kind()]=cleanPalette({...paletteFor(kind()),[key]:e.target.value});applyDocumentColors();syncColorControls()};
  picker.querySelector('[data-color]').onchange=()=>saveDocumentColors(box,'Colors saved.');
  const hex=picker.querySelector('[data-hex]');
  const apply=()=>{if(!validColor(hex.value.trim())){hex.setAttribute('aria-invalid','true');picker.querySelector('.document-color-error').textContent='Enter a six-digit color, such as #17365D.';return}choose(hex.value.trim())};
  picker.querySelector('[data-apply]').onclick=apply;hex.onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();apply()}};
 });
 box.querySelector('[data-color-action="default"]').onclick=()=>{delete documentColorState().overrides[kind()];applyDocumentColors();syncColorControls();closeColorMenus();saveDocumentColors(box,'Using neighborhood colors.')};
 box.querySelector('[data-color-action="save"]').onclick=()=>{const current=paletteFor(kind()),colors=documentColorState();colors.default={...current};delete colors.overrides[kind()];applyDocumentColors();syncColorControls();closeColorMenus();saveDocumentColors(box,'Neighborhood colors saved.')};
 box.querySelector('[data-color-action="reset"]').onclick=()=>{setDocumentPalette(kind(),originalDocumentPalette,box,'Original colors restored.');closeColorMenus()};
 return box;
}
const newsletterColors=makeColorControls('newsletterColors',()=> 'newsletter'),ceremonialColors=makeColorControls('ceremonialColors',()=>ceremonialType);
$('#newsletterTitle').closest('.field').after(newsletterColors);$('#docTypeGrid').after(ceremonialColors);
document.addEventListener('click',e=>{if(!e.target.closest('.document-color-controls details'))closeColorMenus()});
function syncColorControls(){for(const box of [newsletterColors,ceremonialColors]){
 const kind=box.kind(),p=paletteFor(kind),custom=!!state.documentColors.overrides[kind];
 box.querySelectorAll('[data-picker]').forEach(picker=>{
  const key=picker.dataset.picker,value=p[key],display=validColor(value)?value:'#202830';
  picker.querySelector('.color-chip').style.background=display;
  picker.querySelector('summary').title=key[0].toUpperCase()+key.slice(1)+': '+(value==='auto'?'Automatic':value);
  picker.querySelector('[data-color]').value=display;
  const hex=picker.querySelector('[data-hex]');hex.value=validColor(value)?value:'';hex.removeAttribute('aria-invalid');
  picker.querySelector('.document-color-error').textContent='';
  picker.querySelectorAll('[data-swatch]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.swatch===value)));
  picker.querySelector('[data-auto]')?.setAttribute('aria-pressed',String(value==='auto'));
 });
 box.querySelector('[data-color-action="default"]').disabled=!custom;
}}

async function saveDocumentColors(box,message){
 // Capture pending newsletter text before saving a color change.
 state.newsletter.title=$('#newsletterTitle').value;state.newsletter.intro=$('#newsletterIntro').value;
 await saveState('');box.querySelector('.document-color-status').textContent=saveFailed?'Colors are shown but could not be saved. Export your pending work before reloading.':message;
}
function setDocumentPalette(kind,palette,box,message='Colors saved.'){
 documentColorState().overrides[kind]=cleanPalette(palette);applyDocumentColors();syncColorControls();saveDocumentColors(box,message);
}
const newsletterBeforeColors=renderNewsletter;renderNewsletter=function(){newsletterBeforeColors();applyDocumentColors()};
const ceremonialBeforeColors=renderCeremonial;renderCeremonial=function(){closeColorMenus();ceremonialBeforeColors();applyDocumentColors();syncColorControls();ceremonialColors.querySelector('.document-color-status').textContent=''};
// Use concrete CSS values in exports so colors work without Ledger or CSS variables.
const docHtmlBeforeColors=docHtmlFile;docHtmlFile=function(){const p=paletteFor(ceremonialType);return docHtmlBeforeColors().replace('</style>',ceremonialColorCSS(p,'.paper')+`.paper{border-color:${p.accent}}@media print{.paper{border-color:${p.accent}}}</style>`)};
function newsletterHtmlFile(){
 renderNewsletter();const p=paletteFor('newsletter');
 return `<!doctype html><html><head><meta charset="utf-8"><title>${esc(state.newsletter.title)}</title><style>body{margin:32px auto;max-width:800px;background:white;font-family:Georgia,serif;line-height:1.6}.mast{padding:28px 32px}.mast h2{font-size:32px;margin:8px 0}.mast small{font-family:Arial,sans-serif;font-weight:bold;letter-spacing:1px}.mast p{margin:0}.newsbody{padding:28px 32px}.newsbody h3{font-family:Arial,sans-serif;font-size:16px;text-transform:uppercase;border-bottom:2px solid;padding-bottom:6px}.newsbody h4{font-size:19px;margin-bottom:4px}.newsbody a{overflow-wrap:anywhere}${newsletterColorCSS(p,'.newsletterpaper')}@media print{body{margin:0;max-width:none}.newsletterpaper{box-shadow:none}}</style></head><body><article class="newsletterpaper">${$('#newsletterPreview').innerHTML}</article></body></html>`;
}
$('#downloadNewsletter').onclick=()=>download('neighborhood-newsletter.html',newsletterHtmlFile(),'text/html');
$('#newsletter .pagehead button[onclick]').removeAttribute('onclick');
const newsletterPrint=$$('#newsletter .pagehead button').find(b=>b.textContent.includes('Print'));newsletterPrint.onclick=()=>{const w=window.open('','_blank');if(!w)return toast('Allow pop-ups to print this newsletter');w.document.write(newsletterHtmlFile());w.document.close();setTimeout(()=>w.print(),350)};
applyDocumentColors();syncColorControls();
