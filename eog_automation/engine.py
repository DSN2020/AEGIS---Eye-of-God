"""Persistent ordered plans over the verified visible-screen controller."""
import time
from .live import Controller, affordable
from . import evo_screen as screen
from .executor import ExecutionBlocked
from .storage import atomic_json, read_json
from .model import timestamp

class ScheduledEnd(InterruptedError): pass

class PlanController(Controller):
    def __init__(self,*args,progress_path,**kwargs):
        super().__init__(*args,**kwargs)
        self.progress_path=progress_path
        self.progress=read_json(progress_path,{'index':0,'entered':None,'alerts':{}})
    def save_progress(self): atomic_json(self.progress_path,self.progress)
    def update(self,message):
        self.observations['observed_at']=time.time()
        atomic_json(self.path/'live-observations.json',self.observations)
        self.status('watching' if self.profile['mode']=='watch' else 'running',message,
            step=self.progress['index'],total=len(self.profile['steps']),screenshot=str(self.path/'screen.png'),
            balance=self.observations.get('balance',{}),safeRuns=self.observations.get('safe_runs'))
    def advance(self):
        self.progress['index']+=1;self.progress['entered']=None;self.save_progress()
    def watch(self,balance):
        for index,rule in enumerate(self.profile['rules']):
            if rule['metric']=='safe_runs':continue
            interval=balance['energy'] if rule['metric']=='energy' else balance['stock'][rule['metric']]
            hit=interval['high']<=rule['value'] if rule['op']=='<=' else interval['low']>=rule['value']
            key=str(index);last=self.progress['alerts'].get(key,0)
            if hit and time.time()-last>=rule['cooldown']:
                self.record(f"Watch: {rule['metric']} {rule['op']} {rule['value']:g}",{'kind':'alert',**rule})
                self.progress['alerts'][key]=time.time();self.save_progress()
    async def watch_nebula(self):
        from .nebula import safe_runs, use_gamma
        rules=[(i,r) for i,r in enumerate(self.profile['rules']) if r['metric']=='safe_runs']
        if not rules:return
        observed=await safe_runs(self)
        for index,rule in rules:
            hit=observed['available']<=rule['value'] if rule['op']=='<=' else observed['available']>=rule['value']
            key=str(index)
            if not hit or time.time()-self.progress['alerts'].get(key,0)<rule['cooldown']:continue
            if rule['action']=='use_gamma' and self.profile['mode']!='watch':
                if self.journal.count_recent(self.account,self.profile['universe'],'use_gamma')>=self.profile['gamma_limit']:
                    self.record('Owned Gamma rule reached its per-account 24-hour limit',{'kind':'alert'})
                elif await use_gamma(self,observed):
                    self.progress['alerts'][key]=time.time();self.save_progress();return
                else:self.record('Safe runs exhausted; no owned Gamma Detectors available',{'kind':'alert'})
            else:
                suffix='; Watch mode will not use an item' if rule['action']=='use_gamma' else ''
                self.record(f"Safe runs: {observed['available']}/{observed['limit']}"+suffix,{'kind':'alert'})
            self.progress['alerts'][key]=time.time();self.save_progress()

    async def acquire_upgrade(self,step):
        if step['kind']=='building':
            parser=lambda lines:screen.building(lines,step['name'])
            return await self.open_building(step['name']),parser
        lab=await self.open_building('Research Lab')
        if lab['busy']: return None,None
        await self.click((122,210))
        tab=next(tab for tab,names in screen.TECHS.items() if step['name'] in names)
        await self.click((85 if tab=='Basic' else 235,127))
        if screen.TECHS[tab].index(step['name']) == 3:
            await self.page.mouse.move(150,770);await self.page.mouse.down()
            await self.page.mouse.move(150,480,steps=15);await self.page.mouse.up()
            await self.pause(1)
        parser=lambda lines:screen.tech_card(lines,tab,step['name'])
        return await self.stable(parser),parser
    async def run_step(self,balance):
        index=self.progress['index'];steps=self.profile['steps']
        if index>=len(steps):
            self.update('Plan complete; continuing scheduled watch checks');return
        step=steps[index]
        if self.progress.get('entered') is None:
            self.progress['entered']=time.time();self.save_progress()
        if step['kind']=='wait':
            remaining=self.progress['entered']+step['value']-time.time()
            if remaining<=0:self.advance();self.update('Wait finished')
            else:self.update(f'Waiting {remaining:.0f} more seconds')
            return
        if step['kind']=='resource':
            if balance['stock'][step['name']]['low']>=step['value']:
                self.advance();self.update('Resource target reached')
            else:self.update(f"Waiting for {step['value']:g} {step['name']}")
            return
        action,parser=await self.acquire_upgrade(step)
        if action is None:self.update('Research Lab is busy; waiting');return
        if action['level']>=step['value']:
            self.advance();self.update(f"{step['name']} target level reached");await self.home();return
        if action['busy']:
            self.update(f"Waiting for {step['name']} to finish");await self.home();return
        try: affordable(action,balance,self.profile)
        except ExecutionBlocked as exc:
            self.update('Waiting: '+str(exc));await self.home();return
        await self.purchase(action,balance,parser)
        # Leave the index in place until a later read observes the completed level.
        await self.home()
    async def cycle(self):
        if self.profile['mode']!='watch' and self.journal.unresolved(self.account,self.profile['universe']):
            raise ExecutionBlocked('An earlier action has an unknown result. Check it in game before resuming')
        await self.verify_colony()
        await self.watch_nebula()
        balance=await self.home();self.watch(balance)
        if self.profile['mode']=='watch':self.update('Watch check complete');return
        if self.profile['mode']=='auto' and balance['energy']['low']<self.profile['energy_margin']:
            action=await self.open_building('Solar Plant')
            if action['busy']:self.update('Waiting for the Solar Plant to finish');await self.home();return
            if action['level']>=self.profile['solar_level_limit']:
                self.update('Solar ceiling reached; adjust Auto settings to restore more power');await self.home();return
            try:affordable(action,balance,self.profile)
            except ExecutionBlocked as exc:self.update('Waiting: '+str(exc));await self.home();return
            await self.purchase(action,balance,lambda lines:screen.building(lines,'Solar Plant'))
            await self.home();return
        await self.run_step(balance)
