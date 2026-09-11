"""Local canvas reader and bounded, automatic planet reconnaissance.

Run: python -m ev_assistant read|scan|search|export
Fleet dispatch and defense execution remain unavailable until calibrated.
"""
import argparse
import asyncio
import csv
import hashlib
import json
import logging
import re
import time
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from .store import Planet, Store
from .coverage import sweep_positions
from .vision import (OCR, TextLine, UncertainScreen, read_owner, compact,
                     popup_kind, map_header_readable, join_rows)

from .runtime import user_root, browser_options

ROOT = user_root()
LOG = logging.getLogger('eternal-void')


def load_config(path):
    config = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    url = urlparse(config['url'])
    if url.scheme != 'https' or url.hostname not in ('eternal-void.online', 'www.eternal-void.online'):
        raise ValueError('This adapter is calibrated only for Eternal Void')
    if config['viewport'] != {'width': 470, 'height': 912}:
        raise ValueError('This calibration requires a 470 by 912 viewport')
    sweep_positions(config)
    scan = config['scan']
    for key in ('galaxies', 'systems', 'positions'):
        if not scan[key] or any(type(n) is not int or n <= 0 for n in scan[key]):
            raise ValueError(f'{key} must contain positive integers')
    if type(scan['workers']) is not int or not 1 <= scan['workers'] <= 4:
        raise ValueError('Use between 1 and 4 scan workers')
    if not 0.90 <= config['ocr_confidence'] <= 1:
        raise ValueError('OCR confidence must be between 0.90 and 1')
    if scan['seconds_between_planets'] < 3 or scan['rescan_seconds'] < 60:
        raise ValueError('Use at least 3 seconds between coordinates and 60 seconds between passes')
    if config['monitor_seconds'] < 5:
        raise ValueError('Monitor interval must be at least 5 seconds')
    if config['fleet_dispatch_enabled'] or config['defensive_actions_enabled']:
        raise ValueError('Fleet and defensive execution are not calibrated in this version')
    return config


