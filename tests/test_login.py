import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
import sys

from ev_assistant.login import click_named, login_fields, login_and_enter
from ev_assistant.vision import TextLine, UncertainScreen

FIXTURE = '''<style>body{margin:0}input,button{display:block;width:240px;height:40px;margin:12px}
#splash{position:fixed;inset:0;background:white;z-index:10}#enter{position:absolute;top:380px;left:150px;width:120px}
#registration{position:absolute;left:500px;top:0}#invisible{position:absolute;top:300px;opacity:0}
</style>
<div id="splash"><button id="enter" onclick="document.querySelector('#splash').remove()">Enter</button></div>
<div id="registration"><input id="wrong" type="email"><input type="password"><input type="password"></div>
<div id="invisible"><input><input type="password"></div>
<form id="login" onsubmit="event.preventDefault();window.submitted={username:document.querySelector('#identifier').value,password:document.querySelector('#secret').value};this.style.display='none';document.querySelector('#server').hidden=false;">
<input id="identifier" type="text"><input id="secret" type="password">
<button type="submit"><img alt="LOG IN" style="width:50px;height:20px"></button></form>
<div id="server" hidden><button onclick="document.querySelector('#server').hidden=true;document.body.dataset.phase='colony'">Start</button></div>'''


class LoginBrowserTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        bundled = Path(sys.executable).resolve().parent.parent/'browsers'
        if bundled.is_dir():
            env = patch.dict(os.environ, {'PLAYWRIGHT_BROWSERS_PATH':str(bundled)})
            env.start(); self.addCleanup(env.stop)
        from playwright.async_api import async_playwright
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(headless=True)
        self.page = await self.browser.new_page(viewport={'width':470,'height':912})
        await self.page.route('**/*', lambda route: route.abort())

    async def asyncTearDown(self):
        await self.browser.close()
        await self.playwright.stop()

    async def test_splash_and_image_button_with_offscreen_registration(self):
        for identifier in ('NewUsername', 'new-account@example.invalid'):
            with self.subTest(identifier=identifier), tempfile.TemporaryDirectory() as folder:
                await self.page.set_content(FIXTURE)
                self.assertIsNone(await login_fields(self.page))
                reader = Mock(config={},data=Path(folder))
                async def observe(page):
                    phase = await page.locator('body').get_attribute('data-phase')
                    return [TextLine('Planets Fleet Alliance' if phase=='colony' else 'Loading', .99, 0, 0)], b''
                reader.observe = observe
                await login_and_enter(reader,self.page,{'username':identifier,'password':'local-fixture-only'})
                self.assertEqual(await self.page.evaluate('window.submitted'), {'username':identifier,'password':'local-fixture-only'})
                self.assertEqual(await self.page.locator('#wrong').input_value(), '')

    async def test_ambiguous_registration_form_is_not_submitted(self):
        await self.page.set_content('<input type="text"><input type="password"><input type="password">')
        with self.assertRaisesRegex(UncertainScreen,'ambiguous'):
            await login_fields(self.page)

    async def test_missing_password_stops_without_submission(self):
        await self.page.set_content(FIXTURE)
        await click_named(self.page,r'enter')
        reader=Mock(config={})
        with self.assertRaisesRegex(UncertainScreen,'LOGIN ACTION REQUIRED'):
            await login_and_enter(reader,self.page,{'username':'NewUsername'})
        self.assertIsNone(await self.page.evaluate('window.submitted'))

    async def test_rejected_login_is_not_submitted_repeatedly(self):
        await self.page.set_content(FIXTURE)
        await click_named(self.page,r'enter')
        await self.page.locator('#login').evaluate("el => el.onsubmit=e=>{e.preventDefault();window.attempts=(window.attempts||0)+1;}")
        reader=Mock(config={})
        tick=0
        def clock():
            nonlocal tick
            tick+=10
            return tick
        with patch('ev_assistant.login.monotonic',side_effect=clock), patch('ev_assistant.login.asyncio.sleep',new=AsyncMock()):
            with self.assertRaisesRegex(UncertainScreen,'Login did not complete'):
                await login_and_enter(reader,self.page,{'username':'BadUsername','password':'fixture-only'})
        self.assertEqual(await self.page.evaluate('window.attempts'),1)
