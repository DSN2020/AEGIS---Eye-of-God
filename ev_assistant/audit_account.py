"""Require an explicit locally configured account for developer audits."""
from pathlib import Path
from .credentials import load_passwords


def add_account_argument(parser):
    parser.add_argument('--account', required=True,
                        help='Saved account to use; stop its scanner worker first.')


def resolve_account(root, config, username):
    names = config.get('sweep', {}).get('account_profiles', [])
    index = next((i for i, name in enumerate(names)
                  if name.casefold() == username.casefold()), None)
    if index is None:
        raise ValueError('Configure the selected account in EOG before running this audit.')
    name = names[index]
    passwords = load_passwords(Path(root) / 'data', name)
    if not passwords:
        raise ValueError('Save a password for the selected account in EOG first.')
    default = 'browser-profile' if index == 0 else f'browser-profile-account-{index}'
    profile = config.get('browser_profiles', {}).get(name.casefold(), default)
    return {'username': name, 'passwords': passwords}, Path(root) / 'data' / profile