class Reader:
    def __init__(self, config, data):
        self.config = config
        self.data = data
        self.ocr = OCR()
        self.ocr_lock = asyncio.Lock()
        self.navigation_lock = asyncio.Lock()
        self.last_navigation = 0.0
        self.stop = data / 'STOP'
        self.map_snapshot = None
        self.ocr_cache = {}
        self.timings = defaultdict(float)

    def check_stop(self):
        if self.stop.exists():
            raise RuntimeError('STOP file detected. Automation stopped.')

    async def observe(self, page, clip=None, detail=False):
        self.check_stop()
        if urlparse(page.url).hostname not in ('eternal-void.online', 'www.eternal-void.online'):
            raise UncertainScreen('Browser left the configured game host')
        started = time.perf_counter()
        image = await page.screenshot(**({'clip': clip} if clip else {}))
        captured = time.perf_counter()
        async with self.ocr_lock:
            cache = getattr(self, 'ocr_cache', None)
            key = (detail, hashlib.sha256(image).digest())
            cached = cache.get(key) if cache is not None else None
            if cached is not None:
                # A new screenshot with identical pixels has identical text.
                # Changed images always run OCR; no timestamps or guessed UI state.
                lines = cached
                if hasattr(self, 'timings'):
                    self.timings['ocr_cache_hits'] += 1
            else:
                lines = await asyncio.to_thread(self.ocr.read_detail if detail else self.ocr.read, image)
                if cache is not None:
                    if len(cache) >= 2:
                        cache.pop(next(iter(cache)))
                    cache[key] = lines
        if hasattr(self, 'timings'):
            self.timings['capture'] += captured-started
            self.timings['ocr'] += time.perf_counter()-captured
            self.timings['ocr_calls'] += cached is None
        if clip:
            lines = [TextLine(item.text, item.confidence, item.x + clip['x'],
                              item.y + clip['y']) for item in lines]
        return lines, image

    async def expect_text(self, page, *needles, timeout=20):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            lines, image = await self.observe(page)
            text = compact('\n'.join(x.text.lower() for x in lines
                             if x.confidence >= self.config['ocr_confidence'])
                           )
            if all(compact(word) in text for word in needles):
                return lines
            await asyncio.sleep(0.5)
        raise UncertainScreen('Expected screen text not found: ' + ', '.join(needles))

    async def open_map(self, page):
        # Observed colony bottom menu -> system-view submenu.
        await self.expect_text(page, 'Planets', 'Fleet', 'Alliance')
        lines, _ = await self.observe(page)
        if any('solar' in x.text.lower() for x in lines):
            await self.expect_text(page, 'Galaxy', 'Solar', 'Planet', 'Bookmark')
            return
        self.check_stop()
        await page.mouse.click(40, 860)
        await asyncio.sleep(1.2)
        self.check_stop()
        await page.mouse.click(39, 758)
        await self.expect_text(page, 'Galaxy', 'Solar', 'Planet', 'Bookmark')

    async def enter_game(self, page):
        """Advance saved-session splash/server screens without touching account settings."""
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            lines, _ = await self.observe(page)
            text = '\n'.join(x.text for x in lines if x.confidence >= 0.80)
            lowered = text.lower()
            if 'all fields are required' in lowered:
                await page.mouse.click(235, 565)
                await asyncio.sleep(.5)
                continue
            if 'planets' in lowered and 'fleet' in lowered and 'alliance' in lowered:
                return
            if 'tap anywhere to continue' in lowered or ('enter' in lowered and 'updates' in lowered):
                await page.mouse.click(235, 566)
            elif 'start' in lowered and ('email' in lowered or 'orion' in lowered):
                await page.mouse.click(235, 777)
            elif 'password' in lowered and 'log in' in lowered:
                raise UncertainScreen('The saved session needs login again')
            await asyncio.sleep(1)
        raise UncertainScreen('Timed out while entering the saved game session')

    async def login_and_enter(self, page, account):
        """Enter one explicitly supplied account without logging its password."""
        passwords = account.get('passwords') or [account.get('password', '')]
        password_index = 0
        last_diagnostic = 0
        # Fresh isolated contexts may load game assets concurrently. Keep the
        # allowance below the supervisor's 360-second startup watchdog.
        shared = getattr(self, 'config', {}).get('_shared_browser_endpoint')
        deadline = time.monotonic() + (240 if shared else 90)
        while time.monotonic() < deadline:
            lines, entry_image = await self.observe(page)
            text = '\n'.join(x.text for x in lines if x.confidence >= 0.75)
            lowered = text.lower()
            if re.search(r'auth.*fail|invalid.*(?:credential|username|password)|incorrect.*password', lowered):
                password_index += 1
                if password_index >= len(passwords):
                    raise UncertainScreen(f'Login failed for {account["username"]}')
                await page.mouse.click(235, 565)
                await asyncio.sleep(.5)
                continue
            if 'all fields are required' in lowered:
                await page.mouse.click(235, 565)
                await asyncio.sleep(.5)
                continue
            if 'planets' in lowered and 'fleet' in lowered and 'alliance' in lowered:
                return
            if 'tap anywhere to continue' in lowered or ('enter' in lowered and 'updates' in lowered):
                await page.mouse.click(235, 566)
                await asyncio.sleep(1)
                continue
            if 'start' in lowered and ('email' in lowered or 'orion' in lowered):
                await page.mouse.click(235, 777)
                await asyncio.sleep(2)
                continue
            if 'password' in lowered and ('log in' in lowered or 'login' in lowered):
                if not passwords[password_index]:
                    raise UncertainScreen(
                        f'Saved login expired for {account["username"]}; no password available')
                inputs = page.locator('input:visible')
                count = await inputs.count()
                identifier = None
                password = None
                for index in range(count):
                    field = inputs.nth(index)
                    if await field.is_disabled():
                        continue
                    field_type = (await field.get_attribute('type') or 'text').lower()
                    if field_type == 'password' and password is None:
                        password = field
                    elif field_type != 'password' and identifier is None:
                        identifier = field
                if identifier is None or password is None:
                    raise UncertainScreen('Login fields were ambiguous')
                await identifier.fill(account['username'])
                await password.fill(passwords[password_index])
                button = page.get_by_role('button', name='LOG IN', exact=True)
                await button.click()
                await asyncio.sleep(3)
                continue
            if 'password' not in lowered and time.monotonic() - last_diagnostic >= 10:
                (self.data / 'entry-unrecognized.png').write_bytes(entry_image)
                last_diagnostic = time.monotonic()
            await asyncio.sleep(1)
        await page.screenshot(path=str(self.data / 'entry-timeout.png'),
                              mask=[page.locator('input[type="password"]')])
        raise UncertainScreen(f'Timed out entering account {account["username"]}')

    async def set_coordinate(self, page, x, value):
        self.check_stop()
        await page.mouse.click(x, 30)
        # Canvas exposes a real editable input only while a field is active.
        field = page.locator('input:visible')
        await field.wait_for(state='visible', timeout=3000)
        if await field.count() != 1:
            raise UncertainScreen('Coordinate editor is ambiguous')
        await field.fill(str(value))
        await field.press('Enter')

    async def read_coordinate(self, page, x):
        await page.mouse.click(x, 30)
        field = page.locator('input:visible')
        await field.wait_for(state='visible', timeout=3000)
        if await field.count() != 1:
            raise UncertainScreen('Coordinate reader is ambiguous')
        value = await field.input_value()
        await field.press('Enter')
        return int(value)

    @staticmethod
    def popup_details(lines, expected_galaxy, expected_system, threshold=0.82):
        popup = [line for line in lines if 180 <= line.y <= 680 and 25 <= line.x <= 445
                 and line.confidence >= threshold]
        joined = join_rows(popup)
        match = re.search(r'Coordinates\s*[:\uff1a]\s*(?:\[\s*)*(\d+)\s*[:\uff1a]\s*(\d+)\s*[:\uff1a]\s*(\d+)\s*\]?',
                          joined, re.I)
        if not match:
            return None
        coords = tuple(map(int, match.groups()))
        if coords[:2] != (expected_galaxy, expected_system):
            raise UncertainScreen(f'Loaded stale coordinates {coords}; expected '
                                  f'{expected_galaxy}:{expected_system}:*')
        owner_match = re.search(r'(?:^|\n)Player[ \t]*[:\uff1a][ \t]*([^\n]+)', joined, re.I)
        owner = owner_match.group(1).strip() if owner_match else None
        if owner:
            owner = re.sub(r'\s*\[you\]\s*$', '', owner, flags=re.I).strip()
        if not owner:
            return None
        return coords, owner

    @staticmethod
    def header_system(lines):
        values = [line for line in lines if line.confidence >= 0.78 and line.y < 48
                  and 175 <= line.x <= 295 and re.fullmatch(r'\d+', line.text.strip())]
        return int(values[0].text) if values else None

    async def dismiss_popup(self, page):
        # Do not press OK: it navigates to the selected planet and reopens detail.
        for _ in range(3):
            await page.mouse.click(235, 190)
            await asyncio.sleep(.35)
            lines, _ = await self.observe(page, {'x': 25, 'y': 230, 'width': 420, 'height': 450})
            if not popup_kind(lines):
                return
        raise UncertainScreen('Detail popup did not close after three outside clicks')

    async def ready_map(self, page, galaxy, system):
        for _ in range(4):
            lines, _ = await self.observe(page)
            if popup_kind(lines):
                await self.dismiss_popup(page)
                continue
            if map_header_readable(lines):
                self.map_snapshot = (galaxy, system, lines)
                return
            await asyncio.sleep(.5)
        raise UncertainScreen(f'Map did not settle at {galaxy}:{system}')

    async def open_map_coordinate(self, page, coords):
        for x, value in zip((89, 235, 381), coords):
            await self.set_coordinate(page, x, value)
        await page.mouse.click(296, 85)
        await asyncio.sleep(2.5)
        await self.ready_map(page, coords[0], coords[1])
        actual = await self.read_coordinate(page, 235)
        actual_galaxy = await self.read_coordinate(page, 89)
        if actual != coords[1] or actual_galaxy != coords[0]:
            raise UncertainScreen(f'Could not navigate to starting system {coords[0]}:{coords[1]}')
        await asyncio.sleep(0.6)
        return (tuple(coords), None)

    async def force_edge(self, page, direction):
        self.map_snapshot = None
        for _ in range(3):
            start, end = ((80, 650), (390, 650)) if direction < 0 else ((390, 650), (80, 650))
            await page.mouse.move(*start)
            await page.mouse.down()
            await page.mouse.move(*end, steps=12)
            await page.mouse.up()
            await asyncio.sleep(0.35)

    async def open_candidate(self, page, line, galaxy, system, data):
        previous = None
        saw_overlay = False
        for click_y in (max(135, line.y - 82), line.y):
            await page.mouse.click(line.x, click_y)
            previous = None
            for observation in range(6):
                lines, image = await self.observe(
                    page, {'x': 25, 'y': 230, 'width': 420, 'height': 450})
                overlay_text = '\n'.join(x.text for x in lines if 180 <= x.y <= 680)
                if popup_kind(lines) == 'npc':
                    await self.dismiss_popup(page)
                    return None
                detail = self.popup_details(lines, galaxy, system)
                if detail:
                    saw_overlay = True
                    if detail == previous:
                        await self.dismiss_popup(page)
                        return detail
                    previous = detail
                if ('Coordinates' in overlay_text or 'Player' in overlay_text
                        or 'Colonize' in overlay_text):
                    saw_overlay = True
                await asyncio.sleep(0.35)
            if saw_overlay:
                path = data / f'unreadable-{galaxy}-{system}-{int(line.x)}-{int(line.y)}.png'
                path.write_bytes(await page.screenshot())
                raise UncertainScreen(f'Visible detail popup was unreadable: {path}')
        raise UncertainScreen(f'Candidate could not be confirmed at {galaxy}:{system}: {line.text}')

    async def scan_map_view(self, page, galaxy, system, store, data, seen):
        if self.map_snapshot and self.map_snapshot[:2] == (galaxy, system):
            lines = self.map_snapshot[2]
            self.map_snapshot = None
        else:
            lines, _ = await self.observe(page)
        confident = [line for line in lines if line.confidence >= 0.82]
        if popup_kind(lines):
            await self.dismiss_popup(page)
            lines, _ = await self.observe(page)
            confident = [line for line in lines if line.confidence >= .82]
        if not map_header_readable(lines):
            raise UncertainScreen(f'System map header unreadable at {galaxy}:{system}')
        ignored = {
            'void bastion', 'dreah heaven', 'dread heaven', 'iron shroud',
            'crimson vault', 'desolate planet', 'mysterious nebula'
        }
        candidates = [line for line in confident if 130 <= line.y <= 760
                      and compact(line.text) not in {compact(name) for name in ignored}]
        for line in sorted(candidates, key=lambda item: (item.y, item.x)):
            # Retry this one popup before discarding the rest of a successful view.
            for candidate_attempt in range(2):
                try:
                    detail = await self.open_candidate(page, line, galaxy, system, data)
                    break
                except UncertainScreen:
                    if candidate_attempt:
                        raise
                    LOG.warning('Worker 1 retrying candidate at %s:%s: %s',
                                galaxy, system, line.text)
                    current, _ = await self.observe(
                        page, {'x': 25, 'y': 230, 'width': 420, 'height': 450})
                    if popup_kind(current):
                        await self.dismiss_popup(page)
            if not detail:
                continue
            coords, owner = detail
            if coords in seen:
                continue
            seen.add(coords)
            if owner and not re.match(r'^bot_', owner, re.I):
                store.record_sighting(self.config['universe'], coords[0], coords[1],
                                      Planet(coords[2], owner, line.text.strip()))
                LOG.info('%s -> %s (planet title: %s)', coords, owner, line.text.strip())

    async def sweep_system(self, page, galaxy, system, pan_direction, store, data):
        if self.config.get('sweep', {}).get('verification_mode') == 'explicit-slots-v1':
            from .slot_verifier import verify_system
            return await verify_system(self, page, galaxy, system, store, data)
        seen = set()
        await self.scan_map_view(page, galaxy, system, store, data, seen)
        start, end = (((390, 650), (235, 650)) if pan_direction > 0
                      else ((80, 650), (235, 650)))
        await page.mouse.move(*start)
        await page.mouse.down()
        await page.mouse.move(*end, steps=8)
        await page.mouse.up()
        await asyncio.sleep(0.45)
        await self.scan_map_view(page, galaxy, system, store, data, seen)
        await self.force_edge(page, pan_direction)
        await self.scan_map_view(page, galaxy, system, store, data, seen)
        return seen

    async def advance_system(self, page, galaxy, expected_system):
        await self.set_coordinate(page, 235, expected_system)
        await page.mouse.click(296, 85)
        await asyncio.sleep(2.5)
        await self.ready_map(page, galaxy, expected_system)
        actual = await self.read_coordinate(page, 235)
        if actual != expected_system:
            raise UncertainScreen(f'Did not reach system {galaxy}:{expected_system}')
        await asyncio.sleep(0.6)

    async def planet(self, page, coords):
        await self.expect_text(page, 'Galaxy', 'Solar', 'Bookmark')
        # One shared limit across every worker, not a separate limit per tab.
        async with self.navigation_lock:
            interval = self.config['scan']['seconds_between_planets']
            delay = interval - (time.monotonic() - self.last_navigation)
            if delay > 0:
                await asyncio.sleep(delay)
            for x, value in zip((89, 235, 381), coords):
                await self.set_coordinate(page, x, value)
            self.check_stop()
            await page.mouse.click(296, 85)
            self.last_navigation = time.monotonic()
        # Require the same owner and detail coordinates in two observations.
        deadline = time.monotonic() + 20
        last_owner = None
        while time.monotonic() < deadline:
            lines, image = await self.observe(page)
            try:
                owner = read_owner(lines, coords, self.config['ocr_confidence'])
                if owner == last_owner:
                    self.check_stop()
                    await page.mouse.click(235, 190)  # observed popup dismiss area
                    await self.expect_text(page, 'Galaxy', 'Solar', 'Bookmark')
                    return owner
                last_owner = owner
            except UncertainScreen:
                last_owner = None
            await asyncio.sleep(0.75)
        # A bounded diagnostic screenshot helps calibrate without recording credentials.
        path = self.data / ('unreadable-' + '-'.join(map(str, coords)) + '.png')
        path.write_bytes(image)
        raise UncertainScreen(f'Could not verify owner at {coords}; screenshot: {path}')

    async def monitor(self, page):
        """Read-only OCR stream. An attack word is a candidate alert, not a verdict."""
        previous = None
        while True:
            lines, _ = await self.observe(page)
            text = '\n'.join(x.text for x in lines if x.confidence >= self.config['ocr_confidence'])
            if not text:
                LOG.warning('No confident screen text; this is not an all-clear signal')
            if text != previous:
                # Avoid persisting the login screen or other credential-entry UI.
                if not re.search(r'password|log\s*in|register', text, re.I):
                    (self.data / 'latest-screen.txt').write_text(text, encoding='utf-8')
                    LOG.info('SCREEN\n%s', text)
                    if re.search(r'under attack|incoming attack|hostile fleet', text, re.I):
                        LOG.warning('Possible threat text detected. Inspect game now.\a')
                previous = text
            await asyncio.sleep(self.config['monitor_seconds'])


