"""Reload scanner code one account at a time; verify progress before the next."""
import json
import subprocess
import time
from pathlib import Path

DATA = Path(__file__).resolve().parent / 'data'


def status():
    return json.loads((DATA / 'sweep-status.json').read_text())


def main():
    before = status()
    results = []
    for worker in ('2', '3', '4', '1'):
        initial = status()
        old_pid = initial['workers'][worker]['pid']
        other_pids = {key: value['pid'] for key, value in initial['workers'].items()
                      if key != worker}
        print(f'Reloading worker {worker}, PID {old_pid}', flush=True)
        subprocess.run(['taskkill', '/PID', str(old_pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        deadline = time.monotonic() + 360
        while time.monotonic() < deadline:
            time.sleep(5)
            current = status()
            entry = current['workers'][worker]
            if (entry['pid'] != old_pid and entry['state'] == 'active'
                    and entry['detail'].startswith('completed ')):
                result = {'worker': worker, 'account': entry['account'],
                          'oldPid': old_pid, 'newPid': entry['pid'],
                          'completion': entry['detail'],
                          'otherPidsUnchanged': all(current['workers'][key]['pid'] == pid
                                                   for key, pid in other_pids.items())}
                results.append(result)
                print(json.dumps(result), flush=True)
                break
        else:
            raise RuntimeError(f'Worker {worker} has not completed a system after reloading')
    (DATA / 'rolling-update-results.json').write_text(json.dumps(results, indent=2))
    print('All four workers reloaded and confirmed progressing', flush=True)


if __name__ == '__main__':
    main()
