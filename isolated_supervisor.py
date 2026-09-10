"""One restartable process per account; checkpoints owned by galaxy."""
import copy
import json
import logging
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from ev_assistant.limits import MAX_AGENTS
from ev_assistant.coverage import sweep_positions
from ev_assistant.shared_browser import SharedBrowserHost
from ev_assistant.store import Store
from ev_assistant.__main__ import export_players

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data'
LOG = logging.getLogger('supervisor')
JSON_CACHE = {}


def stamp():
    return datetime.now().astimezone().isoformat(timespec='seconds')


def read_json(path, default):
    key = str(path.resolve())
    for attempt in range(8):
        try:
            value = json.loads(path.read_text(encoding='utf-8-sig'))
            JSON_CACHE[key] = copy.deepcopy(value)
            return value
        except FileNotFoundError:
            return copy.deepcopy(JSON_CACHE.get(key, default))
        except (PermissionError, json.JSONDecodeError):
            if attempt == 7:
                if key in JSON_CACHE:
                    LOG.warning('Checkpoint temporarily unreadable; retaining last good value: %s', path)
                    return copy.deepcopy(JSON_CACHE[key])
                raise
            time.sleep(.1 * (attempt + 1))


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    for attempt in range(5):
        try:
            temp.write_text(json.dumps(value, indent=2), encoding='utf-8')
            temp.replace(path)
            return True
        except PermissionError:
            time.sleep(.1 * (attempt + 1))
    LOG.warning('File busy; will publish next tick: %s', path.name)
    return False


def coverage_for(data, galaxy):
    job = data / 'galaxies' / str(galaxy)
    return read_json(job / 'coverage.json', {'progress': {}, 'retry_holes': []})


def galaxy_done(data, galaxy, end):
    coverage = coverage_for(data, galaxy)
    return (int(coverage['progress'].get(str(galaxy), 0)) >= end
            and not coverage['retry_holes'])


def pending_galaxies(data, galaxies, end):
    pending = [galaxy for galaxy in galaxies if not galaxy_done(data, galaxy, end)]
    # Visit every unscanned range before cycling through hard-to-read leftovers.
    return sorted(pending, key=lambda galaxy: (
        int(coverage_for(data, galaxy)['progress'].get(str(galaxy), 0)) >= end, galaxy))


def prepare_jobs(data, galaxies):
    progress = read_json(data / 'sweep-progress.json', {})
    holes = read_json(data / 'sweep-retries.json', {'systems': []})['systems']
    for galaxy in galaxies:
        path = data / 'galaxies' / str(galaxy) / 'coverage.json'
        if not path.exists():
            if not atomic_json(path, {
                'progress': {str(galaxy): progress.get(str(galaxy), 0)},
                'retry_holes': [key for key in holes if key.startswith(f'{galaxy}:')],
            }):
                raise RuntimeError('Cannot initialize galaxy coverage')


def prune_completed_holes(data, galaxies, store, config):
    """A missing excluded slot must not keep an old system in the retry queue."""
    required = set(sweep_positions(config))
    for galaxy in galaxies:
        coverage = coverage_for(data, galaxy)
        retained = []
        for key in coverage['retry_holes']:
            g, system = map(int, key.split(':'))
            checked = store.checked_slots(config['sweep']['verification_mode'],
                                          config['universe'], g, system)
            if not required.issubset(checked):
                retained.append(key)
        if retained != coverage['retry_holes']:
            coverage['retry_holes'] = retained
            atomic_json(data / 'galaxies' / str(galaxy) / 'coverage.json', coverage)


def stop_tree(process):
    if process is None or process.poll() is not None:
        return
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25)
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


