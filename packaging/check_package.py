"""Offline checks executed by the shipped Python, without developer dependencies."""
import asyncio
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

package = Path(sys.argv[1]).resolve()
assert Path(sys.executable).is_relative_to(package), 'Must use bundled Python'
assert not (package / 'config.json').exists(), 'Never distribute local settings'
assert not (package / 'desktop-runtime.json').exists(), 'Never distribute developer paths'
assert not (package / 'data').exists(), 'Never distribute local data'
assert not list(package.rglob('*.dpapi')), 'Never distribute credentials'

from ev_assistant.runtime import APP_ROOT, user_root, browser_options
assert APP_ROOT == package
assert user_root() == Path(os.environ['EOG_DATA_ROOT']).resolve()
assert browser_options() == {}, 'A release must use bundled Chromium'
for name in ('app_bridge', 'isolated_supervisor', 'ev_assistant.__main__',
             'eog_automation.worker', 'eog_automation.service', 'eog_automation.storage'):
    importlib.import_module(name)

# Exercise native OCR libraries and shipped model assets, with no network requests.
from PIL import Image, ImageDraw, ImageFont
from ev_assistant.vision import OCR
fixture = Image.new('RGB', (470, 160), 'white')
draw = ImageDraw.Draw(fixture)
draw.text((20, 40), 'EOG 12345', fill='black', font=ImageFont.load_default(size=32))
buffer = io.BytesIO()
fixture.save(buffer, format='PNG')
lines = OCR().read(buffer.getvalue())
assert any('12345' in line.text for line in lines), f'OCR fixture was not recognized: {lines}'
# Verify native imports actually used our app-local MSVC DLLs, not system copies.
import ctypes
kernel = ctypes.WinDLL('kernel32', use_last_error=True)
kernel.GetModuleHandleW.argtypes = [ctypes.c_wchar_p]
kernel.GetModuleHandleW.restype = ctypes.c_void_p
kernel.GetModuleFileNameW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint]
for name in ('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll'):
    handle = kernel.GetModuleHandleW(name)
    assert handle, f'{name} was not loaded'
    filename = ctypes.create_unicode_buffer(32768)
    assert kernel.GetModuleFileNameW(handle, filename, len(filename))
    assert Path(filename.value).is_relative_to(package), f'Used system runtime: {filename.value}'

async def browsers():
    from playwright.async_api import async_playwright
    from ev_assistant.shared_browser import SharedBrowserHost, AccountBrowser
    with tempfile.TemporaryDirectory(prefix='eog-browser-') as temp:
        data = Path(temp)
        async with async_playwright() as playwright:
            assert Path(playwright.chromium.executable_path).is_relative_to(package)
            account = AccountBrowser({'viewport': {'width':470,'height':912}}, data)
            context = await account.open(playwright)
            page = await context.new_page()
            await page.set_content('<title>EOG package check</title><p>Offline browser works</p>')
            assert await page.title() == 'EOG package check'
            await account.close()
            host = SharedBrowserHost(package, data)
            try:
                assert await asyncio.to_thread(host.ensure), 'Shared browser failed to start'
                connection = await playwright.chromium.connect(host.info['endpoint'])
                context = await connection.new_context()
                page = await context.new_page()
                await page.set_content('<title>Shared browser works</title>')
                assert await page.title() == 'Shared browser works'
                await context.close()
                await connection.close()
            finally:
                await asyncio.to_thread(host.close)

asyncio.run(browsers())
# Same child-process import mechanism used by scanner and upgrade workers.
result = subprocess.run([sys.executable, '-c',
    'from ev_assistant.runtime import user_root; import eog_automation.worker; print(user_root())'],
    cwd=tempfile.gettempdir(), capture_output=True, text=True, check=True, timeout=30)
assert result.stdout.strip() == str(user_root())
print(json.dumps({'passed': True, 'bundledPython': True, 'ocr': True,
                  'isolatedBrowser': True, 'sharedBrowser': True, 'childProcess': True}))
