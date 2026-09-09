"""Bounded UI-only benchmark of the same 21 slots; no coverage is modified."""
import argparse
import asyncio
from collections import defaultdict
import json
import statistics
import time
from playwright.async_api import async_playwright
from ev_assistant.__main__ import Reader,ROOT,load_config
from ev_assistant.audit_account import add_account_argument, resolve_account
from ev_assistant.slot_verifier import verify_slot

async def main(args):
    config=load_config(ROOT/'config.json')
    account, profile = resolve_account(ROOT, config, args.account)
    output=ROOT/'data'/'efficiency-benchmark'/args.mode
    output.mkdir(parents=True,exist_ok=True)
    reader=Reader(config,output)
    reader.config['sweep']['efficient_slots'] = args.mode != 'baseline'
    reader.config['sweep']['detail_ocr'] = args.mode in ('optimized-details', 'rendered-text')
    reader.config['sweep']['rendered_text'] = args.mode == 'rendered-text'
    async with async_playwright() as p:
        context=await p.chromium.launch_persistent_context(
            str(profile),headless=True,
            executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe',
            viewport=config['viewport'],device_scale_factor=1)
        try:
            if args.mode!='baseline':
                from ev_assistant.performance import install_frame_limit, enable_frame_limit
                await install_frame_limit(context,20,defer=True)
                reader.config['sweep']['efficient_slots']=True
            page=context.pages[0]
            await page.goto(config['url'],wait_until='domcontentloaded')
            await reader.login_and_enter(page, account)
            if args.mode!='baseline':
                await enable_frame_limit(page)
            await reader.open_map(page)
            await reader.open_map_coordinate(page,(9,57,1))
            reader.timings=defaultdict(float)
            rows=[]
            for position in range(1,22):
                start=time.perf_counter()
                result=await verify_slot(reader,page,9,57,position,output)
                row={'position':position,'seconds':time.perf_counter()-start,'result':result}
                rows.append(row)
                print(json.dumps(row),flush=True)
                (output/'progress.json').write_text(json.dumps(rows,indent=2))
            seconds=sum(x['seconds'] for x in rows)
            result={'mode':args.mode,'slots':len(rows),'seconds':seconds,
                    'mean_slot_seconds':seconds/len(rows),
                    'median_slot_seconds':statistics.median(x['seconds'] for x in rows),
                    'timings':dict(reader.timings),'observations':rows}
            (output/'result.json').write_text(json.dumps(result,indent=2))
            print(json.dumps({k:v for k,v in result.items() if k!='observations'}),flush=True)
        finally:
            await context.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['baseline','optimized','optimized-details','rendered-text'])
    add_account_argument(parser)
    asyncio.run(main(parser.parse_args()))
