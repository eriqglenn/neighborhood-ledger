import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec=importlib.util.spec_from_file_location('ledger_setup',Path(__file__).resolve().parents[1]/'installer.py')
setup=importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)

class InstallerTests(unittest.TestCase):
    def test_existing_install_is_detected_without_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'NeighborhoodLedgerMLSNoAI.exe').write_bytes(b'original')
            (p/'ledger-install.json').write_text('{"version":"12.2.0"}')
            self.assertEqual(setup.installed_version(p),'12.2.0')
            self.assertEqual((p/'NeighborhoodLedgerMLSNoAI.exe').read_bytes(),b'original')
            (p/'NeighborhoodLedgerMLSNoAI.exe').unlink()
            self.assertIsNone(setup.installed_version(p))

    def test_locked_file_prevents_any_upgrade_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);target=p/'app';target.mkdir()
            (target/'NeighborhoodLedgerMLSNoAI.exe').write_bytes(b'old-exe')
            original='{"version":"12.2.0","files":["NeighborhoodLedgerMLSNoAI.exe"]}'
            (target/'ledger-install.json').write_text(original)
            payload=p/'payload.zip'
            with zipfile.ZipFile(payload,'w') as z:
                z.writestr('NeighborhoodLedgerMLSNoAI.exe',b'new-exe')
            manifest=p/'manifest.json';manifest.write_text(json.dumps({'sha256':hashlib.sha256(payload.read_bytes()).hexdigest()}))
            with patch.object(setup,'PAYLOAD',payload),patch.object(setup,'MANIFEST',manifest),patch.object(setup,'check_available',side_effect=OSError('in use')):
                with self.assertRaises(OSError): setup.install(target,shortcuts=False)
            self.assertEqual((target/'NeighborhoodLedgerMLSNoAI.exe').read_bytes(),b'old-exe')
            self.assertEqual((target/'ledger-install.json').read_text(),original)

    @unittest.skipUnless(setup.sys.platform=='win32','Windows file locking')
    def test_real_windows_lock_is_reported_before_copy(self):
        import ctypes
        from ctypes import wintypes
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
        kernel.CreateFileW.restype=wintypes.HANDLE
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder).resolve();f=p/'NeighborhoodLedgerMLSNoAI.exe';f.write_bytes(b'old')
            handle=kernel.CreateFileW(str(f),0x80000000,1,None,3,0,None)
            self.assertNotEqual(handle,ctypes.c_void_p(-1).value)
            try:
                with self.assertRaisesRegex(OSError,'files are in use'): setup.check_available(p,[f.name])
            finally: kernel.CloseHandle(handle)
            setup.check_available(p,[f.name])

    def test_open_launches_executable_without_installing(self):
        with patch.object(setup.subprocess,'Popen') as launch,patch.object(setup,'install') as install:
            setup.launch(Path('C:/Ledger'))
            self.assertEqual(Path(launch.call_args.args[0][0]).name,'NeighborhoodLedgerMLSNoAI.exe')
            install.assert_not_called()
