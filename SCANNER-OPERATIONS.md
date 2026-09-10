# Eternal Void scanner

## Current scan scope — September 9

The user identified positions 1–4 as NPC slots and position 21 as the nebula. The local and example configurations now set `sweep.positions` to 5–20. Each required position still uses the same clicked detail and two-read confirmation. No synthetic NPC observations or verification receipts are written for excluded positions. The active total is 4,491 × 16 = 71,856 positions. Status exposes required and skipped positions, and the desktop reports the corresponding totals.

Existing `explicit-slots-v1` receipts remain valid and are reused. Stored player observations are preserved. A system completes when every required position has a receipt, irrespective of old receipts at excluded positions. Startup removes old retry holes only when all currently required receipts exist; genuine missing player-position checks remain queued. Initial navigation and retries start at the first required position. Configurations without `sweep.positions` retain the legacy 21-position scope. Change scope while paused, then resume to apply it to workers; expanding a previously reduced scope requires a separate coverage reconciliation before treating old completed frontiers as full coverage.

The older full-coverage notes below describe the previous 21-position scope, not the current required total.

## Coverage correction — September 9

The original three-map-view sweep missed planets between views. System 9:57 was logged as complete with zero players, but direct UI confirmation found XXxxNAZIMxxXX at 9:57:14. Its old completion percentage is not evidence of complete planet coverage. Existing ownership observations remain useful; all systems require verification with the replacement reader.

The replacement mode is `explicit-slots-v1`: navigate separately to positions 1 through 21, open each detail, and require two consistent reads. Slots 1–20 require matching detail coordinates and a confirmed owner or explicit NPC/empty presentation. Slot 21 has a calibrated Mysterious Nebula exploration panel without detail coordinates; verify its panel twice and read all three coordinate editors. No exploration or fleet actions are clicked. Each verified slot is saved in SQLite `slot_checks`, and a system can complete only with all 21 receipts. Failed slots remain unresolved, and retries reuse successful receipts. Legacy observations do not create receipts. Status exposes `verifiedPlanetSlots` and the verification mode.

The full recheck preserves player observations and archives the legacy progress before resetting coverage. Do not restore legacy coverage frontiers into a verification pass.

Run `python sweep_supervisor.py` from this directory using the configured virtual environment. This entry point now starts the independent-worker supervisor. It refuses to start a duplicate supervisor on this computer.

Each configured account owns a separate browser process. Each receives one unfinished galaxy. On completion it receives another galaxy. All nine galaxies remain assigned to this computer; no second computer is configured.

Expired sessions can log in using the user-supplied credentials encrypted in `data/account-secrets.dpapi` with Windows current-user DPAPI. Passwords are loaded in memory and are never written into worker configuration or logs. The login handler dismisses validation dialogs, recognizes "Invalid username or password", and advances to the next supplied candidate. Missing credentials fail explicitly instead of submitting empty fields. This recovery code takes effect independently when each worker next starts.

Each assignment now runs one bounded pass. If it leaves unreadable systems, their galaxy goes to the back of the queue rather than trapping a worker in unlimited retry rounds. On startup, galaxies with unvisited systems take priority over galaxies that only have retry holes. Finishing a pass does not mark an incomplete galaxy complete.

The supervisor restarts only a failed worker. A worker that exits is recovered on the next check. A worker that produces no scan events for four minutes is restarted; initial login has a six-minute allowance. Other workers retain their PIDs and browser sessions. Startup failures back off for 30 seconds. A galaxy is complete only when its frontier reaches system 499 and its retry list is empty.

Live files under `data/`:

- `sweep-status.json`: account, PID, galaxy, latest completed system, state, age of latest event, restart count; refreshed about every five seconds.
- `supervisor.log`: worker launches, recoveries, and completed galaxies.
- `worker-1.log` through `worker-4.log`: individual scan events. Each child calls itself Worker 1 internally; the filename and supervisor status identify the account.
- `sweep-progress.json`, `sweep-retries.json`: combined progress and unresolved systems.
- `galaxies/<galaxy>/coverage.json`: authoritative checkpoint. Frontier and retry holes commit together.
- `observations.sqlite`: shared SQLite database with confirmed ownership observations.
- `players.txt`, `players.csv`: combined, deduplicated player coordinates, excluding `bot_` owners.