async def run_browser(args, config, data, store, accounts=None):
    from playwright.async_api import async_playwright
    reader = Reader(config, data)
    async with async_playwright() as playwright:
        extra_browsers = []
        from .shared_browser import AccountBrowser
        account_browser = AccountBrowser(config, data,
            accounts[0]['username'] if accounts else None)
        browser = await account_browser.open(playwright, headless=(args.command == 'sweep'))
        try:
            if args.command == 'sweep':
                from .performance import install_frame_limit, enable_frame_limit
                fps = config.get('sweep', {}).get('render_fps', 20)
                await install_frame_limit(browser, fps, defer=True)
            page = browser.pages[0] if browser.pages else await browser.new_page()
            await page.goto(config['url'], wait_until='domcontentloaded')
            if args.command != 'sweep':
                print('\nLog in directly in the game browser. Open your colony view.')
                print('This uses its own local browser profile; it does not read another browser profile.')
                await asyncio.to_thread(input, 'Press Enter here when ready: ')
            else:
                print('\nResuming saved Eternal Void session and sweep checkpoint...')
            if args.command == 'sweep' and accounts:
                await reader.login_and_enter(page, accounts[0])
                account_browser.authenticated = True
                await account_browser.save_session()
            else:
                await reader.enter_game(page)
            if args.command == 'sweep':
                await enable_frame_limit(page)
                LOG.info('Scanner animation limit: %s FPS; OpenCV pool: 1 thread', fps)
                LOG.info('Planet detail reader: %s', 'rendered text with OCR fallback'
                         if config.get('sweep', {}).get('rendered_text', False) else 'OCR')
            if args.command == 'read':
                await reader.monitor(page)
                return
            if args.command == 'probe':
                await reader.open_map(page)
                for index in range(6):
                    lines, image = await reader.observe(page)
                    (data / f'probe-{index}.png').write_bytes(image)
                    print(f'\nPROBE {index}')
                    for line in lines:
                        if line.confidence >= 0.70:
                            print(f'{line.x:6.1f} {line.y:6.1f} {line.confidence:.3f} {line.text}')
                    await page.mouse.move(390, 650)
                    await page.mouse.down()
                    await page.mouse.move(80, 650, steps=12)
                    await page.mouse.up()
                    await asyncio.sleep(1)
                return
            if args.command == 'sweep':
                progress_path = data / 'sweep-progress.json'
                retry_path = data / 'sweep-retries.json'
                coverage_path = data / 'coverage.json'
                if progress_path.exists():
                    progress = json.loads(progress_path.read_text(encoding='utf-8'))
                else:
                    progress = {}
                if retry_path.exists():
                    retry_data = json.loads(retry_path.read_text(encoding='utf-8'))
                    retry_holes = {str(item) for item in retry_data.get('systems', [])}
                else:
                    retry_holes = set()
                if coverage_path.exists():
                    coverage = json.loads(coverage_path.read_text(encoding='utf-8'))
                    progress = coverage['progress']
                    retry_holes = set(coverage['retry_holes'])
                sweep = config['sweep']
                first_position = sweep_positions(config)[0]
                systems = sweep.get('systems') or list(range(
                    int(sweep['system_start']), int(sweep['system_end']) + 1))
                galaxy_queue = asyncio.Queue()
                for galaxy in sweep['galaxies']:
                    completed = int(progress.get(str(galaxy), 0))
                    if (any(system > completed for system in systems)
                            or any(key.startswith(f'{galaxy}:') for key in retry_holes)):
                        galaxy_queue.put_nowait(galaxy)
                progress_lock = asyncio.Lock()

                async def checkpoint(galaxy, system, failed=False):
                    key = f'{galaxy}:{system}'
                    async with progress_lock:
                        progress[str(galaxy)] = max(
                            int(progress.get(str(galaxy), 0)), system)
                        if failed:
                            retry_holes.add(key)
                        else:
                            retry_holes.discard(key)
                        # Frontier and holes must commit together so a crash can
                        # never skip a failed system after advancing the frontier.
                        temp_coverage = coverage_path.with_suffix('.tmp')
                        temp_coverage.write_text(json.dumps({
                            'progress': progress, 'retry_holes': sorted(retry_holes)
                        }, indent=2), encoding='utf-8')
                        temp_coverage.replace(coverage_path)
                        progress_temp = progress_path.with_suffix('.tmp')
                        progress_temp.write_text(
                            json.dumps(progress, indent=2), encoding='utf-8')
                        progress_temp.replace(progress_path)
                        retry_temp = retry_path.with_suffix('.tmp')
                        retry_temp.write_text(json.dumps({
                            'systems': sorted(
                                retry_holes,
                                key=lambda value: tuple(map(int, value.split(':'))))
                        }, indent=2), encoding='utf-8')
                        retry_temp.replace(retry_path)
                        export_players(store, data)

                requested_workers = int(sweep.get('workers', 1))
                if accounts:
                    requested_workers = min(requested_workers, len(accounts))
                worker_count = min(requested_workers, galaxy_queue.qsize())
                worker_slots = [(reader, page)]
                for worker_index in range(1, worker_count):
                    worker_reader = Reader(config, data)
                    profile_name = (f'browser-profile-account-{worker_index}' if accounts
                                    else f'browser-profile-worker-{worker_index}')
                    browser_names = sweep.get('worker_browsers', [])
                    browser_name = (browser_names[worker_index]
                                    if worker_index < len(browser_names) else 'chrome')
                    if browser_name == 'edge':
                        profile_name += '-edge'
                    worker_browser = await playwright.chromium.launch_persistent_context(
                        str(data / profile_name), headless=True,
                        **browser_options('msedge' if browser_name == 'edge' else 'chrome'),
                        viewport=config['viewport'], device_scale_factor=1)
                    extra_browsers.append(worker_browser)
                    from .performance import install_frame_limit
                    await install_frame_limit(worker_browser, sweep.get('render_fps', 20), defer=True)
                    worker_page = (worker_browser.pages[0] if worker_browser.pages
                                   else await worker_browser.new_page())
                    await worker_page.goto(config['url'], wait_until='domcontentloaded')
                    if accounts:
                        await worker_reader.login_and_enter(worker_page, accounts[worker_index])
                        LOG.info('Authenticated worker %s as %s using %s', worker_index + 1,
                                 accounts[worker_index]['username'], browser_name)
                    else:
                        await worker_reader.enter_game(worker_page)
                    await enable_frame_limit(worker_page)
                    worker_slots.append((worker_reader, worker_page))

                async def sweep_worker(worker_index):
                    worker_reader, worker_page = worker_slots[worker_index]
                    await worker_reader.open_map(worker_page)
                    while True:
                        try:
                            galaxy = galaxy_queue.get_nowait()
                        except asyncio.QueueEmpty:
                            return
                        try:
                            completed = int(progress.get(str(galaxy), 0))
                            pending = [system for system in systems if system > completed]
                            holes = sorted(int(key.split(':')[1]) for key in retry_holes
                                           if key.startswith(f'{galaxy}:'))
                            if pending:
                                LOG.info('Worker %s scanning Galaxy %s from system %s',
                                         worker_index + 1, galaxy, pending[0])
                            elif holes:
                                LOG.info('Worker %s resolving %s retry systems in Galaxy %s',
                                         worker_index + 1, len(holes), galaxy)
                            else:
                                continue

                            # Finish the contiguous frontier first. Any stubborn
                            # system is retained as a hole and retried after all
                            # other systems in this galaxy have been visited.
                            first_pass = pending
                            retry_round = 0
                            while first_pass or holes:
                                current_pass = first_pass if first_pass else list(holes)
                                first_pass = []
                                retry_round += 1
                                if retry_round > 1:
                                    LOG.warning('Worker %s retry round %s for Galaxy %s: %s',
                                                worker_index + 1, retry_round - 1,
                                                galaxy, holes)
                                    await asyncio.sleep(min(30, retry_round * 2))
                                pan_direction = 1
                                await worker_reader.open_map_coordinate(
                                    worker_page, (galaxy, current_pass[0], first_position))
                                await worker_reader.force_edge(worker_page, -1)
                                for index, system in enumerate(current_pass):
                                    worker_reader.check_stop()
                                    seen = None
                                    last_error = None
                                    for attempt in range(1, 4):
                                        try:
                                            seen = await worker_reader.sweep_system(
                                                worker_page, galaxy, system, pan_direction,
                                                store, data)
                                            break
                                        except UncertainScreen as exc:
                                            last_error = exc
                                            LOG.warning('Worker %s retrying %s:%s (%s/3): %s',
                                                        worker_index + 1, galaxy, system,
                                                        attempt, exc)
                                            await worker_page.keyboard.press('Escape')
                                            await worker_reader.open_map_coordinate(
                                                worker_page, (galaxy, system, first_position))
                                            await worker_reader.force_edge(worker_page, -1)
                                            pan_direction = 1
                                    if seen is None:
                                        await checkpoint(galaxy, system, failed=True)
                                        LOG.warning(
                                            'Worker %s queued %s:%s for another pass; '
                                            'other systems continue (%s)',
                                            worker_index + 1, galaxy, system, last_error)
                                    else:
                                        await checkpoint(galaxy, system, failed=False)
                                        LOG.info(
                                            'Worker %s completed %s:%s '
                                            '(%s confirmed named slots)',
                                            worker_index + 1, galaxy, system, len(seen))
                                    pan_direction *= -1
                                    if index + 1 < len(current_pass):
                                        await worker_reader.advance_system(
                                            worker_page, galaxy, current_pass[index + 1])
                                        if seen is None:
                                            await worker_reader.force_edge(worker_page, -1)
                                            pan_direction = 1
                                holes = sorted(
                                    int(key.split(':')[1]) for key in retry_holes
                                    if key.startswith(f'{galaxy}:'))
                                # Yield unfinished holes to the outer scheduler;
                                # never monopolize an account with endless retry rounds.
                                if retry_round >= int(sweep.get('max_passes_per_job', 1)):
                                    if holes:
                                        LOG.warning('Worker %s deferring Galaxy %s retry systems: %s',
                                                    worker_index + 1, galaxy, holes)
                                    break
                        finally:
                            galaxy_queue.task_done()

                tasks = [asyncio.create_task(sweep_worker(index))
                         for index in range(worker_count)]
                try:
                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    failures = [result for result in results
                                if isinstance(result, BaseException)]
                    if failures:
                        raise RuntimeError(
                            f'{len(failures)} sweep worker(s) stopped unexpectedly; '
                            'checkpoints and retry holes were preserved') from failures[0]
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                export_players(store, data)
                LOG.info('Sweep pass finished with %s unresolved systems: %s',
                         len(retry_holes), data / 'players.txt')
                return
            scan = config['scan']
            store.seed(config['universe'], scan['galaxies'], scan['systems'])
            async def worker(index):
                worker_page = page if index == 0 else await browser.new_page()
                if index:
                    await worker_page.goto(config['url'], wait_until='domcontentloaded')
                await reader.open_map(worker_page)
                while True:
                    reader.check_stop()
                    lease = store.claim(config['universe'], lease_seconds=600)
                    if lease is None:
                        return
                    try:
                        for position in scan['positions']:
                            store.renew(lease)
                            coords = (lease.galaxy, lease.system, position)
                            owner = await reader.planet(worker_page, coords)
                            store.record_sighting(lease.universe, lease.galaxy,
                                                  lease.system, Planet(position, owner, ''), lease=lease)
                            LOG.info('%s -> %s', coords, owner)
                        store.finish_pass(lease, scan['rescan_seconds'])
                    except Exception:
                        try:
                            store.fail(lease)
                        except ValueError:
                            pass
                        raise
            tasks = [asyncio.create_task(worker(i)) for i in range(scan['workers'])]
            try:
                await asyncio.gather(*tasks)
            finally:
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                store.export_csv(data / 'planets.csv')
            LOG.info('Configured pass finished. Last-seen coordinates: %s', data / 'planets.csv')
        finally:
            for extra_browser in extra_browsers:
                await extra_browser.close()
            await account_browser.close()


