"""Confirm a user-provided missing coordinate through the visible game UI."""
import argparse
import asyncio
import json
from playwright.async_api import async_playwright
from ev_assistant.__main__ import Reader, load_config, ROOT, export_players
from ev_assistant.audit_account import add_account_argument, resolve_account
from ev_assistant.store import Store, Planet

async def main(args):
    config = load_config(ROOT / 'config.json')
    account, profile = resolve_account(ROOT, config, args.account)
    output = ROOT / 'data' / 'known-player-audit'
    output.mkdir(exist_ok=True)
    reader = Reader(config, output)
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            str(profile), headless=True,
            executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            viewport=config['viewport'], device_scale_factor=1)
        try:
            page = context.pages[0]
            await page.goto(config['url'], wait_until='domcontentloaded')
            await reader.login_and_enter(page, account)
            print('Logged in', flush=True)
            await reader.open_map(page)
            await reader.open_map_coordinate(page, [9, 57, 14])
            for x, value in zip((89, 235, 381), (9, 57, 14)):
                await reader.set_coordinate(page, x, value)
            await page.mouse.click(296, 85)
            await asyncio.sleep(3)
            previous = None
            for attempt in range(8):
                lines, image = await reader.observe(page)
                (output / '9-57-14.png').write_bytes(image)
                detail = reader.popup_details(lines, 9, 57)
                if detail and detail == previous and detail[0] == (9,57,14):
                    store = Store(ROOT / 'data' / 'observations.sqlite')
                    store.record_sighting(config['universe'], 9, 57, Planet(14, detail[1], ''))
                    (output / 'confirmation.json').write_text(json.dumps(detail))
                    print(json.dumps({'confirmed': detail}), flush=True)
                    return
                previous = detail
                await asyncio.sleep(.75)
            raise RuntimeError('Unable to confirm requested owner; inspect saved screenshot')
        finally:
            await context.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_account_argument(parser)
    asyncio.run(main(parser.parse_args()))
