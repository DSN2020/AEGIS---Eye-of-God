import hashlib
import json
import os
from pathlib import Path
import tempfile

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('EVO_MANAGER_DATA', str(ROOT / 'data' / 'automation')))


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name, suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default


def account_path(account):
    if not isinstance(account, str) or not account.strip():
        raise ValueError('Account name is required')
    key = hashlib.sha256(account.strip().casefold().encode()).hexdigest()[:24]
    path = DATA / 'accounts' / key
    path.mkdir(parents=True, exist_ok=True)
    return path