Create `data/STOP` to request a stop of all workers. Remove that file before starting again. Do not run the old all-in-one `python -m ev_assistant sweep` simultaneously with the supervisor, since they would compete for profiles and coverage files.

Popup handling recognizes OCR text with or without spaces, joins coordinate boxes on the same visual line, and requires an owner with matching detail coordinates in two observations. A coordinate label without an owner does not count as a confirmed planet. The scanner closes popups by clicking outside them and verifies that they disappeared; it does not press the map's OK button to dismiss them.

ASCII and full-width colons are accepted in labels and coordinate separators; player names retain their original Unicode characters. Status includes `lastCompletedAt`, `secondsSinceCompletion`, and a separate `retryingWorkers` count, so fresh process activity can be distinguished from new completed systems.

Popup OCR uses only the detail panel region. Explicit verification selects every numbered slot and confirms the resulting detail. The legacy pan reader remains in the code for diagnosis, but must not be used for complete coverage.

The saved `benchmark-four-chrome.json` and `benchmark-mixed-browsers.json` files record the prior browser experiment. They do not measure the revised implementation.

## Efficiency changes — September 9, afternoon

The current defaults are `efficient_slots=true`, `detail_ocr=true`, and `render_fps=20` in `sweep`. They do not change the verification revision or reset receipts. The scanner still opens every unverified slot and requires matching coordinates and two consistent observations. A fresh byte-identical screenshot may reuse its OCR result; changed screenshots always run OCR. The two-entry cache is memory-only.

Fresh text detection keeps its calibrated resolution. Detail recognition reads coordinate, owner, and alliance rows for the upper ownership layout, or the NPC/empty/nebula information rows and classification controls for the centered layout. An unreadable selected-row observation falls back to full OCR on the next attempt. Action buttons and item levels are not needed to identify owners. The live comparison and the saved 21-capture replay both preserved the two reference players, the bot, and every empty/NPC classification and recorded alliance.

A normal slot no longer closes its popup and OCRs the closed map before selecting the next coordinate. The coordinate-checked new popup supplies that validation. Slot 21 still verifies all three header editors and closes the panel before system navigation. Keep the one-second initial transition allowance: a .15-second experiment repeatedly read stale details and added unnecessary OCR. The inter-read pause is now .05 seconds instead of .35 seconds.

Browser animation is capped at 20 FPS after account entry. Loading/login remains uncapped. The limiter preserves animation timestamps and cancellation, including cancellation by another callback in the same frame. OpenCV has one thread per worker, matching the already bounded ONNX pools. The isolated OpenCV comparison did not show a measurable speed improvement by itself. GPU inspection confirmed that Chrome already used the RTX 3070; forcing GPU flags was unnecessary.

Live benchmark files are under `data/efficiency-benchmark/`. These are bounded UI-only reads of 9:57 positions 1–21 using an explicitly selected standby account, with no ownership or coverage writes. Other desktop activity continued; production workers were rolling onto the new version during the final test, so these are practical loaded-machine comparisons rather than an isolated microbenchmark.

| Version | All 21 slots | Mean per slot | OCR calls |
|---|---:|---:|---:|
| Original, with four other game workers | 262.70 s | 12.51 s | 66 |
| First optimization | 195.27 s | 9.30 s | 64 |
| Focused detail OCR and corrected transition wait | 163.38 s | 7.78 s | 50 |

The final comparison used 37.8% less elapsed time and found identical results in all 21 positions. The last run predates the identical-frame cache. Do not present 7.78 seconds as a guaranteed rate or compare these five-browser timings directly to an earlier four-browser estimate. Normal system-navigation and retry overhead also affects whole-universe throughput.

