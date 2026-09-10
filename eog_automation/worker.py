"""Independent scheduled profile worker. Closing EOG does not stop it."""
import argparse
import asyncio
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse
from ev_assistant.credentials import load_passwords
from .storage import atomic_json, read_json
from .service import Service, AccountLock
from .vision import OCR, UncertainScreen
from .executor import ExecutionBlocked
from .engine import PlanController, ScheduledEnd
from .model import timestamp
URL='https://eternal-void.online/'


async def onscreen(page,selector,hit_test=True):
    """Playwright visibility includes the offscreen registration carousel."""
    fields=[]
    locator=page.locator(selector) if isinstance(selector,str) else selector
    for field in await locator.element_handles():
        bounds=await field.bounding_box()
        if not bounds or not (bounds['width']>0 and bounds['height']>0 and 0<=bounds['x'] and bounds['x']+bounds['width']<=470 and 0<=bounds['y'] and bounds['y']+bounds['height']<=912):
            continue
        painted=await field.evaluate('el => { let a=1; for(let e=el;e;e=e.parentElement){const s=getComputedStyle(e);a*=Number(s.opacity);if(s.visibility==="hidden"||s.display==="none")return false;} return el.isConnected&&a>=0.5; }')
        reachable=not hit_test or await field.evaluate('el => { const r=el.getBoundingClientRect();const top=document.elementFromPoint(r.x+r.width/2,r.y+r.height/2);return top===el||el.contains(top); }')
        if painted and reachable:fields.append(field)
    return fields

async def click_control(page, pattern):
    controls=await onscreen(page,page.get_by_role('button',name=re.compile(pattern,re.I)))
    if len(controls)!=1:raise RuntimeError('The requested login control is not uniquely visible')
    await controls[0].click()

