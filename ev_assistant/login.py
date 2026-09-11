"""Select only painted, reachable login controls in the current viewport."""
import re
import asyncio
import logging
from time import monotonic
from .vision import UncertainScreen


async def onscreen(page, selector):
    controls = []
    for element in await page.locator(selector).element_handles():
        if await element.evaluate('''el => {
            const r=el.getBoundingClientRect();
            if(el.disabled || r.width<=0 || r.height<=0 || r.left<0 || r.top<0 || r.right>innerWidth || r.bottom>innerHeight) return false;
            let opacity=1;
            for(let e=el;e;e=e.parentElement) {
                const s=getComputedStyle(e); opacity*=Number(s.opacity);
                if(s.display==='none' || s.visibility==='hidden') return false;
            }
            const top=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);
            return el.isConnected && opacity>=0.5 && (top===el || el.contains(top));
        }'''):
            controls.append(element)
    return controls


async def named_buttons(page, pattern):
    matched = []
    for button in await onscreen(page, 'button'):
        labels = await button.evaluate('el => [el.innerText,el.getAttribute("aria-label"),...Array.from(el.querySelectorAll("img")).map(i=>i.alt)]')
        if any(re.fullmatch(pattern, str(label).strip(), re.I) for label in labels if label):
            matched.append(button)
    return matched


async def click_named(page, pattern):
    buttons = await named_buttons(page, pattern)
    if len(buttons) > 1:
        raise UncertainScreen('LOGIN ACTION REQUIRED: More than one login control matches; login stopped')
    if not buttons:
        return False
    await buttons[0].click()
    return True


async def login_and_enter(reader, page, account):
    passwords = account.get('passwords') or [account.get('password', '')]
    password_index = 0
    submitted_at = None
    shared = getattr(reader, 'config', {}).get('_shared_browser_endpoint')
    deadline = monotonic() + (240 if shared else 90)
    log = logging.getLogger('eternal-void')
    while monotonic() < deadline:
        reader.check_stop()
        if await click_named(page, r'enter'):
            log.info('Opening the game login screen')
            await asyncio.sleep(1)
            continue
        fields = await login_fields(page)
        if fields:
            if submitted_at is None:
                if not passwords[password_index]:
                    raise UncertainScreen("LOGIN ACTION REQUIRED: Save this account's password in Agents & accounts")
                await submit_login(page, fields, account['username'], passwords[password_index])
                submitted_at = monotonic()
                log.info('Login submitted; waiting for the game response')
            elif monotonic() - submitted_at >= 25:
                raise UncertainScreen('LOGIN ACTION REQUIRED: Login did not complete. Check the username and password, then Save & apply')
            await asyncio.sleep(1)
            continue
        if await click_named(page, r'start'):
            log.info('Entering the selected game server')
            await asyncio.sleep(2)
            continue
        lines, _ = await reader.observe(page)
        lowered = ' '.join(x.text for x in lines if x.confidence >= .75).lower()
        if re.search(r'auth.*fail|invalid.*(?:credential|username|password)|incorrect.*password', lowered):
            password_index += 1
            if password_index < len(passwords) and await dismiss_dialog(page, lines):
                submitted_at = None
                continue
            raise UncertainScreen('LOGIN ACTION REQUIRED: The game rejected the login. Correct this account in Agents & accounts, then Save & apply')
        if 'all fields are required' in lowered:
            if await dismiss_dialog(page, lines):
                submitted_at = None
                continue
            raise UncertainScreen('LOGIN ACTION REQUIRED: The game requires login details. Check the saved username and password')
        if 'planets' in lowered and 'fleet' in lowered and 'alliance' in lowered:
            return
        if 'tap anywhere to continue' in lowered:
            await page.mouse.click(235, 566)
        await asyncio.sleep(1)
    await page.screenshot(path=str(reader.data/'entry-timeout.png'), mask=[page.locator('input')])
    raise UncertainScreen('LOGIN ACTION REQUIRED: The game did not finish opening. Check your connection and account details, then use Restart selected')


async def dismiss_dialog(page, lines):
    if await click_named(page, r'ok|close|try again'):
        return True
    buttons = [line for line in lines if line.confidence >= .8 and re.fullmatch(r'ok|close|try again', line.text.strip(), re.I)]
    if len(buttons) == 1:
        await page.mouse.click(buttons[0].x, buttons[0].y)
        return True
    return False


async def login_fields(page):
    passwords = await onscreen(page, 'input[type="password"]')
    if not passwords:
        return None
    identifiers = await onscreen(page, 'input:is([type="text"],[type="email"],:not([type]))')
    if len(passwords) != 1 or len(identifiers) != 1:
        raise UncertainScreen('LOGIN ACTION REQUIRED: Login fields are ambiguous; nothing was submitted')
    return identifiers[0], passwords[0]


async def submit_login(page, fields, username, password):
    buttons = await named_buttons(page, r'log\s*in')
    if len(buttons) != 1:
        raise UncertainScreen('LOGIN ACTION REQUIRED: The Log in button could not be identified; nothing was submitted')
    await fields[0].fill(username)
    await fields[1].fill(password)
    await buttons[0].click()
