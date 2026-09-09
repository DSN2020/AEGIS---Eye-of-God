# EOG — Eye of God

Windows desktop control panel and coordinate scanner for [Eternal Void](https://eternal-void.online/).

Repository: [DSN2020/AEGIS---Eye-of-God](https://github.com/DSN2020/AEGIS---Eye-of-God).

## Features

- WPF app with live worker status, game previews, and account management.
- Python + Playwright with a separate Chrome profile for each worker.
- RapidOCR reads the canvas. Every unverified slot is opened and checked before recording ownership.
- Resumable coverage of nine galaxies, 499 systems each, and 21 slots per system. Unresolved slots remain queued for retry.
- Player coordinates grouped by owner, newest observations first, with name search and alliance filtering.
- Newest-first activity, distinct account colors, and five-second highlights for incoming messages.
- Automatic resizing between 1–6 agents using saved accounts. Unchanged workers keep their browser processes.
- Local Windows DPAPI protection for saved passwords.

## Windows setup

Install Python 3.10, Google Chrome at its standard Windows location, and the .NET 8 SDK. From this folder:

```powershell
.\Setup.ps1
dotnet publish DesktopApp/EyeOfGod.csproj -c Release -o DesktopApp/publish
.\DesktopApp\publish\EOG.exe
```

Setup creates a virtual environment, copies `config.example.json` to `config.json` if absent, and writes the local Python path to `desktop-runtime.json` if absent. Existing configuration files are preserved.

In **Agents & accounts**, enter your accounts and select **Save & apply**, then use **Resume scan**. Count changes apply automatically using saved account details; username/password edits require Save & apply. Additional workers share the computer's resources and may not increase throughput.

Closing EOG leaves the scanner running. **Pause scan** stops workers and retains progress. Findings represent last observed ownership. An incomplete scan is not evidence that no other players exist.

## Source and local data

- `DesktopApp/`: desktop application and icon assets.
- `ev_assistant/`: browser navigation, OCR, verification, credential protection, and storage.
- `isolated_supervisor.py`: worker supervision and live resizing.
- `app_bridge.py`: private process-input/output connection between EOG and the scanner.
- `tests/`: automated checks.

The local `data/` folder contains the database, browser profiles, credentials, screenshots, logs, and checkpoints. It is **excluded from Git**, along with `config.json`, `desktop-runtime.json`, virtual environments, and generated desktop builds. The repository synchronizes source code, not account details or scan results.

See [desktop usage](DesktopApp/README.md) and [scanner operations](SCANNER-OPERATIONS.md). Audit/benchmark scripts require local reference captures or development accounts and are not setup steps.

## Validation

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
dotnet build DesktopApp/EyeOfGod.csproj -c Release
```

The optional `EOG.exe --verify-ui` check requires populated local reference observations. It does not start or stop workers.

Fresh installations have six blank username/password slots. Add your own accounts in Manage; there are no bundled accounts. Saved account names, encrypted passwords, browser sessions, and scan results stay in the local ignored files. Share this repository or a clean build, not your working folder with its local configuration and data.
