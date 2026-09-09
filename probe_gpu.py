import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

async def main():
    results=[]
    async with async_playwright() as p:
        for label,args in [('default',[]),('hardware',['--enable-gpu','--use-angle=d3d11'])]:
            browser=await p.chromium.launch(headless=True,
                executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',args=args)
            try:
                cdp=await browser.new_browser_cdp_session()
                info=(await cdp.send('SystemInfo.getInfo'))['gpu']
                result={'mode':label,'devices':info['devices'],
                        'renderer':info.get('auxAttributes',{}).get('glRenderer'),
                        'features':info.get('featureStatus',{})}
                results.append(result)
                print(json.dumps(result),flush=True)
            finally:
                await browser.close()
    Path('data/gpu-probe.json').write_text(json.dumps(results,indent=2))

asyncio.run(main())
