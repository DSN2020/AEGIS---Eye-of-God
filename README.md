# EOG — Eye of God

Windows desktop control panel and coordinate scanner for [Eternal Void](https://eternal-void.online/).

Repository: [DSN2020/AEGIS---Eye-of-God](https://github.com/DSN2020/AEGIS---Eye-of-God).

## Download for Windows

**[Download EOG for Windows](https://github.com/DSN2020/AEGIS---Eye-of-God/releases/latest)**

1. Under **Assets**, download **EOG-<version>-windows-x64.zip**.
2. Right-click the ZIP and select **Extract All**.
3. Open the extracted folder and double-click **EOG.exe**.
4. Enter your Eternal Void account, select **Save & apply**, then **Resume scan**.

The download includes Python, .NET, Chromium and OCR. No developer tools, commands or administrator access are required. Supports 64-bit Windows 10/11 on Intel/AMD PCs. Scanning requires internet access and your own game account. macOS, Linux and native ARM builds are not included.

**GitHub's Code → Download ZIP downloads the source code.** Use the Windows asset on the release page to run the app. If you already downloaded the source folder, double-click **Download EOG.cmd** to open the correct download page.

Settings and results are stored separately in `%LOCALAPPDATA%\EOG`. To update, pause scans and any Upgrade bot profiles, close EOG, and extract the new download into a new folder. Your accounts and progress remain available. Source installations keep their original local data and are not automatically migrated. Closing EOG leaves scans running; use **Pause scan** to stop them.

Current downloads are unsigned, so Windows may show an unknown-publisher warning. See the release notes for the checks performed for that build.

## Features

- WPF app with live worker status, game previews, and account management.
- Python + Playwright with separate browser profiles and an optional shared-Chrome mode.
- RapidOCR reads the canvas. Every unverified slot is opened and checked before recording ownership.
- Resumable coverage of nine galaxies and 499 systems each. The default sweep checks positions 5–20 (16 per system), skipping NPC positions 1–4 and nebula position 21. Unresolved required positions remain queued for retry.
- Player coordinates grouped by owner, newest observations first, with name search and alliance filtering.
- Newest-first activity, distinct account colors, and one-second fades from account colors to gray for incoming messages.
- Automatic resizing between 1–10 agents using saved accounts. Unchanged workers keep their browser processes.
- Reads displayed planet-detail text directly from the game renderer, with automatic OCR fallback. Every planet is still opened and confirmed.
- Local Windows DPAPI protection for saved passwords.

## Developer setup from source

Install Python 3.10, Google Chrome at its standard Windows location, and the .NET 8 SDK. From this folder:

```powershell
.\Setup.ps1
dotnet publish DesktopApp/EyeOfGod.csproj -c Release -o DesktopApp/publish
.\DesktopApp\publish\EOG.exe
```

Setup creates a virtual environment, copies `config.example.json` to `config.json` if absent, and writes the local Python path to `desktop-runtime.json` if absent. Existing configuration files are preserved.

To build a distributable Windows download, see [packaging instructions](packaging/README.md). Publishing only `EOG.exe` from the source build does not include the scanner runtime.

In **Agents & accounts**, choose the agent count, enter one account per selected slot, and select **Save & apply**, then use **Resume scan**. Usernames and email logins are supported. Count and account edits are saved together; an unsaved draft does not change the running scanner. Additional workers share the computer's resources and may not increase throughput.

Closing EOG leaves the scanner running. **Pause scan** stops workers and retains progress. Findings represent last observed ownership. An incomplete scan is not evidence that no other players exist.

## Source and local data

- `DesktopApp/`: desktop application and icon assets.
- `ev_assistant/`: browser navigation, rendered-text reading, OCR fallback, verification, credential protection, and storage.
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

Fresh installations have ten blank username/password slots. Add your own accounts in Manage; there are no bundled accounts. Saved account names, encrypted passwords, browser sessions, and scan results stay in the local ignored files. Share this repository or a clean build, not your working folder with its local configuration and data.

The `sweep.rendered_text` setting enables the faster detail reader (enabled in new configurations). Existing configurations can set it to `true` and restart workers individually; setting it to `false` restores OCR-only detail verification. Each account retains its isolated session and saved login. Live previews and checkpoints continue working. Run `python verify_rendered_text.py` for offline browser checks; `python benchmark_efficiency.py rendered-text --account YOUR_ACCOUNT` benchmarks an explicitly selected idle account.

EOG supports ten account slots. The current scheduler assigns a whole galaxy to each scanning agent, so up to nine can scan concurrently; an additional configured agent waits for an available assignment. New slots are blank and require your own credentials. Adding accounts through Save & apply restarts the supervisor from checkpoints and loads the updated limit.

## Shared Chrome (experimental)

Separate browsers remain the default. In a nine-account trial on September 9, one shared browser sustained four scanning agents while later accounts remained on the game's loading screen, including with a longer startup allowance. Separate browsers were restored from checkpoints. This is an observed trial result, not a universal four-account limit or a proven diagnosis of the game's loading problem.

Set `sweep.browser_mode` to `"shared"` in your local `config.json`, then pause and resume the scan. One headless Chrome instance hosts a separate context for each account. Live overview reports the active browser mode. Chrome still uses renderer/helper processes; one browser does not mean one Task Manager process.

Each worker remains an independent Python process. Restarting or removing an agent closes only that agent's context. If the shared browser crashes, the supervisor relaunches it and reconnects the workers from their saved receipts. Cookies and local storage are saved per account with Windows DPAPI under ignored `data/browser-sessions/`. The local Playwright endpoint is runtime-only and bound to loopback. It is not published with the source.

To return to the original arrangement, pause, set `sweep.browser_mode` to `"isolated"`, and resume. Existing persistent profiles are retained. Browser mode changes require a supervisor restart; agent-count changes remain live. Run `python verify_shared_browser.py` for offline browser isolation, encrypted-session, individual-worker crash and shared-browser recovery checks. Sharing Chrome reduces duplicated browser infrastructure; game renderers and OCR workers still consume resources.

## Upgrade bot tab

EOG includes account profiles, ordered upgrade plans, saved presets, scheduled checks and resource, energy and safe-run watch alerts. Owned Gamma rules can restore exhausted safe runs, with a per-account 24-hour limit; purchases are disabled. Auto mode restores power before following the plan. Profiles start paused and borrow only their selected scanner account while running. See [AUTOMATION.md](AUTOMATION.md) for setup, supported screens and current limitations.


## Hives in Player coordinates

Open **Player coordinates → Hives** to find concentrations of recorded human-owned planets. The default is at least **8 planets within 3 consecutive system numbers** in one galaxy. Both limits are adjustable (2–160 planets, 1–10 systems). A single player or several players can form a hive; alliances do not restrict membership.

Cards list the galaxy/system range, totals per system, each member's alliance, local planet count and coordinates. Largest qualifying windows are selected first, with tighter windows winning ties; overlapping windows are discarded so a planet never counts in two hives. Long concentrations are split into bounded groups rather than chained into one unlimited range. The grouping is a configurable estimate from collected coordinates, not an official game designation, and can change as scanning finds more planets.

Name and alliance filters find hives containing a member who matches both filters. All members of those hives remain visible for context. **Copy hive** and **Copy shown hives** copy exactly the displayed groups with compact Discord coordinate blocks. Detection updates with the directory and makes no additional game requests.

Run `dotnet run --project tests/HiveChecks/HiveChecks.csproj -c Release` for clustering, filtering, boundaries, deduplication and copy-format checks. The desktop `--verify-ui` check also captures the Hive view.


Copy buttons use a shared Unicode clipboard writer with brief asynchronous retries for clipboard contention. Other Windows failures report their error code instead of being labelled busy. The opt-in native integration check is `dotnet run --project tests/ClipboardChecks/ClipboardChecks.csproj -c Release -- --copy-saved-hive <private-player-snapshot.json>`; the file must contain the player array from the local bridge snapshot. This test temporarily changes the Windows clipboard and finishes by copying a saved hive. Never commit the snapshot.
