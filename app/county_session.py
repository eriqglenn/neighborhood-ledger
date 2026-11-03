"""Keep County session cookies encrypted for the current Windows user (DPAPI)."""
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import sys
import time

class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_ubyte))]

def protect(content, decrypt=False):
    if sys.platform!='win32':raise OSError('Windows session protection is unavailable')
    buffer=ctypes.create_string_buffer(content)
    source=Blob(len(content),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_ubyte)));target=Blob()
    crypt=ctypes.WinDLL('crypt32',use_last_error=True);kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    function=crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    function.argtypes=[ctypes.POINTER(Blob),ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,wintypes.DWORD,ctypes.POINTER(Blob)]
    function.restype=wintypes.BOOL
    kernel.LocalFree.argtypes=[ctypes.c_void_p];kernel.LocalFree.restype=ctypes.c_void_p
    if not function(ctypes.byref(source),None,None,None,None,1,ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:return ctypes.string_at(target.data,target.size)
    finally:kernel.LocalFree(target.data)

def county_cookies(cookies):
    return [c for c in cookies if c.get('domain','').lstrip('.') in {'www.cclerk.hctx.net','cclerk.hctx.net'} and (c.get('expires',-1)<0 or c['expires']>time.time())]

def restore(context, root):
    path=Path(root)/'county-session.bin'
    if not path.exists():return
    try:
        cookies=county_cookies(json.loads(protect(path.read_bytes(),decrypt=True)))
        if cookies:context.add_cookies(cookies)
    except (OSError,ValueError,TypeError):
        # A revoked/expired/corrupt session simply requires County sign-in again.
        return

def save(context, root):
    cookies=county_cookies(context.cookies())
    root=Path(root);root.mkdir(parents=True,exist_ok=True)
    encrypted=protect(json.dumps(cookies).encode())
    temp=root/'county-session.bin.tmp';temp.write_bytes(encrypted);temp.replace(root/'county-session.bin')
