"""One local Playwright server; independent, encrypted account sessions."""
import hashlib
import json
import logging
import os
from pathlib import Path
import subprocess
import time

from .credentials import crypt
from .runtime import browser_options

LOG = logging.getLogger(__name__)


class SharedBrowserHost:
    def __init__(self, root, data):
        self.root, self.data = Path(root), Path(data)
        self.process = self.output = None
        self.info = {}
        self.next_attempt = 0
        self.state_path = self.data / 'shared-browser-runtime.json'

    @property
    def alive(self):
        return self.process is not None and self.process.poll() is None and bool(self.info)

    def ensure(self):
        if self.alive:
            return True
        if time.monotonic() < self.next_attempt:
            return False
        self.close()
        try:
            import playwright
            driver = Path(playwright.__file__).parent / 'driver'
            self.data.mkdir(parents=True, exist_ok=True)
            self.output = (self.data / 'shared-browser.log').open('a', encoding='utf-8')
            options = browser_options()
            self.process = subprocess.Popen([
                str(driver / ('node.exe' if os.name == 'nt' else 'node')),
                str(self.root / 'shared_browser_host.cjs'), str(driver / 'package'),
                str(self.state_path), options.get('channel', '')], cwd=self.root, stdin=subprocess.PIPE,
                stdout=self.output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                if self.process.poll() is not None:
                    raise RuntimeError('Host exited during startup')
                if self.state_path.exists():
                    self.info = json.loads(self.state_path.read_text(encoding='utf-8'))
                    if self.info.get('hostPid') == self.process.pid:
                        LOG.info('Shared Chrome ready PID=%s', self.info['browserPid'])
                        return True
                time.sleep(.1)
            raise RuntimeError('Shared Chrome startup timed out')
        except Exception:
            LOG.error('Shared Chrome unavailable; retrying in 30 seconds')
            self.close()
            self.next_attempt = time.monotonic() + 30
            return False

    def close(self):
        if self.process is not None:
            if self.process.poll() is None:
                try:
                    self.process.stdin.close()
                    self.process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    if os.name == 'nt':
                        subprocess.run(['taskkill', '/PID', str(self.process.pid), '/T', '/F'],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                       timeout=25)
                    else:
                        self.process.kill()
                    self.process.wait(timeout=10)
            self.process = None
        if self.output:
            self.output.close()
            self.output = None
        self.info = {}
        self.state_path.unlink(missing_ok=True)


class AccountBrowser:
    """Context lifecycle shared by normal workers and integration checks."""
    def __init__(self, config, data, account=None):
        self.config, self.data, self.account = config, Path(data), account
        self.connection = self.context = None
        self.authenticated = False
        self.session_path = None
        if config.get('_shared_browser_endpoint'):
            if not account or config.get('sweep', {}).get('workers') != 1:
                raise ValueError('Shared Chrome requires one named account per worker process')
            key = hashlib.sha256(account.casefold().encode('utf-8')).hexdigest()
            root = Path(config['store_path']).parent / 'browser-sessions'
            self.session_path = root / (key + '.dpapi')

    async def open(self, playwright, headless=True):
        if self.session_path is None:
            self.context = await playwright.chromium.launch_persistent_context(
                str(self.config.get('browser_profile', self.data / 'browser-profile')),
                headless=headless, **browser_options(),
                viewport=self.config['viewport'], device_scale_factor=1)
        else:
            state = None
            if self.session_path.exists():
                try:
                    state = json.loads(crypt(self.session_path.read_bytes(), decrypt=True))
                except Exception:
                    LOG.warning('Saved browser session unreadable; signing in again')
            try:
                self.connection = await playwright.chromium.connect(
                    self.config['_shared_browser_endpoint'], timeout=20000)
                self.context = await self.connection.new_context(
                    viewport=self.config['viewport'], device_scale_factor=1,
                    storage_state=state)
            except Exception:
                if self.connection:
                    await self.connection.close()
                # Never write the private server endpoint into a worker log.
                raise RuntimeError('Cannot open isolated session in shared Chrome') from None
        return self.context

    async def save_session(self):
        if self.session_path is not None and self.authenticated:
            try:
                state = await self.context.storage_state()
                self.session_path.parent.mkdir(parents=True, exist_ok=True)
                temp = self.session_path.with_suffix('.tmp')
                temp.write_bytes(crypt(json.dumps(state).encode('utf-8')))
                temp.replace(self.session_path)
            except Exception:
                LOG.warning('Browser session could not be saved; scan receipts remain saved')

    async def close(self):
        await self.save_session()
        try:
            if self.context:
                await self.context.close()
        finally:
            if self.connection:
                # Remote Browser.close disconnects this client, not the server.
                await self.connection.close()