class Slot:
    def __init__(self, index, config, data=DATA):
        self.index, self.config, self.data = index, config, data
        self.account = config['sweep']['account_profiles'][index]
        self.galaxy = self.process = self.output = None
        self.position = self.restarts = self.event_count = 0
        self.last_seen = time.monotonic()
        self.last_event = stamp()
        self.state, self.detail = 'idle', 'Waiting for a galaxy'
        self.last_completed = None
        self.last_completed_time = None
        self.last_completed_at = None
        self.next_launch = time.monotonic() + index * 12
        self.log_path = data / f'worker-{index + 1}.log'

    def start(self, galaxy):
        self.galaxy = galaxy
        job = self.data / 'galaxies' / str(galaxy)
        config = copy.deepcopy(self.config)
        config['sweep'].update(workers=1, galaxies=[galaxy],
                               account_profiles=[self.account], worker_browsers=['chrome'])
        profile = 'browser-profile' if self.index == 0 else f'browser-profile-account-{self.index}'
        profile = config.get('browser_profiles',{}).get(self.account.casefold(),profile)
        config['browser_profile'] = str((self.data / profile).resolve())
        config['store_path'] = str((self.data / 'observations.sqlite').resolve())
        config_path = job / f'worker-{self.index + 1}-config.json'
        if not atomic_json(config_path, config):
            raise RuntimeError('Cannot save worker config')
        self.output = self.log_path.open('a', encoding='utf-8', buffering=1)
        self.output.write(f'\n{stamp()} START account={self.account} galaxy={galaxy}\n')
        self.position = self.log_path.stat().st_size
        self.process = subprocess.Popen(
            [sys.executable, '-u', '-m', 'ev_assistant', 'sweep',
             '--config', str(config_path), '--data-dir', str(job)],
            cwd=ROOT, stdout=self.output, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        self.last_seen, self.last_event = time.monotonic(), stamp()
        self.event_count = 0
        self.last_completed = self.last_completed_time = self.last_completed_at = None
        self.state, self.detail = 'starting', f'Opening saved session for Galaxy {galaxy}'
        LOG.info('Worker %s started %s PID=%s Galaxy=%s', self.index + 1,
                 self.account, self.process.pid, galaxy)

    def observe_log(self):
        with self.log_path.open('r', encoding='utf-8', errors='replace') as handle:
            handle.seek(self.position)
            additions = handle.read()
            self.position = handle.tell()
        for line in additions.splitlines():
            if 'Worker 1 ' in line:
                self.last_seen, self.last_event = time.monotonic(), stamp()
                self.detail = line.split('Worker 1 ', 1)[1]
                self.state = 'retrying' if 'retry' in self.detail else 'active'
                self.event_count += 1
                match = re.search(r'completed (\d+:\d+)', self.detail)
                if match:
                    self.last_completed = match[1]
                    self.last_completed_time = time.monotonic()
                    self.last_completed_at = stamp()
            elif 'ERROR Stopped:' in line:
                self.detail = line.split('ERROR Stopped:', 1)[1].strip()

    def failure_reason(self, now=None):
        if self.process is None:
            return None
        if self.process.poll() is not None:
            return f'process exited ({self.process.returncode})'
        now = time.monotonic() if now is None else now
        limit = 360 if self.event_count == 0 else 240
        if now - self.last_seen > limit:
            return f'no worker events for {int(now - self.last_seen)} seconds'
        return None

    def close(self):
        stop_tree(self.process)
        self.process = None
        if self.output:
            self.output.close()
            self.output = None

    def restart(self, reason):
        LOG.warning('Restarting ONLY worker %s (%s): %s', self.index + 1, self.account, reason)
        self.close()
        self.restarts += 1
        self.start(self.galaxy)

    def service(self, pending, end):
        try:
            if self.process is not None:
                self.observe_log()
                if self.process.poll() is not None and (self.process.returncode == 0 or
                                                       galaxy_done(self.data, self.galaxy, end)):
                    finished = galaxy_done(self.data, self.galaxy, end)
                    if finished:
                        LOG.info('Worker %s finished Galaxy %s', self.index + 1, self.galaxy)
                    else:
                        LOG.warning('Worker %s deferring Galaxy %s holes; assigning next galaxy',
                                    self.index + 1, self.galaxy)
                        if self.galaxy not in pending:
                            pending.append(self.galaxy)
                    self.close()
                    self.galaxy = None
                    self.state, self.detail = 'idle', 'Pass ended; awaiting next assignment'
                else:
                    reason = self.failure_reason()
                    if reason:
                        self.restart(reason)
            if self.process is None and time.monotonic() >= self.next_launch:
                if self.galaxy is None and pending:
                    self.galaxy = pending.pop(0)
                if self.galaxy is not None:
                    self.start(self.galaxy)
        except Exception as exc:
            LOG.exception('Worker %s recovery failed; other workers continue', self.index + 1)
            self.close()
            self.state, self.detail = 'error', str(exc)
            self.next_launch = time.monotonic() + 30

    def status(self):
        return {'account': self.account, 'browser': 'chrome', 'galaxy': self.galaxy,
                'pid': self.process.pid if self.process else None,
                'state': self.state, 'lastEvent': self.last_event,
                'lastCompleted': self.last_completed, 'detail': self.detail,
                'lastCompletedAt': self.last_completed_at,
                'secondsSinceCompletion': (round(time.monotonic() - self.last_completed_time)
                                           if self.last_completed_time is not None else None),
                'restarts': self.restarts,
                'secondsSinceEvent': round(time.monotonic() - self.last_seen)}


def reconcile_slots(slots, pending, config, data=DATA):
    """Resize the worker pool without restarting unaffected browser sessions."""
    count = config['sweep']['workers']
    names = config['sweep']['account_profiles']
    if type(count) is not int or not 1 <= count <= MAX_AGENTS or len(names) < count:
        raise ValueError('Invalid worker count or missing accounts')
    if any(not name.strip() for name in names[:count]) or len({n.casefold() for n in names[:count]}) != count:
        raise ValueError('Active accounts must be unique and nonempty')
    while len(slots) > count:
        removed = slots.pop()
        removed.close()
        if removed.galaxy is not None and removed.galaxy not in pending:
            pending.insert(0, removed.galaxy)
        LOG.info('Removed worker %s (%s); saved galaxy progress retained',removed.index+1,removed.account)
    for index, slot in enumerate(slots):
        if slot.account != names[index]:
            galaxy = slot.galaxy
            slot.close()
            slots[index] = Slot(index, config, data)
            slots[index].galaxy = galaxy
            slots[index].next_launch = time.monotonic()
        else:
            slot.config = config
    added = 0
    while len(slots) < count:
        slot = Slot(len(slots), config, data)
        slot.next_launch = time.monotonic() + added * 12
        slots.append(slot)
        added += 1
        LOG.info('Added worker %s (%s)',slot.index+1,slot.account)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s',
                        handlers=[logging.FileHandler(DATA / 'supervisor.log', encoding='utf-8'),
                                  logging.StreamHandler()])
    singleton = socket.socket()
    try:
        singleton.bind(('127.0.0.1', 47682))
    except OSError:
        LOG.error('A scan supervisor is already running')
        return
    config = read_json(ROOT / 'config.json', {})
    positions = sweep_positions(config)
    galaxies, end = config['sweep']['galaxies'], config['sweep']['system_end']
    prepare_jobs(DATA, galaxies)
    store = Store(DATA / 'observations.sqlite')
    if config['sweep'].get('verification_mode') == 'explicit-slots-v1':
        prune_completed_holes(DATA, galaxies, store, config)
    pending = pending_galaxies(DATA, galaxies, end)
    slots = [Slot(index, config) for index in range(config['sweep']['workers'])]
    browser_mode = config['sweep'].get('browser_mode', 'isolated')
    host = SharedBrowserHost(ROOT, DATA) if browser_mode == 'shared' else None
    atomic_json(DATA / 'supervisor-pids.json', {'pid': os.getpid(), 'started': stamp()})
    try:
        while True:
            if (DATA / 'STOP').exists():
                LOG.info('STOP requested')
                break
            requested = read_json(ROOT / 'config.json', config)
            browser_ready = True
            if host:
                if not host.alive:
                    # A server crash invalidates every context. Preserve each
                    # assignment and restart from receipts after a new host is ready.
                    for slot in slots:
                        if slot.process is not None:
                            slot.close()
                            slot.restarts += 1
                            slot.next_launch = time.monotonic() + slot.index * 12
                            slot.state, slot.detail = 'starting', 'Waiting for shared Chrome'
                browser_ready = host.ensure()
                if browser_ready:
                    requested['_shared_browser_endpoint'] = host.info['endpoint']
                    for slot in slots:
                        if slot.detail == 'Waiting for shared Chrome':
                            slot.detail = 'Waiting for scheduled session restart'
            else:
                requested.pop('_shared_browser_endpoint', None)
            try:
                requested_positions = sweep_positions(requested)
                reconcile_slots(slots, pending, requested)
                config, positions = requested, requested_positions
            except ValueError as exc:
                LOG.error('Keeping current worker configuration: %s', exc)
            command_path = DATA / 'worker-command.json'
            if command_path.exists():
                command = read_json(command_path,{})
                command_path.unlink(missing_ok=True)
                index = command.get('index',0)-1
                if command.get('action') == 'restart' and 0 <= index < len(slots):
                    if browser_ready and slots[index].process is not None:
                        slots[index].restart('Requested in EOG')
            if browser_ready:
                for slot in slots:
                    slot.service(pending, end)
            progress, holes = {}, []
            for galaxy in galaxies:
                coverage = coverage_for(DATA, galaxy)
                progress.update(coverage['progress'])
                holes.extend(coverage['retry_holes'])
            atomic_json(DATA / 'sweep-progress.json', progress)
            atomic_json(DATA / 'sweep-retries.json', {'systems': sorted(holes)})
            complete = all(galaxy_done(DATA, galaxy, end) for galaxy in galaxies)
            atomic_json(DATA / 'sweep-status.json', {
                'supervisorPid': os.getpid(), 'state': 'complete' if complete else 'running',
                'browserMode': browser_mode,
                'sharedBrowserPid': host.info.get('browserPid') if host else None,
                'browserState': 'ready' if browser_ready else 'retrying',
                'updated': stamp(), 'expectedWorkers': len(slots), 'liveWorkerResize': True,
                'activeWorkers': sum(slot.state in ('active', 'retrying') and
                                     slot.process is not None for slot in slots),
                'retryingWorkers': sum(slot.state == 'retrying' for slot in slots),
                'queuedGalaxies': pending,
                'completedSystems': (store.checked_system_count(config['sweep']['verification_mode'], positions)
                    if config['sweep'].get('verification_mode') == 'explicit-slots-v1'
                    else sum(int(value) for value in progress.values()) - len(holes)),
                'totalSystems': len(galaxies) * end, 'retrySystems': len(holes),
                'verificationMode': config['sweep'].get('verification_mode', 'legacy-three-views'),
                'verifiedPlanetSlots': store.checked_slot_count(config['sweep'].get('verification_mode', ''), positions),
                'totalPlanetSlots': len(galaxies) * end * len(positions),
                'requiredSlotsPerSystem': len(positions), 'requiredPositions': list(positions),
                'skippedPositions': [p for p in range(1, 22) if p not in positions],
                'workers': {str(slot.index + 1): slot.status() for slot in slots}})
            try:
                export_players(store, DATA)
            except PermissionError:
                LOG.warning('Player export is busy; retrying next tick')
            if complete:
                LOG.info('All galaxies completed with no pending systems')
                return
            time.sleep(5)
    finally:
        for slot in slots:
            slot.close()
        if host:
            host.close()
        singleton.close()


if __name__ == '__main__':
    main()
