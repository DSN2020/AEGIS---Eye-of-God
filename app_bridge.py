"""Private stdin/stdout bridge for EOG. No HTTP listener."""
import hashlib
import json
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from ev_assistant.limits import MAX_AGENTS
from ev_assistant.store import Store
from ev_assistant.credentials import load_passwords, save_passwords
from isolated_supervisor import atomic_json

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'

def recent_activity(path, account):
    """Keep timestamped messages together and give polling clients stable IDs."""
    if not path.exists():
        return []
    with path.open('rb') as handle:
        offset = max(0, path.stat().st_size-16000)
        handle.seek(offset)
        if offset:
            handle.readline()  # Never expose a cut-off first line.
        lines = handle.read().decode('utf-8', errors='replace').splitlines()
    events = []
    for line in lines:
        match = re.match(r'^(\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d(?:[.,]\d+)?(?:[+-]\d\d:\d\d)?)\s+(.*)', line)
        if match:
            try:
                timestamp = datetime.fromisoformat(match[1].replace(',', '.')).timestamp()
            except ValueError:
                continue
            events.append({'account':account, 'timestamp':timestamp, 'text':match[2]})
        elif line.strip() and events:
            events[-1]['text'] += '\n' + line
    for event in events:
        identity = f"{account}\0{event['timestamp']}\0{event['text']}"
        event['id'] = hashlib.sha256(identity.encode('utf-8')).hexdigest()
    return events[-22:]

def startup_progress(worker, events, now=None):
    """Describe observed milestones from this launch, never a previous session."""
    starts=[i for i,e in enumerate(events) if e['text'].startswith('START ')]
    if not starts:
        return None
    session=events[starts[-1]:]
    started=session[0]['timestamp']
    if worker.get('state')=='starting':
        elapsed=max(0,int((time.time() if now is None else now)-started))
        signed_in=any('Scanner animation limit:' in event['text'] for event in session)
        phase='Signed in; opening the galaxy map' if signed_in else 'Loading game and signing in'
        worker['detail']=f'{phase} · {elapsed}s since launch'
    return started

