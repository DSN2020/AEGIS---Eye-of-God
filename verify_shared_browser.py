"""Offline real-Chrome checks: isolated logins, reconnects and failure recovery."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from playwright.async_api import async_playwright
from ev_assistant.shared_browser import AccountBrowser, SharedBrowserHost

ROOT = Path(__file__).resolve().parent


async def page_for(context):
    await context.route('http://eog.test/**', lambda route: route.fulfill(body='<title>Fixture</title>'))
    page = await context.new_page()
    await page.goto('http://eog.test/')
    return page


async def crashed_client(config_path):
    config = json.loads(Path(config_path).read_text(encoding='utf-8'))
    async with async_playwright() as pw:
        account = AccountBrowser(config, Path(config_path).parent, 'Crash fixture')
        await account.open(pw)
        await page_for(account.context)
        Path(config_path).with_suffix('.ready').touch()
        await asyncio.Event().wait()


async def verify():
    with tempfile.TemporaryDirectory(prefix='eog-shared-check-') as folder:
        data = Path(folder)
        host = SharedBrowserHost(ROOT, data)
        clients = []
        child = None
        try:
            assert host.ensure(), 'Host failed to launch'
            original_pid = host.info['browserPid']
            config = {'_shared_browser_endpoint': host.info['endpoint'],
                      'viewport': {'width': 470, 'height': 912},
                      'store_path': str(data / 'fixture.sqlite'), 'sweep': {'workers': 1}}
            async with async_playwright() as pw:
                a, b = [AccountBrowser(config, data, name) for name in ('Fixture A', 'Fixture B')]
                clients.extend([a, b])
                await a.open(pw)
                await b.open(pw)
                pa, pb = await page_for(a.context), await page_for(b.context)
                await pa.evaluate("localStorage.setItem('login', 'fixture-a'); document.cookie='login=a'")
                assert await pb.evaluate("localStorage.getItem('login')") is None
                assert await b.context.cookies() == []
                await pb.evaluate("localStorage.setItem('login', 'fixture-b')")
                a.authenticated = True
                await a.save_session()
                assert b'fixture-a' not in a.session_path.read_bytes(), 'Session not encrypted'
                await a.close()
                clients.remove(a)
                assert await pb.evaluate("localStorage.getItem('login')") == 'fixture-b'
                a = AccountBrowser(config, data, 'Fixture A')
                clients.append(a)
                await a.open(pw)
                pa = await page_for(a.context)
                assert await pa.evaluate("localStorage.getItem('login')") == 'fixture-a'
                assert (await a.context.cookies())[0]['value'] == 'a'
                # A real worker-process crash must release only its own contexts.
                path = data / 'client.json'
                path.write_text(json.dumps(config), encoding='utf-8')
                child = subprocess.Popen([sys.executable, __file__, '--client', str(path)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                for _ in range(200):
                    if path.with_suffix('.ready').exists():
                        break
                    assert child.poll() is None, 'Fixture client exited'
                    await asyncio.sleep(.1)
                else:
                    raise AssertionError('Fixture client startup timed out')
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                               capture_output=True, text=True, check=False)
                if child.poll() is None:
                    child.kill()
                child.wait(timeout=10)
                assert await pb.evaluate("localStorage.getItem('login')") == 'fixture-b'
                assert host.info['browserPid'] == original_pid and host.alive
                cdp = await b.connection.new_browser_cdp_session()
                for _ in range(50):
                    remaining = (await cdp.send('Target.getBrowserContexts'))['browserContextIds']
                    if len(remaining) == 2:
                        break
                    await asyncio.sleep(.1)
                assert len(remaining) == 2, 'Crashed client left an orphan context'
                await cdp.detach()
                # Browser failure: host detects exit, reopens and accepts clients.
                subprocess.run(['taskkill', '/PID', str(original_pid), '/T', '/F'],
                               capture_output=True, text=True, check=False)
                for _ in range(100):
                    if not host.alive:
                        break
                    await asyncio.sleep(.1)
                assert not host.alive
                for client in clients:
                    client.authenticated = False
                    await client.close()
                clients.clear()
                assert host.ensure() and host.info['browserPid'] != original_pid
                config['_shared_browser_endpoint'] = host.info['endpoint']
                restored = AccountBrowser(config, data, 'Fixture A')
                clients.append(restored)
                await restored.open(pw)
                assert await (await page_for(restored.context)).evaluate("localStorage.getItem('login')") == 'fixture-a'
                for client in clients:
                    await client.close()
                clients.clear()
            print('PASS: isolated cookies/storage; encrypted session restore; individual worker crash; shared browser crash/recovery')
        finally:
            if child and child.poll() is None:
                subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            host.close()


if __name__ == '__main__':
    asyncio.run(crashed_client(sys.argv[2]) if len(sys.argv) > 1 else verify())
