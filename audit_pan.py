"""Bounded read-only UI audit of map pan coverage using an unused account."""
import argparse
import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright
from ev_assistant.__main__ import Reader, load_config, ROOT
from ev_assistant.audit_account import add_account_argument, resolve_account

async def main(args):
    config = load_config(ROOT / 'config.json')
    account, profile = resolve_account(ROOT, config, args.account)
    output = ROOT / 'data' / 'coverage-audit'
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
            await reader.open_map_coordinate(page, [3, 220, 1])
            await reader.force_edge(page, -1)
            frames = []
            for index in range(15):
                lines, image = await reader.observe(page)
                (output / f'pan-{index:02d}.png').write_bytes(image)
                labels = [{'text': line.text, 'x': line.x, 'y': line.y,
                           'confidence': line.confidence} for line in lines
                          if 130 <= line.y <= 760]
                frames.append(labels)
                (output / 'pan-labels.json').write_text(json.dumps(frames, ensure_ascii=True, indent=2))
                print(json.dumps({'frame': index, 'labels': labels}), flush=True)
                await page.mouse.move(350, 650)
                await page.mouse.down()
                await page.mouse.move(300, 650, steps=8)
                await page.mouse.up()
                await asyncio.sleep(.8)
        finally:
            await context.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_account_argument(parser)
    asyncio.run(main(parser.parse_args()))