Validation: 54 automated tests; all 21 saved detail captures; live 21-slot ownership/alliance comparison; real-browser frame timing and cancellation checks. `measure_scan_rate.py` records a separate 90-second four-worker sample in `four-worker-rate.json`. New workers log per-system elapsed time, OCR call counts, and identical-frame reuse counts. Only the affected worker is restarted for code rollout or recovery; receipts remain in the same shared database.

The four-worker production sample confirmed 47 new slots in 90.48 seconds, or 31.17 verified slots/minute, including navigation and retries. All four process IDs remained unchanged. A later CPU snapshot was 68%, versus the earlier 90–100% readings, but background activity varies. Identical-frame caching is opportunistic: the first logged 18-slot system had zero hits because the background changes.

At the time of this earlier trial, the desktop app supported 1–6 accounts. Four was the operating choice, not a hardware or account-count restriction. A six-worker trial added two standby accounts across galaxies 5 and 6. CPU reached 100%; only three workers reached scanning during the observation period, and one existing worker timed out at login and restarted. The trial was aborted and the four-worker setting restored, preserving all receipts and retaining the two standby accounts. `six-worker-trial.json` records the state. No steady six-worker throughput figure was obtained, so do not claim that four is a universal optimum or extrapolate a six-worker rate from startup. More accounts must be judged by aggregate verified slots/minute and reliable startup.

## Live worker-count changes

The supervisor rereads saved worker settings each tick and reconciles the pool. Increasing the count appends workers using the first N saved accounts, with new launches staggered by 12 seconds. Reducing the count closes only the removed workers and returns their assigned galaxies to the pending queue. Unchanged workers retain both their process IDs and browser sessions. Changing an account name replaces only that slot during reconciliation. All checkpoints remain shared and resumable.

The desktop count buttons send `set_worker_count` after a 650 ms debounce. This validates the saved accounts and credentials, saves the target without stopping the supervisor, and lets the next supervisor tick apply it. The snapshot exposes `requestedWorkers` and `workerCountPending` separately from actual scanning/starting workers. Account credential edits remain an explicit Save & apply operation. `tests/test_live_worker_count.py` covers pool preservation, returned galaxies, validation, and pending-count reporting; `verify_live_resize.py` performs a bounded 4→5→4 live check and records the unchanged worker/supervisor PIDs in `data/live-resize-verification.json`.

Developer audits and benchmarks require `--account YOUR_ACCOUNT`, selected from your local saved accounts. Stop that account’s worker before running an audit that uses its browser profile. No account is selected by default.

## Rendered-text reader — September 9, evening

The deployed game exposes its displayed Pixi stage and renderer through its developer inspection interface. The planet map is a canvas; its initial HTML contains no player directory. `ev_assistant/rendered_text.py` reads displayed text objects and their screen bounds without issuing API requests, reading hidden game data, changing the scene, or installing renderer hooks. Each account continues using its own persistent browser. Browser processes were already reused across planets; the primary change removes repeated screenshot/OCR inference for supported details.

With `sweep.rendered_text=true`, each clicked detail first uses rendered text. Two matching ownership/classification readings from different renderer ticks are required. Exact detail coordinates remain mandatory; the special position-21 panel still requires all three coordinate editors. Invisible, masked, faint, offscreen, unsupported and malformed text cannot provide a confirmation. Overlapping identical outline layers are deduplicated. Multiple coordinate/owner labels are rejected. Missing, stale or ambiguous rendered text falls back to the existing OCR path, and changing sources requires two confirmations from the new source. Coverage receipts, bot exclusion, alliance storage, and live screenshots retain their existing behavior. Setting the flag to false and restarting the affected worker returns to OCR-only details.

