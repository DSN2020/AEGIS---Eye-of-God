"""Remove build-machine launchers and bytecode after validating a release."""
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
assert (root/'eog-release.json').is_file() and (root/'EOG.exe').is_file()
assert Path(sys.executable).resolve().is_relative_to(root)

for path in root.rglob('*.pyc'):
    assert path.resolve().is_relative_to(root)
    path.unlink()
for path in root.rglob('__pycache__'):
    if not any(path.iterdir()):
        path.rmdir()
# Console-script wrappers contain absolute paths from the packaging machine.
# EOG always invokes the included interpreter directly with -m or an absolute script.
scripts = root/'runtime'/'python'/'Scripts'
if scripts.is_dir():
    for path in scripts.iterdir():
        if path.is_file():
            assert path.resolve().is_relative_to(root)
            path.unlink()
    if not any(scripts.iterdir()):
        scripts.rmdir()
for path in (root/'runtime'/'python'/'Lib'/'site-packages').glob('*.dist-info/direct_url.json'):
    assert path.resolve().is_relative_to(root)
    path.unlink()
print('Removed build-specific wrappers and bytecode; dependency licenses retained.')
