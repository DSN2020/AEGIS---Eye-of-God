"""Exercise requestAnimationFrame timing/cancellation in a real blank browser."""
import asyncio
import json
from playwright.async_api import async_playwright
from ev_assistant.performance import install_frame_limit, enable_frame_limit

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True,
            executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
        try:
            context = await browser.new_context()
            await install_frame_limit(context,20,defer=True)
            page = await context.new_page()
            await enable_frame_limit(page)
            result = await page.evaluate('''() => new Promise(resolve => {
              let cancelled = false, frames = [];
              cancelAnimationFrame(requestAnimationFrame(() => cancelled = true));
              let later;
              requestAnimationFrame(() => cancelAnimationFrame(later));
              later = requestAnimationFrame(() => cancelled = true);
              function frame(t) {
                frames.push(t);
                if (frames.length < 15) requestAnimationFrame(frame);
                else resolve({cancelled, frames, now: performance.now()});
              }
              requestAnimationFrame(frame);
            })''')
            differences = [b-a for a,b in zip(result['frames'],result['frames'][1:])]
            assert not result['cancelled']
            assert min(differences) >= 49
            assert 0 <= result['now']-result['frames'][-1] < 1000
            print(json.dumps({'passed':True,'minimum_interval_ms':min(differences),
                              'callbacks':len(result['frames']),'cancellation':True}))
        finally:
            await browser.close()

asyncio.run(main())
