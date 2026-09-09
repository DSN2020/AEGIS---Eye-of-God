"""Account passwords protected by Windows DPAPI for the current Windows user."""
import argparse
import ctypes
from ctypes import wintypes
import getpass
import json
import os
from pathlib import Path


class Blob(ctypes.Structure):
    _fields_ = [('cbData', wintypes.DWORD), ('pbData', ctypes.POINTER(ctypes.c_ubyte))]


def crypt(data, decrypt=False):
    if os.name != 'nt':
        raise RuntimeError('Saved credentials require Windows DPAPI')
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD,
                         ctypes.POINTER(Blob)]
    function.restype = wintypes.BOOL
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(target.pbData)


def load_passwords(data, username):
    path = Path(data) / 'account-secrets.dpapi'
    if not path.exists():
        return []
    values = json.loads(crypt(path.read_bytes(), decrypt=True))
    return values.get(username.casefold(), [])


def save_passwords(data, username, passwords):
    path = Path(data) / 'account-secrets.dpapi'
    values = json.loads(crypt(path.read_bytes(), decrypt=True)) if path.exists() else {}
    values[username.casefold()] = passwords
    temporary = path.with_suffix('.tmp')
    temporary.write_bytes(crypt(json.dumps(values).encode('utf-8')))
    temporary.replace(path)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--username', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--count', type=int, default=1)
    args = parser.parse_args()
    passwords = [getpass.getpass(f'Password {index + 1}: ') for index in range(args.count)]
    if any(not value for value in passwords):
        raise SystemExit('Empty passwords were not saved')
    save_passwords(args.data, args.username, passwords)
    print('Credentials saved using Windows user encryption.')