async def run(profile_id):
    from playwright.async_api import async_playwright
    root=Path(__file__).resolve().parent.parent
    service=Service(root);profile=service.get(profile_id);account=profile['account'];visible=False
    path=service.path(profile);account_path=service.account_path(profile);claim=service.existing_claim(profile)
    lock=None;last={}
    def status(state,message,**extra):
        last.update(state=state,message=message,updated=time.time(),pid=os.getpid(),**extra)
        atomic_json(path/'status.json',last)
    def require_running():
        if (path/'STOP').exists():raise InterruptedError('Paused')
        if read_json(claim,{}).get('profileId')!=profile_id:raise InterruptedError('Account reservation was released')
        end=timestamp(profile.get('endAt'))
        if end is not None and time.time()>=end:raise ScheduledEnd('Scheduled end reached')
    async def sleep(seconds):
        until=time.monotonic()+seconds
        while time.monotonic()<until:
            require_running()
            if time.time()-last.get('updated',0)>5:status(last.get('state','waiting'),last.get('message','Waiting'))
            await asyncio.sleep(min(.5,max(0,until-time.monotonic())))
    try:
        lock=AccountLock(account_path/'worker.lock')
        require_running()
        start=timestamp(profile.get('startAt'))
        if start is not None and time.time()<start:
            status('scheduled','Waiting for the scheduled start',nextCheck=start)
            await sleep(start-time.time())
        if claim != service.claim(profile):
            active_claim=service.claim(profile)
            atomic_json(active_claim,read_json(claim,{}))
            claim.unlink(missing_ok=True);claim=active_claim
        # Wait for the supervisor to close this account's scanner before logging in.
        import socket
        deadline=time.monotonic()+90
        while True:
            require_running()
            probe=socket.socket()
            try:probe.bind(('127.0.0.1',47682));running=False
            except OSError:running=True
            finally:probe.close()
            state=read_json(root/'data'/'sweep-status.json',{})
            matching=[w for w in state.get('workers',{}).values() if w.get('account','').casefold()==account.casefold()]
            if not running or (state.get('accountReservationsSupported') and all(w.get('state')=='managing' and not w.get('pid') for w in matching)):break
            if time.monotonic()>deadline:raise ExecutionBlocked('Scanner did not release this account; pause the profile and retry')
            status('handoff',"Waiting for this account's scanner to close");await sleep(1)
        status('starting','Opening the account and verifying login')
        ocr=OCR()
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch_persistent_context(str(account_path/'browser-profile'),channel='chrome',headless=True,
                viewport={'width':470,'height':912},device_scale_factor=1)
            try:
                from ev_assistant.performance import install_frame_limit, enable_frame_limit
                await install_frame_limit(browser,20,defer=True)
                page=browser.pages[0] if browser.pages else await browser.new_page()
                status('connecting','Loading the game page')
                await page.goto(URL,wait_until='domcontentloaded',timeout=90000)
                entered, login_attempted = False, False
                identity = {}
                deadline = time.monotonic() + (240)
                while not entered and time.monotonic() < deadline:
                    require_running()
                    if urlparse(page.url).hostname != 'eternal-void.online':
                        raise RuntimeError('Browser left Eternal Void')
                    password_fields = await onscreen(page,'input[type="password"]:visible:enabled')
                    if password_fields:
                        passwords = load_passwords(root/'data', account)
                        if not passwords:
                            raise RuntimeError('Save this account’s password in Agents & accounts')
                        if login_attempted:
                            if time.monotonic()-login_attempted<25:
                                await sleep(1);continue
                            raise RuntimeError('Login failed; check the saved account credentials')
                        identifiers=await onscreen(page,'input:visible:enabled:is([type="text"],[type="email"],:not([type]))')
                        if len(identifiers)!=1 or len(password_fields)!=1:
                            raise RuntimeError('Login fields changed; account login stopped')
                        status('login','Filling the account login form')
                        await identifiers[0].fill(account)
                        await password_fields[0].fill(passwords[0])
                        status('login','Submitting login')
                        await click_control(page,r'^\s*log\s*in\s*$')
                        login_attempted = time.monotonic()
                        await sleep(3)
                        continue
                    entry_image=await page.screenshot(mask=[page.locator('input')])
                    temporary=account_path/'entry.tmp';temporary.write_bytes(entry_image);os.replace(temporary,account_path/'screen.png')
                    lines = await asyncio.to_thread(ocr.read, entry_image)
                    text = ' '.join(x.text for x in lines if x.confidence >= .8).lower()
                    if 'planets' in text and 'fleet' in text and 'alliance' in text:
                        entered = True
                        continue
                    if 'enter' in text and 'updates' in text:
                        # Splash has a semantic button; use it instead of guessed coordinates.
                        await click_control(page,r'^\s*enter\s*$')
                    elif 'start' in text and ('orion' in text or 'email' in text):
                        fields = await onscreen(page,'input:visible:disabled',hit_test=False)
                        server = await onscreen(page,page.get_by_role('button', name=re.compile('EV-T ORION 1',re.I)))
                        if len(fields) != 1 or len(server) != 1:
                            raise RuntimeError('Account or universe could not be verified on the entry screen')
                        shown = await fields[0].input_value()
                        if shown.strip().casefold() != account.strip().casefold():
                            raise RuntimeError('The signed-in account differs from the configured account')
                        identity = {'account':account,'universe':'EV-T ORION 1'}
                        status('connecting','Account verified; entering the colony')
                        await click_control(page,r'^\s*start\s*$')
                    status('connecting', 'Waiting for the colony screen',screenshot=str(account_path/'screen.png'))
                    await sleep(2)
                if not entered:
                    raise RuntimeError('Could not verify the colony screen; open the account browser')

                await enable_frame_limit(page)
                controller=PlanController(page,ocr,account_path,account,profile,status,require_running,identity,progress_path=path/'progress.json')
                try:
                    while True:
                        require_running()
                        await controller.cycle()
                        status(last['state'],last['message'],nextCheck=time.time()+profile['interval'])
                        await sleep(profile['interval'])
                finally:controller.close()
            finally:await browser.close()
    except ScheduledEnd:status('finished','Scheduled end reached; account released')
    except InterruptedError:status('paused','Paused; account released to scanning')
    except Exception as exc:
        message=str(exc) if isinstance(exc,(ExecutionBlocked,UncertainScreen)) or type(exc) is RuntimeError else type(exc).__name__+': '+last.get('message','profile stopped')
        import traceback
        trace=traceback.extract_tb(exc.__traceback__)
        location=next((f'{Path(f.filename).name}:{f.lineno}' for f in reversed(trace) if 'eog_automation' in f.filename),'')
        status('error',message,diagnostic=location)
    finally:
        if lock:
            # Browser cleanup has completed before the scanner can resume.
            if read_json(claim,{}).get('profileId')==profile_id:claim.unlink(missing_ok=True)
            lock.close()
        service.db.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--profile',required=True)
    asyncio.run(run(parser.parse_args().profile))
