import asyncio
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from ev_assistant.__main__ import Reader
from ev_assistant.vision import OCR, TextLine, UncertainScreen, popup_kind, map_header_readable
from isolated_supervisor import (Slot, atomic_json, galaxy_done, prepare_jobs,
                                 read_json, pending_galaxies)


def line(text, x=150, y=300, confidence=.99):
    return TextLine(text, confidence, x, y)


class PopupTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_session_can_finish_loading_after_90_seconds(self):
        reader = Reader.__new__(Reader)
        reader.check_stop = Mock()
        reader.config = {'_shared_browser_endpoint': 'fixture'}
        reader.observe = AsyncMock(return_value=([line('Planets Fleet Alliance')], b''))
        with patch('ev_assistant.login.monotonic', side_effect=[0, 100]), \
                patch('ev_assistant.login.click_named', new=AsyncMock(return_value=False)), \
                patch('ev_assistant.login.login_fields', new=AsyncMock(return_value=None)):
            await reader.login_and_enter(Mock(), {'username': 'test'})
        reader.observe.assert_awaited_once()

    async def test_invalid_username_or_password_tries_second_supplied_password(self):
        reader = Reader.__new__(Reader)
        reader.check_stop = Mock()
        reader.observe = AsyncMock(side_effect=[
            ([line('Invalid username or password.')], b''),
            ([line('Planets Fleet Alliance')], b'')])
        fields = (Mock(), Mock())
        async def click(page, pattern):
            return pattern == r'ok|close|try again'
        with patch('ev_assistant.login.click_named', new=click), \
                patch('ev_assistant.login.login_fields', new=AsyncMock(side_effect=[fields,None,fields,None])), \
                patch('ev_assistant.login.submit_login', new=AsyncMock()) as submit, \
                patch('ev_assistant.login.asyncio.sleep', new=AsyncMock()):
            await reader.login_and_enter(Mock(), {'username':'test','passwords':['first','second']})
        self.assertEqual([c.args[3] for c in submit.await_args_list], ['first','second'])

    async def test_expired_session_does_not_submit_an_empty_password(self):
        reader = Reader.__new__(Reader)
        reader.check_stop = Mock()
        with patch('ev_assistant.login.click_named', new=AsyncMock(return_value=False)), \
                patch('ev_assistant.login.login_fields', new=AsyncMock(return_value=(Mock(),Mock()))), \
                patch('ev_assistant.login.submit_login', new=AsyncMock()) as submit:
            with self.assertRaisesRegex(UncertainScreen, 'Save this account'):
                await reader.login_and_enter(Mock(), {'username':'test'})
        submit.assert_not_awaited()

    async def test_required_fields_dialog_is_dismissed_before_entering_game(self):
        reader = Reader.__new__(Reader)
        reader.check_stop = Mock()
        reader.observe = AsyncMock(side_effect=[
            ([line('All fields are required.'),line('OK',x=210,y=540)], b''),
            ([line('Planets Fleet Alliance')], b'')])
        page = Mock()
        page.mouse.click = AsyncMock()
        with patch('ev_assistant.login.click_named', new=AsyncMock(return_value=False)), \
                patch('ev_assistant.login.login_fields', new=AsyncMock(return_value=None)), \
                patch('ev_assistant.login.asyncio.sleep', new=AsyncMock()):
            await reader.login_and_enter(page, {'username':'test'})
        page.mouse.click.assert_awaited_once_with(210,540)

    def test_fixed_ui_ocr_does_not_auto_rotate_coordinates(self):
        ocr = OCR.__new__(OCR)
        ocr.engine = Mock(return_value=([], None))
        self.assertEqual(ocr.read(b'frame'), [])
        ocr.engine.assert_called_once_with(b'frame', use_cls=False)
    def test_full_width_label_punctuation_preserves_player_name(self):
        name = '\u2463\u5e7b\u5149asd'
        lines = [line('Coordinates\uff1a[3:234:15]', y=277),
                 line('Player\uff1a' + name, y=300)]
        self.assertEqual(Reader.popup_details(lines, 3, 234), ((3, 234, 15), name))
        self.assertEqual(popup_kind(lines), 'detail')

    def test_compacted_pirate_title(self):
        self.assertEqual(popup_kind([line('HostilePirates', y=360)]), 'npc')

    def test_header_spacing_does_not_reject_map(self):
        lines = [line(text, y=57) for text in ('Galaxy', 'SolarSystem', 'Planet')]
        lines += [line('Bookmark', y=84)]
        self.assertTrue(map_header_readable(lines))

    def test_split_coordinates_confirm_owner(self):
        lines = [line('Coordinates:[', 120, 277), line('[3:69:9]', 220, 279),
                 line('Player: bot_3_69_9', 150, 300)]
        self.assertEqual(Reader.popup_details(lines, 3, 69), ((3, 69, 9), 'bot_3_69_9'))

    def test_missing_owner_cannot_count_as_confirmed(self):
        self.assertIsNone(Reader.popup_details([line('Coordinates:[3:69:9]')], 3, 69))

    async def test_dismiss_verifies_overlay_gone_without_clicking_ok(self):
        reader = Reader.__new__(Reader)
        reader.observe = AsyncMock(side_effect=[([line('HostilePirates')], b''), ([], b'')])
        page = Mock()
        page.mouse.click = AsyncMock()
        with patch('ev_assistant.__main__.asyncio.sleep', new=AsyncMock()):
            await reader.dismiss_popup(page)
        self.assertEqual(page.mouse.click.await_count, 2)
        for call in page.mouse.click.call_args_list:
            self.assertEqual(call.args, (235, 190))

    async def test_candidate_retry_does_not_repeat_previously_confirmed_candidate(self):
        reader = Reader.__new__(Reader)
        reader.map_snapshot = None
        reader.config = {'universe': 'test'}
        lines = [line(text, y=57) for text in ('Galaxy', 'SolarSystem', 'Planet', 'Bookmark')]
        lines.extend([line('Alice', y=400), line('Bob', y=600)])
        reader.observe = AsyncMock(side_effect=[(lines, b''), ([], b'')])
        reader.open_candidate = AsyncMock(side_effect=[
            ((1, 1, 1), 'Alice'), UncertainScreen('transition'), ((1, 1, 2), 'Bob')])
        store = Mock()
        seen = set()
        await reader.scan_map_view(Mock(), 1, 1, store, Path('.'), seen)
        self.assertEqual([call.args[1].text for call in reader.open_candidate.call_args_list],
                         ['Alice', 'Bob', 'Bob'])
        self.assertEqual(seen, {(1, 1, 1), (1, 1, 2)})
        self.assertEqual(store.record_sighting.call_count, 2)


class SupervisorTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform == 'win32', 'Windows DPAPI only')
    def test_password_store_roundtrip_is_encrypted(self):
        from ev_assistant.credentials import save_passwords, load_passwords
        with tempfile.TemporaryDirectory() as directory:
            marker = 'unit-test-value-unique-527819'
            save_passwords(directory, 'Test', [marker])
            encrypted = (Path(directory) / 'account-secrets.dpapi').read_bytes()
            self.assertNotIn(marker.encode(), encrypted)
            self.assertEqual(load_passwords(directory, 'test'), [marker])

    def test_unvisited_galaxies_precede_unresolved_holes(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            atomic_json(data / 'sweep-progress.json', {'1': 499, '2': 499, '5': 4})
            atomic_json(data / 'sweep-retries.json', {'systems': ['1:363', '2:493']})
            prepare_jobs(data, [1, 2, 5, 6])
            self.assertEqual(pending_galaxies(data, [1, 2, 5, 6], 499), [5, 6, 1, 2])

    def test_successful_pass_with_holes_yields_to_next_galaxy(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            atomic_json(data / 'galaxies/2/coverage.json',
                        {'progress': {'2': 499}, 'retry_holes': ['2:493']})
            slot = Slot(0, {'sweep': {'account_profiles': ['one']}}, data)
            slot.galaxy = 2
            slot.process = Mock(returncode=0)
            slot.process.poll.return_value = 0
            slot.observe_log = Mock()
            slot.close = Mock(side_effect=lambda: setattr(slot, 'process', None))
            slot.start = Mock()
            slot.next_launch = 0
            pending = [5, 6]
            slot.service(pending, 499)
            slot.start.assert_called_once_with(5)
            self.assertEqual(pending, [6, 2])
            self.assertFalse(galaxy_done(data, 2, 499))

    def test_checkpoint_read_retries_windows_sharing_violation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'coverage.json'
            value = {'progress': {'4': 366}, 'retry_holes': ['4:301']}
            with patch.object(Path, 'read_text', side_effect=[PermissionError(), json.dumps(value)]), \
                    patch('isolated_supervisor.time.sleep'):
                self.assertEqual(read_json(path, {}), value)

    def test_persistent_read_lock_keeps_last_checkpoint_and_holes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'coverage.json'
            value = {'progress': {'4': 499}, 'retry_holes': ['4:301']}
            path.write_text(json.dumps(value))
            self.assertEqual(read_json(path, {}), value)
            with patch.object(Path, 'read_text', side_effect=PermissionError()), \
                    patch('isolated_supervisor.time.sleep'):
                self.assertEqual(read_json(path, {}), value)

    def test_migration_preserves_holes_and_never_claims_complete(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            atomic_json(data / 'sweep-progress.json', {'1': 499, '2': 250})
            atomic_json(data / 'sweep-retries.json', {'systems': ['1:137']})
            prepare_jobs(data, [1, 2])
            self.assertFalse(galaxy_done(data, 1, 499))
            atomic_json(data / 'galaxies/1/coverage.json',
                        {'progress': {'1': 499}, 'retry_holes': []})
            prepare_jobs(data, [1, 2])
            self.assertTrue(galaxy_done(data, 1, 499))
            self.assertFalse(galaxy_done(data, 2, 499))

    def test_file_viewer_lock_does_not_crash_status_writer(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(Path, 'replace', side_effect=PermissionError), \
                    patch('isolated_supervisor.time.sleep'):
                self.assertFalse(atomic_json(Path(directory) / 'status.json', {}))

    def test_restart_one_process_keeps_other_process_alive(self):
        config = {'sweep': {'account_profiles': ['one', 'two']}}
        first, second = Slot(0, config), Slot(1, config)
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0
        def launch():
            return subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                                    creationflags=flags)
        first.process, second.process = launch(), launch()
        old_first, other_pid = first.process, second.process.pid
        first.galaxy = 1
        def replacement(galaxy):
            first.process = launch()
        try:
            with patch.object(first, 'start', side_effect=replacement):
                first.restart('test failure')
            self.assertIsNotNone(old_first.poll())
            self.assertNotEqual(old_first.pid, first.process.pid)
            self.assertEqual(second.process.pid, other_pid)
            self.assertIsNone(second.process.poll())
            self.assertEqual(first.restarts, 1)
        finally:
            first.close()
            second.close()

    def test_quiet_worker_is_stale_but_other_worker_is_not(self):
        config = {'sweep': {'account_profiles': ['one', 'two']}}
        first, second = Slot(0, config), Slot(1, config)
        for slot in (first, second):
            slot.process = Mock()
            slot.process.poll.return_value = None
            slot.event_count = 1
        first.last_seen, second.last_seen = 100, 330
        self.assertIsNotNone(first.failure_reason(now=350))
        self.assertIsNone(second.failure_reason(now=350))
