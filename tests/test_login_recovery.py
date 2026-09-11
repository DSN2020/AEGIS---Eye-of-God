import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from isolated_supervisor import Slot


class LoginRecoveryTests(unittest.TestCase):
    def test_failed_login_waits_for_user_instead_of_relaunching(self):
        with tempfile.TemporaryDirectory() as folder:
            slot=Slot(0,{'sweep':{'account_profiles':['example']}},Path(folder))
            slot.galaxy=1
            slot.detail='LOGIN ACTION REQUIRED: Check the saved account'
            slot.process=Mock(returncode=1)
            slot.process.poll.return_value=1
            slot.observe_log=Mock()
            with patch.object(slot,'start') as start:
                slot.service([],499)
                slot.service([],499)
                self.assertTrue(slot.login_blocked)
                self.assertEqual(slot.state,'error')
                start.assert_not_called()
                slot.restart('Requested in EOG')
                self.assertFalse(slot.login_blocked)
                start.assert_called_once_with(1)
