import unittest
from unittest.mock import Mock, patch
from desktop import CloseGuard

class DesktopCloseTests(unittest.TestCase):
    def test_close_waits_for_save_result(self):
        window=Mock();guard=CloseGuard(window)
        with patch('desktop.threading.Thread') as thread:
            self.assertFalse(guard.closing())
            self.assertFalse(guard.closing())
            self.assertEqual(thread.call_count,1)
        window.destroy.assert_not_called()
        guard.finished(True)
        window.destroy.assert_called_once()
        self.assertTrue(guard.closing())

    def test_failed_save_or_cancel_keeps_window_open(self):
        for result in [False,None,'true',{'error':'Save failed'}]:
            window=Mock();guard=CloseGuard(window);guard.pending=True
            guard.finished(result)
            window.destroy.assert_not_called()
            self.assertFalse(guard.allowed)
            self.assertFalse(guard.pending)

    def test_unresponsive_page_does_not_discard_without_confirmation(self):
        window=Mock();window.evaluate_js.side_effect=RuntimeError('Disconnected')
        window.create_confirmation_dialog.return_value=False
        guard=CloseGuard(window)
        with self.assertLogs(level='ERROR'): guard.prepare()
        window.destroy.assert_not_called()
        self.assertFalse(guard.pending)