def export_players(store, data):
    grouped = defaultdict(list)
    for row in store.search():
        if re.match(r'^bot_', row['player'], re.I):
            continue
        grouped[row['player']].append(f"{row['galaxy']}:{row['system']}:{row['position']}")
    with open(data / 'players.csv', 'w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.writer(handle)
        writer.writerow(['player', 'coordinates'])
        for player in sorted(grouped, key=str.casefold):
            writer.writerow([player, ' '.join(grouped[player])])
    lines = []
    for player in sorted(grouped, key=str.casefold):
        lines.append(player)
        lines.extend(f'  {coords}' for coords in grouped[player])
    (data / 'players.txt').write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['read', 'probe', 'scan', 'sweep', 'search', 'export'])
    parser.add_argument('--config', default=str(ROOT / 'config.json'))
    parser.add_argument('--data-dir', default=str(ROOT / 'data'))
    parser.add_argument('--player')
    parser.add_argument('--accounts-file')
    args = parser.parse_args()
    config = load_config(args.config)
    data = Path(args.data_dir).resolve()
    data.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.StreamHandler(), logging.FileHandler(data / 'activity.log', encoding='utf-8')])
    store = Store(config.get('store_path', data / 'observations.sqlite'))
    accounts = None
    if args.accounts_file:
        accounts_path = Path(args.accounts_file).resolve()
        accounts = json.loads(accounts_path.read_text(encoding='utf-8'))
        accounts_path.unlink()
    elif args.command == 'sweep' and config['sweep'].get('account_profiles'):
        from .credentials import load_passwords
        credentials_root = Path(config.get('store_path', data / 'observations.sqlite')).parent
        accounts = [{'username': username}
                    for username in config['sweep']['account_profiles']]
        for account in accounts:
            saved = load_passwords(credentials_root, account['username'])
            if saved:
                account['passwords'] = saved
    if args.command == 'search':
        print(json.dumps(store.search(args.player), indent=2))
    elif args.command == 'export':
        store.export_csv(data / 'planets.csv')
        print(data / 'planets.csv')
    else:
        try:
            asyncio.run(run_browser(args, config, data, store, accounts))
        except KeyboardInterrupt:
            LOG.info('Stopped by user')
        except Exception as exc:
            LOG.error('Stopped: %s', exc)
            raise SystemExit(1)


if __name__ == '__main__':
    main()
