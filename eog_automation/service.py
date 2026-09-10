"""Local profile persistence and independent workers; no credentials in profiles."""
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from .model import validate, preset, timestamp
from .storage import atomic_json, read_json

def account_key(account):
    return hashlib.sha256(account.strip().casefold().encode()).hexdigest()[:24]

def reserved_accounts(data):
    directory=Path(data)/'automation'/'reservations'
    names=set()
    for path in directory.glob('*.json'):
        try:
            value=read_json(path,{})
            if value.get('account'): names.add(value['account'].casefold())
        except (OSError,ValueError):
            # A damaged claim must not allow a second controller onto the account.
            raise RuntimeError('An automation account reservation cannot be read')
    return names

class AccountLock:
    def __init__(self,path):
        path.parent.mkdir(parents=True,exist_ok=True)
        self.file=path.open('a+b'); self.file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.file.close(); raise RuntimeError('This account already has an automation worker')
    def close(self): self.file.close()
    def __enter__(self): return self
    def __exit__(self,*args): self.close()

class Service:
    def __init__(self,root):
        self.root=Path(root); self.data=self.root/'data'/'automation'
        self.data.mkdir(parents=True,exist_ok=True)
        self.db=sqlite3.connect(self.data/'profiles.sqlite',timeout=10)
        self.db.execute('CREATE TABLE IF NOT EXISTS profiles(id TEXT PRIMARY KEY, document TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS presets(name TEXT PRIMARY KEY, document TEXT NOT NULL)')
        self.db.commit()
    def path(self,p):
        path=self.data/'profiles'/p['id'];path.mkdir(parents=True,exist_ok=True);return path
    def account_path(self,p):
        path=self.data/'accounts'/account_key(p['account']);path.mkdir(parents=True,exist_ok=True);return path
    def claim(self,p,scheduled=False): return self.data/('scheduled' if scheduled else 'reservations')/(account_key(p['account'])+'.json')
    def existing_claim(self,p): return self.claim(p) if self.claim(p).exists() else self.claim(p,scheduled=True)
    def get(self,id):
        row=self.db.execute('SELECT document FROM profiles WHERE id=?',(id,)).fetchone()
        if not row: raise ValueError('Select a saved profile')
        return json.loads(row[0])
    def active(self,p): return self.claim(p).exists() or self.claim(p,scheduled=True).exists()
    def save(self,raw):
        p=validate(raw)
        old=self.db.execute('SELECT document FROM profiles WHERE id=?',(p['id'],)).fetchone()
        if old and self.active(json.loads(old[0])): raise ValueError('Pause this account’s profile before editing it')
        config=read_json(self.root/'config.json',{})
        configured={n.casefold():n for n in config.get('sweep',{}).get('account_profiles',[])}
        if p['account'].casefold() not in configured:
            raise ValueError('Save the account in Agents & accounts first')
        p['account']=configured[p['account'].casefold()]
        if not old or json.loads(old[0]).get('steps')!=p['steps']:
            atomic_json(self.path(p)/'progress.json',{'index':0,'entered':None,'alerts':{}})
        self.db.execute('INSERT OR REPLACE INTO profiles VALUES (?,?)',(p['id'],json.dumps(p)));self.db.commit()
        atomic_json(self.path(p)/'profile.json',p)
        return p
    def start(self,id):
        p=validate(self.get(id))
        from ev_assistant.credentials import load_passwords
        if not load_passwords(self.root/'data',p['account']): raise ValueError('Save this account’s password in Agents & accounts first')
        from app_bridge import ApplicationBridge
        # Only a supervisor that understands claims may run beside automation.
        probe=ApplicationBridge(self.root)
        if probe.running() and not read_json(self.root/'data'/'sweep-status.json',{}).get('accountReservationsSupported'):
            raise ValueError('The scanner needs one pause/resume to load account handoff support')
        start_at=timestamp(p.get('startAt'))
        claim=self.claim(p,scheduled=start_at is not None and start_at>time.time());claim.parent.mkdir(parents=True,exist_ok=True)
        with AccountLock(self.account_path(p)/'worker.lock'):
            if self.active(p): raise ValueError('This account is already reserved. Pause its profile first')
            atomic_json(claim,{'account':p['account'],'profileId':p['id'],'created':time.time()})
        path=self.path(p);(path/'STOP').unlink(missing_ok=True)
        atomic_json(path/'status.json',{'state':'starting','message':'Waiting for the account handoff','updated':time.time()})
        try:
            with (path/'worker.log').open('a',encoding='utf-8') as out:
                subprocess.Popen([sys.executable,'-u','-m','eog_automation.worker','--profile',p['id']],cwd=self.root,
                    stdout=out,stderr=out,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        except Exception:
            claim.unlink(missing_ok=True);raise RuntimeError('Could not start automation worker')
        return {'message':'Profile starting; other scanner accounts keep running'}
    def pause(self,id):
        p=self.get(id);path=self.path(p);(path/'STOP').touch()
        claim=self.existing_claim(p); owner=read_json(claim,{})
        if owner and owner.get('profileId')!=id: raise ValueError('Another profile owns this account; pause that profile')
        try:
            with AccountLock(self.account_path(p)/'worker.lock'):
                # A freshly launched worker may not have acquired its lock yet.
                if owner and time.time()-owner.get('created',0)<15:
                    return {'message':'Pause requested; waiting for startup to close'}
                claim.unlink(missing_ok=True)
                atomic_json(path/'status.json',{'state':'paused','message':'Paused; scanner may resume this account','updated':time.time()})
        except RuntimeError: pass
        return {'message':'Pause requested; the account returns to scanning after its browser closes'}
    def snapshot(self):
        profiles=[]
        for row in self.db.execute('SELECT document FROM profiles ORDER BY rowid'):
            p=json.loads(row[0]);path=self.path(p)
            status=read_json(path/'status.json',{'state':'paused','message':'Ready to configure and start'})
            own=read_json(self.existing_claim(p),{}).get('profileId')==p['id']
            if own and time.time()-status.get('updated',0)>180:
                status={**status,'state':'unresponsive','message':'No recent worker update; pause before restarting'}
            activity=[]
            log=self.account_path(p)/'live-activity.jsonl'
            if log.exists():
                with log.open('rb') as f:
                    f.seek(max(0,log.stat().st_size-16000))
                    for line in f.read().decode('utf-8',errors='replace').splitlines():
                        try: activity.append(json.loads(line))
                        except ValueError: pass
            profiles.append({'profile':p,'status':status,'reserved':own,
                'progress':read_json(path/'progress.json',{}),'activity':activity[-30:][::-1]})
        return {'profiles':profiles,'presets':[json.loads(r[0]) for r in self.db.execute('SELECT document FROM presets ORDER BY name')],
            'buildings':list(__import__('eog_automation.evo_screen',fromlist=['BUILDINGS']).BUILDINGS),
            'accounts':read_json(self.root/'config.json',{}).get('sweep',{}).get('account_profiles',[])}
    def dispatch(self,request):
        command=request['command'].removeprefix('automation_')
        if command=='snapshot': return self.snapshot()
        if command=='save': return self.save(request['profile'])
        if command=='start': return self.start(request['id'])
        if command=='pause': return self.pause(request['id'])
        if command=='delete':
            p=self.get(request['id'])
            if self.active(p): raise ValueError('Pause the account before deleting its profile')
            self.db.execute('DELETE FROM profiles WHERE id=?',(p['id'],));self.db.commit();return {'message':'Profile deleted'}
        if command=='preset':
            value=preset(self.get(request['id']),request['name'])
            self.db.execute('INSERT OR REPLACE INTO presets VALUES (?,?)',(value['name'],json.dumps(value)));self.db.commit();return value
        raise ValueError('Unknown automation command')
