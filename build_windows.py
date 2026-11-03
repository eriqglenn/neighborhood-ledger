from pathlib import Path
import subprocess,zipfile,json,hashlib,sys
project=Path(__file__).resolve().parent;work=project/'build';work.mkdir(exist_ok=True);python=Path(sys.executable)
args=[str(python),'-m','PyInstaller','--noconfirm','--windowed','--onedir','--name','NeighborhoodLedgerMLSNoAI','--distpath',str(project/'portable'),'--workpath',str(work/'pyinstaller-app'),'--specpath',str(work),'--paths',str(project/'app')]
args+=['--collect-all','playwright','--collect-all','pymupdf']
for name in ['neighborops.html','office.js','design.css','design.js','deeds.js','communities.json','community.js','cases.js','document-colors.js','document-colors.css','mls.js','mls.css','requests.js','requests.css','news-dedup.js','mls-assets','plat_cache_2026-07-09.xlsx','vendor']:
    args+=['--add-data',str(project/'app'/name)+';'+(name if name in {'vendor','mls-assets'} else '.')]
args+=[str(project/'app/desktop.py')]
subprocess.run(args,check=True)
payload=project/'ledger-payload.zip'
with zipfile.ZipFile(payload,'w',zipfile.ZIP_DEFLATED) as z:
    for file in (project/'portable/NeighborhoodLedgerMLSNoAI').rglob('*'):
        if file.is_file():z.write(file,file.relative_to(project/'portable/NeighborhoodLedgerMLSNoAI'))
(project/'payload-manifest.json').write_text(json.dumps({'sha256':hashlib.sha256(payload.read_bytes()).hexdigest()}),encoding='utf-8')
subprocess.run([str(python),'-m','PyInstaller','--noconfirm','--windowed','--onefile','--name','Install-Neighborhood-Ledger-MLS-No-AI','--distpath',str(project),'--workpath',str(work/'pyinstaller-setup'),'--specpath',str(work),'--add-data',str(payload)+';.','--add-data',str(project/'payload-manifest.json')+';.',str(project/'installer.py')],check=True)
print('BUILT',project/'Install-Neighborhood-Ledger-MLS-No-AI.exe')
