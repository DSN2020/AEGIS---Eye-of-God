import argparse
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from app_bridge import ApplicationBridge
from ev_assistant.audit_account import add_account_argument, resolve_account


class AccountPrivacyTests(unittest.TestCase):
    def test_fresh_install_has_no_accounts_or_credentials(self):
        template = Path(__file__).resolve().parents[1] / 'config.example.json'
        config = json.loads(template.read_text(encoding='utf-8'))
        self.assertEqual(config['sweep']['account_profiles'], [])
        self.assertFalse(config.get('browser_profiles'))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'config.json').write_bytes(template.read_bytes())
            bridge = ApplicationBridge(root)
            with patch('app_bridge.load_passwords') as load, patch.object(bridge, 'running', return_value=False):
                settings = bridge.settings()
            self.assertEqual(settings['accounts'], [])
            self.assertEqual(settings['workerCount'], 1)
            load.assert_not_called()
            self.assertFalse((root / 'data' / 'account-secrets.dpapi').exists())
            with self.assertRaises(ValueError):
                bridge.validate_settings({'workerCount': 1, 'accounts': []})

    def test_developer_tools_require_explicit_account(self):
        parser = argparse.ArgumentParser()
        add_account_argument(parser)
        with patch('sys.stderr'), self.assertRaises(SystemExit):
            parser.parse_args([])
        with patch('ev_assistant.audit_account.load_passwords') as load:
            with self.assertRaises(ValueError):
                resolve_account(Path('.'), {'sweep': {'account_profiles': ['example']}}, 'missing')
            load.assert_not_called()

    def test_audit_uses_only_selected_local_account(self):
        config = {'sweep': {'account_profiles': ['example', 'second']},
                  'browser_profiles': {'second': 'custom-profile'}}
        with patch('ev_assistant.audit_account.load_passwords', return_value=['test-value']) as load:
            account, profile = resolve_account(Path('workspace'), config, 'SECOND')
        self.assertEqual(account['username'], 'second')
        self.assertEqual(profile, Path('workspace/data/custom-profile'))
        load.assert_called_once_with(Path('workspace/data'), 'second')
        with patch('ev_assistant.audit_account.load_passwords', return_value=[]):
            with self.assertRaises(ValueError):
                resolve_account(Path('.'), config, 'example')
