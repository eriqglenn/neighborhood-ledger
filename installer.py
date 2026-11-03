"""Per-user Windows setup. Bundled Python; no package downloads or administrator step."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import zipfile

PAYLOAD=Path(__file__).resolve().parent/'ledger-payload.zip'
MANIFEST=Path(__file__).resolve().parent/'payload-manifest.json'
VERSION='13.8 MLS (No AI)'

def installed_version(target):
    target=Path(target)
    if not (target/'NeighborhoodLedgerMLSNoAI.exe').is_file(): return None
    try: return json.loads((target/'ledger-install.json').read_text(encoding='utf-8'))['version']
    except (OSError,ValueError,KeyError): return None

def check_available(target,names):
    """Check every replacement before touching the existing installation."""
    if sys.platform!='win32': return
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    kernel.CreateFileW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    for name in names:
        item=(target/name).resolve()
        if target not in item.parents: raise ValueError('Invalid installation path')
        if not item.is_file(): continue
        handle=kernel.CreateFileW(str(item),0x40000000,0,None,3,0,None)
        if handle==ctypes.c_void_p(-1).value:
            error=ctypes.get_last_error()
            raise OSError(error,'Ledger cannot update while its files are in use. Open Ledger and choose Settings → Save and close Ledger, then try Update again. Your existing files have not been changed.',str(item))
        kernel.CloseHandle(handle)

def install(target,shortcuts=True):
    target=Path(target).resolve()
    if target.exists() and any(target.iterdir()) and not (target/'ledger-install.json').exists(): raise ValueError('Choose an empty folder or an existing Neighborhood Ledger MLS (No AI) installation.')
    expected=json.loads(MANIFEST.read_text(encoding='utf-8'))
    if hashlib.sha256(PAYLOAD.read_bytes()).hexdigest()!=expected['sha256']:raise ValueError('Installer payload verification failed')
    with tempfile.TemporaryDirectory(prefix='ledger-setup-') as temporary:
        staged=Path(temporary)
        with zipfile.ZipFile(PAYLOAD) as archive:
            for member in archive.infolist():
                resolved=(staged/member.filename).resolve()
                if staged not in resolved.parents or member.filename.startswith(('/','\\')):raise ValueError('Invalid installer path')
            archive.extractall(staged)
        exe=staged/'NeighborhoodLedgerMLSNoAI.exe'
        if not exe.exists():raise ValueError('Application executable is missing')
        check_available(target,[item.relative_to(staged) for item in staged.rglob('*') if item.is_file()])
        # Preserve the previous program files for an upgrade rollback. Never touch user records.
        if (target/'ledger-install.json').exists():
            old=json.loads((target/'ledger-install.json').read_text(encoding='utf-8'))
            import datetime
            backup=target.parent/('NeighborhoodLedgerMLSNoAI-program-backup-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
            for name in old.get('files',[]):
                item=(target/name).resolve()
                if target not in item.parents:raise ValueError('Invalid previous install manifest')
                if item.is_file():
                    dest=backup/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(item,dest)
        target.mkdir(parents=True,exist_ok=True)
        files=[]
        for item in staged.rglob('*'):
            if item.is_file():
                name=item.relative_to(staged);dest=target/name;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(item,dest);files.append(str(name))
        (target/'ledger-install.json').write_text(json.dumps({'version':VERSION,'files':files},indent=2),encoding='utf-8')
    if shortcuts:
        create_shortcuts(target)
    return target/'NeighborhoodLedgerMLSNoAI.exe'

def create_shortcuts(target):
        script="""$shell = New-Object -ComObject WScript.Shell
