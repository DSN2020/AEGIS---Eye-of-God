"""Safe-run observations and owned Gamma use through verified UI dialogs."""
import asyncio
import time
from . import evo_screen as screen
from .executor import ExecutionBlocked

async def safe_runs(controller):
    from ev_assistant.__main__ import Reader
    c=controller
    await c.home()
    reader=Reader.__new__(Reader)
    reader.config={'ocr_confidence':.9};reader.ocr=c.ocr;reader.ocr_lock=asyncio.Lock()
    reader.data=c.path;reader.check_stop=c.check_stop;reader.map_snapshot=None;reader.ocr_cache={}
    await reader.open_map(c.page)
    galaxy,system,_=map(int,c.profile['coordinate'].split(':'))
    await reader.open_map_coordinate(c.page,(galaxy,system,21))
    await reader.set_coordinate(c.page,381,21);await c.click((296,85))
    value=await c.stable(lambda lines:screen.nebula(lines,c.profile['coordinate']))
    c.observations['safe_runs']=value
    await c.click((235,190));await c.click((128,857))
    target=await c.stable(lambda lines:screen.colony_return(lines,c.profile['coordinate']))
    await c.click(target['button']);await c.verify_colony()
    return value

async def prepare_gamma(c):
    await c.home();await c.click((344,857))
    inventory=await c.stable(screen.gamma_store)
    if inventory['owned']<1:
        await c.home();return None
    await c.click(inventory['button'])
    quantity=await c.stable(screen.gamma_quantity)
    await c.click(quantity['button'])
    confirmation=await c.stable(screen.gamma_confirmation)
    return inventory,confirmation

async def use_gamma(c, observed):
    if observed['available']!=0 or time.time()-observed['observed_at']>90:
        raise ExecutionBlocked('Gamma needs a fresh zero-safe-runs observation')
    prepared=await prepare_gamma(c)
    if prepared is None:return False
    inventory,confirmation=prepared
    if time.time()-observed['observed_at']>90:
        raise ExecutionBlocked('Safe-run observation expired before Gamma confirmation')
    await c.stable(screen.gamma_confirmation)
    action={'kind':'use_gamma','name':'Gamma Detector','quantity':1,'before_owned':inventory['owned']}
    c.check_stop()
    key=c.journal.begin({'account':c.account,'universe':c.profile['universe']},action)
    try:
        await c.click(confirmation['button'])
        after=await c.stable(screen.gamma_store)
        if after['owned']!=inventory['owned']-1:raise ExecutionBlocked('Gamma inventory change is uncertain; inspect the game before resuming')
        await c.home()
        counter=await safe_runs(c)
        if counter['available']<=0:raise ExecutionBlocked('Gamma safe-run restoration could not be confirmed')
        c.journal.finish(key,'confirmed')
        c.record('Used one owned Gamma Detector; safe runs restored',action)
        return True
    except BaseException:
        c.journal.finish(key,'uncertain');raise