class ApplicationBridge:
    def __init__(self, root=ROOT):
        self.root, self.data = Path(root), Path(root)/'data'
        self.store = Store(self.data/'observations.sqlite')

    def read(self, path, default):
        for attempt in range(4):
            try:
                return json.loads(path.read_text(encoding='utf-8-sig'))
            except (OSError, ValueError):
                time.sleep(.02)
        return default

    def running(self):
        probe = socket.socket()
        try:
            probe.bind(('127.0.0.1',47682))
            return False
        except OSError:
            return True
        finally:
            probe.close()

    def settings(self):
        config = self.read(self.root/'config.json', {})
        names = config.get('sweep',{}).get('account_profiles',[])
        return {'workerCount':config.get('sweep',{}).get('workers',4),
            'accounts':[{'username':name,'hasPassword':bool(load_passwords(self.data,name))}
                        for name in names], 'running':self.running()}

    def validate_settings(self, request):
        count = request.get('workerCount')
        accounts = request.get('accounts',[])
        if type(count) is not int or not 1 <= count <= MAX_AGENTS:
            raise ValueError(f'Choose between 1 and {MAX_AGENTS} agents.')
        if not count <= len(accounts) <= MAX_AGENTS:
            raise ValueError('Add one account for every active agent.')
        names = [str(a.get('username','')).strip() for a in accounts]
        if any(not name for name in names[:count]):
            raise ValueError('Every active agent needs a username.')
        nonempty = [n.casefold() for n in names if n]
        if len(nonempty) != len(set(nonempty)):
            raise ValueError('Use a different account for each agent.')
        for index in range(count):
            if not accounts[index].get('password') and not load_passwords(self.data,names[index]):
                raise ValueError(f'Enter a password for agent {index+1}.')
        return count, accounts, names

    def save_settings(self, request):
        count, accounts, names = self.validate_settings(request)
        config = self.read(self.root/'config.json',{})
        profiles = config.setdefault('browser_profiles',{})
        for index, old in enumerate(config['sweep']['account_profiles']):
            profiles.setdefault(old.casefold(), 'browser-profile' if index == 0
                                else f'browser-profile-account-{index}')
        for account, name in zip(accounts,names):
            if not name:
                continue
            profiles.setdefault(name.casefold(), 'browser-account-'+hashlib.sha256(name.casefold().encode()).hexdigest()[:16])
            if account.get('password'):
                save_passwords(self.data,name,[account['password']])
        config['sweep'].update(workers=count, account_profiles=[n for n in names if n],
                               verification_mode='explicit-slots-v1')
        if not atomic_json(self.root/'config.json',config):
            raise RuntimeError('Could not save settings. Try again.')
        return {'message':'Accounts saved. Passwords are protected by Windows.'}

    def stop(self):
        (self.data/'STOP').touch()
        deadline = time.monotonic()+30
        while self.running() and time.monotonic()<deadline:
            time.sleep(.25)
        if self.running():
            raise RuntimeError('The scanner is still stopping. Wait a moment and try again.')
        return {'message':'Scan paused. Confirmed slots and coordinates are saved.'}

    def set_worker_count(self, count):
        settings = self.settings()
        self.validate_settings({'workerCount':count,'accounts':settings['accounts']})
        config = self.read(self.root/'config.json',{})
        config['sweep']['workers'] = count
        if not atomic_json(self.root/'config.json',config):
            raise RuntimeError('Could not save the agent count. Try again.')
        return {'message':f'Applying {count} agents using saved accounts.' if settings['running']
                else f'{count} agents selected. Resume scan to start them.'}

    def start(self):
        if self.running():
            return {'message':'The scanner is already running.'}
        settings = self.settings()
        self.validate_settings(settings)
        (self.data/'STOP').unlink(missing_ok=True)
        with (self.data/'desktop-supervisor.log').open('a',encoding='utf-8') as log:
            subprocess.Popen([sys.executable,'-u','sweep_supervisor.py'],cwd=self.root,
                stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        return {'message':'Starting agents from their saved checkpoints.'}

    def snapshot(self):
        status = self.read(self.data/'sweep-status.json',{})
        running = self.running()
        settings = self.settings()
        status['requestedWorkers'] = settings['workerCount']
        status['workerCountPending'] = running and status.get('expectedWorkers') != settings['workerCount']
        if not running:
            status['state'] = 'complete' if status.get('state')=='complete' else 'paused'
            status['activeWorkers'] = 0
        elif time.time() - (self.data/'sweep-status.json').stat().st_mtime > 30:
            status['state'] = 'unresponsive'
        profiles = {(r['universe'],r['player'].casefold()):r for r in self.store.profiles()}
        grouped = {}
        for row in self.store.search():
            if re.match(r'^bot_',row['player'],re.I):
                continue
            key = (row['universe'],row['player'].casefold())
            profile = profiles.get(key)
            player = grouped.setdefault(key,{'name':row['player'],
                'alliance':profile['alliance'] if profile else None,
                'allianceObserved':profile['observed'] if profile else None,
                'coordinates':[], 'observed':row['observed']})
            player['coordinates'].append(f"{row['galaxy']}:{row['system']}:{row['position']}")
            player['observed'] = max(player['observed'],row['observed'])
        players = sorted(grouped.values(),key=lambda p:(-p['observed'],p['name'].casefold()))
        workers, activity = [], []
        for key, worker in status.get('workers',{}).items():
            worker = dict(worker, id=int(key))
            if not running:
                worker['state'] = 'paused'
            path = self.data/f'worker-{key}.log'
            events=recent_activity(path,worker.get('account','Agent '+key))
            started=startup_progress(worker,events)
            frame = self.data/'galaxies'/str(worker.get('galaxy'))/'live-frame.png'
            frame_time=frame.stat().st_mtime if frame.exists() else 0
            fresh=bool(frame_time) and (not running or started is None or frame_time>=started)
            worker['framePath'] = str(frame) if fresh else ''
            worker['frameUpdated'] = frame_time if fresh else 0
            workers.append(worker)
            activity.extend(events)
        activity.sort(key=lambda event:(-event['timestamp'],event['id']))
        logs = [f"[{event['account']}] {datetime.fromtimestamp(event['timestamp']).isoformat(' ',timespec='milliseconds')} {event['text']}" for event in activity]
        return {'status':status,'workers':workers,'players':players,
            'logs':'\n'.join(logs), 'activity':activity, 'settings':settings, 'updated':time.time(),
            'playerCount':len(players),'coordinateCount':sum(len(p['coordinates']) for p in players),
            'allianceCount':len({p['alliance'] for p in players if p['alliance']})}

    def dispatch(self, request):
        command = request.get('command')
        if isinstance(command,str) and command.startswith('automation_'):
            from eog_automation.service import Service
            service=Service(self.root)
            try: return service.dispatch(request)
            finally: service.db.close()
        if command == 'snapshot': return self.snapshot()
        if command == 'settings': return self.settings()
        if command == 'start': return self.start()
        if command == 'stop': return self.stop()
        if command == 'save': return self.save_settings(request)
        if command == 'set_worker_count': return self.set_worker_count(request.get('workerCount'))
        if command == 'apply':
            self.validate_settings(request)
            saved_names = [a['username'] for a in self.settings()['accounts']]
            if [a.get('username','').strip() for a in request['accounts'] if a.get('username','').strip()] == saved_names and not any(a.get('password') for a in request['accounts']):
                return self.set_worker_count(request['workerCount'])
            running = self.running()
            if running: self.stop()
            self.save_settings(request)
            if running: self.start()
            return {'message':'Agent settings applied. Saved progress retained.'}
        if command == 'restart_worker':
            index = request.get('index')
            if type(index) is not int or not 1 <= index <= self.settings()['workerCount']:
                raise ValueError('Select an active agent.')
            if not self.running(): raise ValueError('Resume the scan first.')
            if not atomic_json(self.data/'worker-command.json',{'action':'restart','index':index}):
                raise RuntimeError('Could not request an agent restart.')
            return {'message':f'Restarting agent {index}; other agents continue.'}
        raise ValueError('Unknown application command.')

if __name__ == '__main__':
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    bridge = ApplicationBridge()
    for raw in sys.stdin:
        try:
            result = bridge.dispatch(json.loads(raw))
            response = {'ok':True,'result':result}
        except (ValueError, RuntimeError) as exc:
            response = {'ok':False,'error':str(exc)}
        except Exception:
            response = {'ok':False,'error':'Could not complete the operation. Check the scanner activity and try again.'}
        print(json.dumps(response,ensure_ascii=True),flush=True)
