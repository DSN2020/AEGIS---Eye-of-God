"""Separate installed program files from per-user settings and scan data."""
import os
import hashlib
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1]
if (APP_ROOT / 'runtime' / 'browsers').is_dir():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(APP_ROOT / 'runtime' / 'browsers')


def user_root():
    # Source checkouts retain their existing local data unless explicitly configured.
    return Path(os.environ.get('EOG_DATA_ROOT', str(APP_ROOT))).resolve()


def browser_options(browser='chrome'):
    bundled = APP_ROOT / 'runtime' / 'browsers'
    if bundled.is_dir():
        os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(bundled)
        # Use the matching Playwright Chromium shipped with this release.
        return {}
    return {'channel': browser}


def child_environment(root):
    return dict(os.environ, EOG_DATA_ROOT=str(Path(root).resolve()))


def supervisor_port(root=None):
    root = Path(root).resolve() if root is not None else user_root()
    if root == APP_ROOT:
        return 47682  # Preserve the existing source-install supervisor lock.
    # Separate users/installations must not control each other's scanner.
    identity = os.path.normcase(str(root)).encode('utf-8')
    return 49152 + int.from_bytes(hashlib.sha256(identity).digest()[:2], 'big') % 16384
