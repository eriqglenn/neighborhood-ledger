"""Desktop window with a private local server and durable office records."""
import argparse
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import threading
import urllib.request
from pathlib import Path

from paths import data_dir, APP_DIR, VERSION

TITLE = 'Neighborhood Ledger MLS (No AI)'

class CloseGuard:
    """Wait for the page's save queue before permitting a native close."""
    def __init__(self, window):
        self.window = window
        self.allowed = False
        self.pending = False

    def closing(self):
        if self.allowed:
            return True
        if not self.pending:
            self.pending = True
            threading.Thread(target=self.prepare, daemon=True).start()
        return False

    def prepare(self):
        try:
            self.window.evaluate_js('Promise.resolve(window.ledgerPrepareClose ? window.ledgerPrepareClose() : true)', self.finished)
        except Exception:
            logging.exception('Could not check pending saves')
            self.pending = False
            if self.window.create_confirmation_dialog(TITLE, 'The window is not responding. Close it? Unsaved edits may be lost.'):
                self.finished(True)

    def finished(self, saved):
        self.pending = False
        if saved is True:
            self.allowed = True
            self.window.destroy()

def open_window(url, root, smoke=False):
    import webview
    webview.settings['ALLOW_DOWNLOADS'] = True
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = True
    window = webview.create_window(TITLE, url, width=1280, height=850, min_size=(900, 650), background_color='#f6f7f3')
    window.expose(window.destroy)
    guard = CloseGuard(window)
    window.events.closing += guard.closing
    if smoke:
        def loaded():
            (root/'window-check.json').write_text(json.dumps({'windowLoaded':True,'renderer':'edgechromium','version':VERSION}),encoding='utf-8')
            threading.Timer(3,window.destroy).start()
        window.events.loaded += loaded
    webview.start(gui='edgechromium', private_mode=False, storage_path=str(root/'window-profile'))

def acquire_window():
    """Keep repeated shortcut clicks in the same desktop window."""
    if sys.platform != 'win32':
        return True, None
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.CreateMutexW.restype = ctypes.c_void_p
    handle = kernel.CreateMutexW(None, False, 'Local\\NeighborhoodLedgerMLSNoAIDesktop')
    if not handle:
        raise OSError('Could not create the desktop window lock')
    if ctypes.get_last_error() == 183:
        user = ctypes.windll.user32
        user.FindWindowW.restype = ctypes.c_void_p
        hwnd = user.FindWindowW(None, TITLE)
        if hwnd:
            user.ShowWindow(ctypes.c_void_p(hwnd), 9)
            user.SetForegroundWindow(ctypes.c_void_p(hwnd))
        kernel.CloseHandle(ctypes.c_void_p(handle))
        return False, None
    return True, handle

def configure_autostart(enabled):
    if sys.platform!='win32':
        if enabled: raise ValueError('Automatic sign-in startup is available on Windows only')
        return
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
        if enabled:
            if not getattr(sys,'frozen',False): raise ValueError('Install the packaged application before enabling sign-in startup')
            winreg.SetValueEx(key,'NeighborhoodLedgerMLSNoAI',0,winreg.REG_SZ,'"'+sys.executable+'" --background')
        else:
            try: winreg.DeleteValue(key,'NeighborhoodLedgerMLSNoAI')
            except FileNotFoundError: pass

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--background',action='store_true');parser.add_argument('--port',type=int,default=8898);parser.add_argument('--smoke-test',action='store_true');parser.add_argument('--window-smoke-test',action='store_true');parser.add_argument('--document-smoke-test',action='store_true')
    args=parser.parse_args(); root=data_dir()
    logging.basicConfig(handlers=[RotatingFileHandler(root/'application.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')],level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s')
    if sys.stdout is None: sys.stdout=open(root/'console.log','a',encoding='utf-8')
    if sys.stderr is None: sys.stderr=sys.stdout
    if args.document_smoke_test:
        from playwright.sync_api import sync_playwright
        import pymupdf
        from deed_documents import pdf_pages
        with pymupdf.open() as pdf:
            pdf.new_page().insert_text((72,72),'Ledger packaged runtime check')
            content=pdf.tobytes()
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            page=browser.new_page();page.set_content('<h1>Ledger document check</h1>')
            browser_ok=page.locator('h1').inner_text()=='Ledger document check';browser.close()
        (root/'document-check.json').write_text(json.dumps({'version':VERSION,'browser':browser_ok,'pdfPages':pdf_pages(content)}),encoding='utf-8');return
    if args.smoke_test:
        from storage import Store
        store=Store(root)
        (root/'startup-check.json').write_text(json.dumps({'version':VERSION,'database':str(store.path),'html':(APP_DIR/'neighborops.html').is_file(),'officeScript':(APP_DIR/'office.js').is_file()}),encoding='utf-8');return
    handle = None
    if not args.background:
        acquired, handle = acquire_window()
        if not acquired: return
    url='http://127.0.0.1:'+str(args.port)
    existing=False
    try:
        with urllib.request.urlopen(url+'/api/health',timeout=2) as response: health=json.load(response)
        existing=health.get('product')=='NeighborhoodLedgerMLSNoAIOffice'
    except (OSError,ValueError): pass
    if existing:
        try:
            if not args.background: open_window(url, root, args.window_smoke_test)
        finally:
            if handle: ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
        return
    from office_server import create_server
    try: server=create_server(args.port,root)
    except OSError as e:
        logging.exception('Startup failed')
        if sys.platform=='win32': ctypes.windll.user32.MessageBoxW(None,'Neighborhood Ledger could not start. The local port may be occupied. See '+str(root/'application.log'),'Neighborhood Ledger',0x10)
        return
    logging.info('Neighborhood Ledger %s started at %s',VERSION,url)
    worker=threading.Thread(target=server.serve_forever,daemon=True)
    worker.start()
    try:
        if args.background:
            worker.join()
        else:
            open_window(url,root,args.window_smoke_test)
            if handle:
                ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))
                handle=None
            if server.store.settings().get('autoStart'):
                # Only the explicitly enabled Windows background option keeps checks alive.
                worker.join()
    except Exception:
        logging.exception('Desktop window failed')
        if sys.platform=='win32':
            ctypes.windll.user32.MessageBoxW(None,'The desktop window could not open. Install Microsoft Edge WebView2 Runtime, then reopen Ledger. Details: '+str(root/'application.log'),TITLE,0x10)
    finally:
        server.deed_browser.close()
        server.monitor.stop.set();server.shutdown();server.server_close()
        if handle: ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(handle))

if __name__=='__main__': main()
