import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from ev_assistant import runtime


class RuntimeTests(unittest.TestCase):
    def test_source_and_user_data_are_distinct(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(runtime.user_root(), runtime.APP_ROOT)
        with tempfile.TemporaryDirectory() as folder:
            with patch.dict(os.environ, {'EOG_DATA_ROOT': folder}):
                self.assertEqual(runtime.user_root(), Path(folder).resolve())
                self.assertEqual(runtime.child_environment(folder)['EOG_DATA_ROOT'], str(Path(folder).resolve()))

    def test_bundle_uses_matching_browser_and_source_keeps_chrome(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            with patch.object(runtime, 'APP_ROOT', root), patch.dict(os.environ):
                self.assertEqual(runtime.browser_options(), {'channel':'chrome'})
                self.assertEqual(runtime.browser_options('msedge'), {'channel':'msedge'})
                (root/'runtime'/'browsers').mkdir(parents=True)
                self.assertEqual(runtime.browser_options(), {})
                self.assertEqual(os.environ['PLAYWRIGHT_BROWSERS_PATH'], str(root/'runtime'/'browsers'))

    def test_source_lock_is_preserved_and_user_locks_are_stable(self):
        self.assertEqual(runtime.supervisor_port(runtime.APP_ROOT), 47682)
        with tempfile.TemporaryDirectory() as folder:
            first = runtime.supervisor_port(Path(folder)/'one')
            self.assertEqual(first, runtime.supervisor_port(Path(folder)/'one'))
            self.assertNotEqual(first, runtime.supervisor_port(Path(folder)/'two'))
            self.assertTrue(49152 <= first <= 65535)

    def test_bridge_passes_data_location_to_supervisor(self):
        from app_bridge import ApplicationBridge
        with tempfile.TemporaryDirectory() as folder:
            bridge = ApplicationBridge(folder)
            with patch.object(bridge, 'running', return_value=False), \
                    patch.object(bridge, 'settings', return_value={}), \
                    patch.object(bridge, 'validate_settings'), patch('app_bridge.subprocess.Popen') as launch:
                bridge.start()
            args, kwargs = launch.call_args
            self.assertEqual(Path(args[0][-1]), runtime.APP_ROOT/'sweep_supervisor.py')
            self.assertEqual(kwargs['cwd'], runtime.APP_ROOT)
            self.assertEqual(kwargs['env']['EOG_DATA_ROOT'], str(Path(folder).resolve()))
