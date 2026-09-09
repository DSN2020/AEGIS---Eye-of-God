"""Calibrate explicit navigation to each planet slot; no fleet actions."""
import argparse
import asyncio
import json
from playwright.async_api import async_playwright
from ev_assistant.__main__ import Reader, load_config, ROOT
from ev_assistant.audit_account import add_account_argument, resolve_account

async def main(args):
    config = load_config(ROOT / 'config.json')
    account, profile = resolve_account(ROOT, config, args.account)
    output = ROOT / 'data' / 'slot-audit'
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
            await reader.open_map(page)
            await reader.open_map_coordinate(page, [9, 57, 1])
            results = []
            for position in range(1, 22):
                await reader.set_coordinate(page, 381, position)
                await page.mouse.click(296, 85)
                await asyncio.sleep(2)
                lines, image = await reader.observe(page)
                (output / f'9-57-{position}.png').write_bytes(image)
                labels = [{'text': x.text, 'x': x.x, 'y': x.y, 'confidence': x.confidence}
                          for x in lines]
                results.append({'position': position, 'lines': labels})
                (output / 'slots.json').write_text(json.dumps(results, indent=2))
                print(json.dumps({'position': position, 'lines': labels}), flush=True)
                await reader.dismiss_popup(page)
        finally:
            await context.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_account_argument(parser)
    asyncio.run(main(parser.parse_args()))
