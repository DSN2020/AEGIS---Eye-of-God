# EOG — Eye of God

Windows desktop control panel for the Eternal Void scanner. Its WPF theme is adapted from the user's Anispo Control Panel: charcoal panels, red accents, rounded controls, and sidebar navigation.

Open `publish/EOG.exe` or the **EOG** desktop shortcut. Keep the executable in this folder structure; it connects to the scanner's existing Python environment through `desktop-runtime.json` in the scanner root. Closing EOG leaves the scanner running. **Pause scan** stops scanner agents and preserves every saved confirmation; **Resume scan** continues from checkpoints.

- **Live overview:** account-level status, verified slot and system totals, found players, and a selected agent's game screenshot. Status refreshes every two seconds; screenshots are captured during scanning about every five seconds. No login screenshots are used for this view. Restart selected affects only the selected agent.
- **Agents & accounts:** choose 1–6 agents, one unique username per active slot, and enter passwords in masked fields. The first N saved accounts run. The +/− count buttons apply automatically after a short debounce; existing workers keep their processes when agents are added or removed. Live overview shows the pending target and workers starting. Missing saved credentials produce an inline error without changing the running count. Username/password edits still require **Save & apply**; those edits may restart the scanner. Blank passwords retain saved values, and settings never reset coverage. Windows DPAPI encrypts saved passwords. New usernames receive their own browser profile.
- **Player coordinates:** players are ordered by their most recent observation; search names and filter by alliance simultaneously. Every player has its coordinates grouped underneath. Copy one player or all matching results. Bot names beginning with `bot_` are omitted. Alliances are read from confirmed planet detail popups and stored in SQLite; old or unreadable alliance values display **Not recorded**, and an explicit empty/hyphen value displays **No alliance**.
- **Activity:** recent scanner messages merged across accounts, newest first. Each account has a distinct color. New messages receive a matching background highlight for five seconds from arrival; the highlight expires independently of polling and unchanged messages do not flash again. Historical messages do not flash when the app first opens. Message text remains selectable.

The app bridge has no network listener; commands and responses use private process input/output. It never returns stored passwords to the desktop app or its logs.

Build: `dotnet publish EyeOfGod.csproj -c Release -o publish`

UI verification: `publish/EOG.exe --verify-ui` exercises actual name/alliance filters and agent-count bounds, then writes rendered screenshots and `verification.json` in `ui-review/`. It does not modify credentials or start/stop the scanner. Scanner and bridge tests live in the root `tests/` directory.