$locations = @([Environment]::GetFolderPath('Desktop'), (Join-Path ([Environment]::GetFolderPath('Programs')) 'Neighborhood Ledger MLS (No AI)'))
foreach ($directory in $locations) {
 New-Item -ItemType Directory -Path $directory -Force | Out-Null
 $link = $shell.CreateShortcut((Join-Path $directory 'Neighborhood Ledger MLS (No AI).lnk'))
 $link.TargetPath = $env:LEDGER_SETUP_EXE
 $link.WorkingDirectory = $env:LEDGER_SETUP_DIR
 $link.Description = 'Neighborhood Ledger MLS (No AI) application wizard'
 $link.Save()
}
"""
        env={**os.environ,'LEDGER_SETUP_EXE':str(target/'NeighborhoodLedgerMLSNoAI.exe'),'LEDGER_SETUP_DIR':str(target)}
        subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],env=env,check=True,creationflags=subprocess.CREATE_NO_WINDOW)

def launch(target):
    return subprocess.Popen([str(Path(target)/'NeighborhoodLedgerMLSNoAI.exe')],creationflags=subprocess.CREATE_NO_WINDOW)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--test-install');args=parser.parse_args()
    if args.test_install:
        install(args.test_install,shortcuts=False);return
    import tkinter as tk
    from tkinter import ttk,messagebox,filedialog
    window=tk.Tk();window.title('Neighborhood Ledger MLS (No AI) — Open or install');window.geometry('660x410');window.resizable(False,False)
    frame=ttk.Frame(window,padding=25);frame.pack(fill='both',expand=True)
    ttk.Label(frame,text='Neighborhood Ledger MLS (No AI)',font=('Segoe UI',22,'bold')).pack(anchor='w')
    ttk.Label(frame,text='Houston Special Minimum Lot Size applications',font=('Segoe UI',11)).pack(anchor='w',pady=(0,16))
    ttk.Label(frame,text='Install once, then open the desktop shortcut.\nPython is included. No account or AI service is needed.\nExisting office records are kept separately from program files.',wraplength=550).pack(anchor='w')
    destination=tk.StringVar(value=str(Path(os.environ['LOCALAPPDATA'])/'Programs'/'NeighborhoodLedgerMLSNoAI'))
    ttk.Entry(frame,textvariable=destination).pack(fill='x',pady=(20,8))
    status=tk.StringVar();ttk.Label(frame,textvariable=status,wraplength=590).pack(anchor='w')
    def open_app():
        try: launch(destination.get());window.destroy()
        except OSError as e: messagebox.showerror('Could not open Ledger',str(e))
    def refresh(*_):
        version=installed_version(destination.get())
        if version:
            status.set('Ledger '+version+' is already installed. Use Open to run it. You do not need to reinstall.')
            button.configure(text='Open Neighborhood Ledger MLS (No AI)',command=open_app,state='normal')
            update.configure(text='Update to '+VERSION if version!=VERSION else 'Repair installation',state='normal')
            shortcut.configure(state='normal')
        else:
            status.set('Install once. After that, use the Neighborhood Ledger MLS (No AI) desktop shortcut.')
            button.configure(text='Install',command=run,state='normal');update.configure(state='disabled');shortcut.configure(state='disabled')
    def run():
        button.configure(state='disabled');update.configure(state='disabled');status.set('Installingâ€¦');window.update()
        try:
            install(destination.get());refresh()
        except Exception as e:
            refresh();messagebox.showerror('Update could not finish',str(e))
    def repair_shortcuts():
        try: create_shortcuts(Path(destination.get()));status.set('Desktop and Start menu shortcuts are ready. Use Neighborhood Ledger MLS (No AI) to open the app.')
        except Exception as e: messagebox.showerror('Shortcut could not be created',str(e))
    buttons=ttk.Frame(frame);buttons.pack(fill='x',pady=14)
    ttk.Button(buttons,text='Choose folder',command=lambda:destination.set(filedialog.askdirectory() or destination.get())).pack(side='left')
    button=ttk.Button(buttons,text='Install',command=run);button.pack(side='right')
    secondary=ttk.Frame(frame);secondary.pack(fill='x')
    shortcut=ttk.Button(secondary,text='Restore desktop shortcut',command=repair_shortcuts);shortcut.pack(side='left')
    update=ttk.Button(secondary,text='Update',command=run);update.pack(side='right')
    destination.trace_add('write',refresh);refresh()
    window.mainloop()

if __name__=='__main__':main()