A development comparison, before the final inherited-opacity visibility guard, opened every position in 9:57 with each reader while five other workers continued scanning. All 21 classifications and owner identities matched. Rendered text also supplied one alliance that OCR left unreadable; the other recorded alliances agreed. Total slot-check time was 34.26 seconds with rendered text versus 107.12 seconds with OCR (68.0% less time, 3.13x as fast for this sample). The fast pass used 42 rendered-text reads and 6 OCR calls, including fallback and the position-21 close check. Raw comparison and captures remain local under `data/render-text-probe/`. These figures exclude login/system-entry time and are not a whole-universe throughput guarantee.

Validation: 76 automated checks plus real-browser offline checks of visibility, inherited opacity, masking, viewport scaling, outlines, render ticks and missing-interface fallback. The live rollout replaces one worker at a time and requires a completed system with rendered-text reads before moving on. Per-system performance logs expose rendered-text read counts beside OCR counts. No credentials or account defaults are added to the repository.

The completed production rollout confirmed all six workers using rendered text; each selected restart preserved every other worker PID. A subsequent full-pipeline sample of the final reader verified 146 new slots in 60.20 seconds (145.52 slots/minute), with all six worker PIDs unchanged. This includes normal navigation and retries. Results are local in `data/rendered-text-rollout.json` and `data/rendered-text-throughput.json`; the sample is a measured rate on this machine, not a guaranteed sustained rate.

## Ten account slots

The desktop, bridge and supervisor now accept 1–10 configured agents. Each account has its own login fields and activity color. New fields and fresh-install templates contain no credentials. Whole-galaxy scheduling remains unchanged: with nine galaxies, at most nine agents can have simultaneous assignments; a tenth waits. Existing six-worker sessions need no restart just to install the new UI. Adding new accounts through Save & apply starts the updated supervisor from saved checkpoints.


## Shared-browser mode — September 9

The supervisor can own one headless Chrome server (`sweep.browser_mode: "shared"`). It launches the Node runtime and Playwright package bundled with the same Python Playwright installation, keeping protocol versions matched. The WebSocket binds only to 127.0.0.1; its random endpoint lives in ignored runtime files. Each Python worker creates its own browser context through the native Playwright connection. The existing per-planet clicks, two-read confirmation, alliance parsing, OCR fallback, receipts and previews are unchanged.

Only the supervisor owns the host process. A failed or removed worker disconnects its client and releases its contexts without closing the shared Chrome instance. A host/browser failure closes affected workers and restarts their existing galaxy assignments from receipts, staggered by slot. Cookies and local storage are saved using DPAPI to account-specific hashed paths after login. Persistent browser profiles remain available for rollback. Set `sweep.browser_mode` back to `"isolated"` while paused and resume to restore separate browsers; changing browser mode while running takes effect at the next supervisor start.

Status includes `browserMode`, `browserState` and `sharedBrowserPid`; Live overview describes the active mode. A shared Chrome instance still has renderer/helper subprocesses and does not remove the per-worker game or OCR workload. Nine galaxy assignments remain the maximum concurrency even with ten configured account slots.

`python verify_shared_browser.py` uses a local fixture, with no game accounts, to check isolated cookies/local storage, encrypted session restoration, client close, forced worker termination with no orphan contexts, and browser-crash recovery. Existing worker-count/recovery and ownership-verification tests remain applicable.

The live nine-account trial used exactly one Chrome root with separate contexts and confirmed new slots without resetting coverage. Only the first four accounts reached sustained scanning; later accounts remained on the game loading overlay and retried. Shared-session startup was extended from 90 to 240 seconds, below the 360-second worker watchdog, but the later sessions still did not reach scanning during the trial. A requested restart of agent 1 preserved the Chrome PID and the PIDs/progress of scanning agents 2–4. No graphics or network failures were reported during the bounded diagnostic observations; the underlying loading cause is unresolved.

The operational setup and example configuration therefore retain `browser_mode: "isolated"`. Shared mode is opt-in and experimental. The separate-browser sample overlapped the ninth account's startup, and shared mode did not reach equivalent concurrency, so these observations do not establish a fair throughput or memory improvement. Private trial/status reports remain under ignored `data/`.
