"""Verified EVO power restoration and research milestones through visible UI.

This controller is intentionally limited to the observed 470x912 colony layout.
Every navigation target is checked by OCR before any purchase can be issued.
"""
import asyncio
import json
import os
import time
from . import evo_screen as screen
from .executor import Journal, ExecutionBlocked
from .storage import atomic_json
from .vision import UncertainScreen



def signature(item):
    return json.dumps({k:v for k,v in item.items() if k not in ('seconds','observed_at')}, sort_keys=True)


def affordable(action, balance, profile):
    for r in screen.RESOURCES:
        cost = action['cost'][r]['high']
        if cost < 0 or cost > profile['max_upgrade_cost']:
            raise ExecutionBlocked('Upgrade exceeds the configured per-resource limit')
        if balance['stock'][r]['low'] - cost < profile['reserves'].get(r, 0):
            raise ExecutionBlocked(f'Upgrade would use the {r} reserve')


class Controller:
    def __init__(self, page, ocr, path, account, profile, status, check_stop, verified_identity):
        self.page, self.ocr, self.path, self.account = page, ocr, path, account
        self.profile, self.status, self.check_stop = profile, status, check_stop
        self.identity = verified_identity
        self.journal = Journal(path / 'live-actions.sqlite')
        self.observations = {'account': account, 'universe': profile['universe'],
            'coordinate': profile['coordinate'], 'buildings': {}, 'research': {}, 'complete_economy': False}

    def close(self):
        self.journal.close()

    async def pause(self, seconds):
        for _ in range(max(1, int(seconds * 5))):
            self.check_stop()
            await asyncio.sleep(.2)

    async def read(self, force_ocr=False):
        self.check_stop()
        if self.page.url.rstrip('/') != 'https://eternal-void.online':
            raise ExecutionBlocked('Browser is not on the configured EVO game')
        if await self.page.locator('input[type="password"]:visible').count():
            raise ExecutionBlocked('EVO session expired')
        image = await self.page.screenshot()
        from .rendered import read_controls
        lines = None if force_ocr else await read_controls(self.page)
        if lines is None: lines = await asyncio.to_thread(self.ocr.read, image)
        # Small red minus signs can disappear in OCR. On the colony screen,
        # read resource text directly from the visible rendered header instead.
        labels=screen.text(screen.region(lines,80,815,465,911)).lower()
        if all(word in labels for word in ('planets','fleet','alliance')):
            from ev_assistant.rendered_text import read_rendered_text
            rendered=await read_rendered_text(self.page,{'x':0,'y':50,'width':470,'height':52})
            if rendered is None:
                raise UncertainScreen('The visible resource header is unreadable; energy sign cannot be verified')
            lines=[line for line in lines if not 50<=line.y<=102]+rendered[1]
        if any('password' in line.text.casefold() for line in lines):
            raise ExecutionBlocked('Login screen detected')
        temporary = self.path / 'screen.tmp'
        temporary.write_bytes(image)
        os.replace(temporary, self.path / 'screen.png')
        atomic_json(self.path / 'ocr.json', {'observed_at': time.time(), 'lines': [vars(x) for x in lines]})
        return lines

    def update(self, message):
        self.observations['observed_at'] = time.time()
        atomic_json(self.path / 'live-observations.json', self.observations)
        self.status('managing', message, screenshot=str(self.path/'screen.png'),
                    calibrated=True, auto_manage=True, scope='power-and-research')

    async def stable(self, parser, timeout=35):
        deadline, prior = time.monotonic()+timeout, None
        error = 'Screen did not stabilize'
        while time.monotonic() < deadline:
            self.check_stop()
            try:
                try: item = parser(await self.read())
                except UncertainScreen: item = parser(await self.read(force_ocr=True))
                current = signature(item)
                if current == prior:
                    item['observed_at'] = time.time()
                    return item
                prior = current
            except UncertainScreen as problem:
                prior, error = None, str(problem)
            await self.pause(.6)
        raise UncertainScreen(error)

    async def click(self, point):
        self.check_stop()
        await self.page.mouse.click(*point)
        await self.pause(.8)

    async def home(self):
        for _ in range(5):
            lines = await self.read()
            title = screen.text(screen.region(lines,100,10,375,58)).strip()
            if title in screen.BUILDINGS or title in ('Tech Description','Planets','Store'):
                await self.click((46,30))
                continue
            try:
                try: value = screen.home(lines)
                except UncertainScreen:
                    lines=await self.read(force_ocr=True)
                    value=screen.home(lines)
                value['observed_at'] = time.time()
                self.observations.update(balance=value)
                return value
            except UncertainScreen:
                title = screen.text(screen.region(lines, 100, 10, 375, 58)).strip()
                if title in screen.BUILDINGS or title in ('Tech Description', 'Planets', 'Store'):
                    await self.click((46,30))
                else:
                    await self.pause(1)
        raise UncertainScreen('Could not return to the verified colony home screen')

    async def verify_colony(self):
        if self.identity.get('account', '').casefold() != self.account.casefold() or self.identity.get('universe') != self.profile['universe']:
            raise ExecutionBlocked('Account/universe was not verified on EVO’s visible login screen')
        if self.page.viewport_size != {'width':470,'height':912}:
            raise ExecutionBlocked('The browser viewport differs from the calibrated layout')
        await self.home()
        await self.click((236,28))
        await self.stable(lambda lines: {'coordinate': screen.planet_identity(lines, self.account, self.profile['coordinate'])})
        await self.click((99,321))
        await self.home()

    async def open_building(self, name):
        await self.home()
        await self.click(screen.BUILDINGS[name])
        value = await self.stable(lambda lines: screen.building(lines, name))
        self.observations['buildings'][name] = value
        return value

    def record(self, message, action):
        with (self.path / 'live-activity.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'time':time.time(),'message':message,'action':action})+'\n')

    async def purchase(self, action, balance, parser):
        # Re-read the exact action immediately before the one permitted click.
        fresh = await self.stable(parser)
        if fresh.get('busy') or signature(fresh) != signature(action):
            raise ExecutionBlocked('The upgrade changed before execution')
        if time.time() - balance['observed_at'] > 90:
            raise ExecutionBlocked('Resource observation is too old')
        affordable(fresh, balance, self.profile)
        state = {'account':self.account,'universe':self.profile['universe']}
        self.check_stop()
        key = self.journal.begin(state, fresh)
        try:
            self.check_stop()
            await self.click(fresh['button'])
            deadline = time.monotonic()+40
            while time.monotonic() < deadline:
                self.check_stop()
                try:
                    result = parser(await self.read())
                    if result['level'] == fresh['level'] + 1 or (result['busy'] and result['level'] == fresh['level']):
                        self.journal.finish(key,'confirmed')
                        self.record(f'Started {fresh["name"]} level {fresh["level"]+1}', fresh)
                        self.update(f'{fresh["name"]} level {fresh["level"]+1} confirmed in game')
                        return
                except UncertainScreen:
                    pass
                await self.pause(1)
            raise ExecutionBlocked('Upgrade result is uncertain; inspect the game before resuming')
        except BaseException:
            self.journal.finish(key,'uncertain')
            raise
