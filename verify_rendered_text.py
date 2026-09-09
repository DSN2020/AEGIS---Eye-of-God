"""Exercise rendered-text visibility and coordinates in a real browser, offline."""
import asyncio
from playwright.async_api import async_playwright
from ev_assistant.rendered_text import read_rendered_text

FIXTURE = r"""() => {
 const node = (text, x=50, y=130, options={}) => ({
   text, visible:true, renderable:true, alpha:1, children:[],
   getBounds:()=>({x,y,width:40,height:15}), ...options
 });
 const stage = {children:[node('visible'), node('offscreen',600),
   {visible:false,children:[node('hidden')]},
   {mask:{},children:[node('masked')]},
   {alpha:0.6,children:[{alpha:0.6,children:[node('faded')]}]},
   node('ABC',80,150),node('ABC',80.5,150.5)]};
 const renderer={tick:10,canvas:document.querySelector('canvas'),screen:{x:0,y:0,width:235,height:456}};
 window.__PIXI_DEVTOOLS__={stage,renderer};
}"""

async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,
            executable_path=r'C:\Program Files\Google\Chrome\Application\chrome.exe')
        try:
            page=await browser.new_page(viewport={'width':470,'height':912})
            await page.set_content('<style>body{margin:0}canvas{width:470px;height:912px}</style><canvas></canvas>')
            await page.evaluate(FIXTURE)
            clip={'x':25,'y':230,'width':420,'height':450}
            frame,lines=await read_rendered_text(page,clip)
            assert frame==10 and [r.text for r in lines]==['visible','ABC']
            assert lines[0].x==140 and lines[0].y==275
            assert await page.evaluate('() => window.__PIXI_DEVTOOLS__.stage.children.length')==7
            await page.evaluate('() => window.__PIXI_DEVTOOLS__.renderer.tick++')
            assert (await read_rendered_text(page,clip))[0]==11
            await page.evaluate('() => { const d=window.__PIXI_DEVTOOLS__; window.__PIXI_DEVTOOLS__={app:d}; }')
            assert [r.text for r in (await read_rendered_text(page,clip))[1]]==['visible','ABC']
            await page.evaluate('() => { delete window.__PIXI_DEVTOOLS__; }')
            assert await read_rendered_text(page,clip) is None
            print('PASS: browser visibility, inherited opacity, masks, scaling, duplicate outlines, render frames and unavailable-renderer fallback')
        finally:
            await browser.close()

if __name__=='__main__':
    asyncio.run(main())
