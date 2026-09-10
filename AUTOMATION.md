# EOG account automation

Open **Upgrade bot** in EOG. Account credentials are supplied by **Agents & accounts**, encrypted with Windows DPAPI. A new installation has no accounts or profiles. Profiles, presets, logs, browser sessions and observations live in the ignored `data/automation/` directory.

## Profiles and modes

Create a profile, select an account and enter the coordinate of its currently selected colony. The adapter verifies the account on the login screen and the colony coordinate in Planet Info. It stops if they differ; it does not guess which colony to operate.

- **Watch:** reads resources, energy and configured safe-nebula-run rules. It never queues an upgrade or uses an item.
- **Plan:** follows the saved steps in order. Building and research steps specify a target level. A queued upgrade does not complete a step: the runner waits until that level is visible. Resource steps wait for an amount; wait steps count seconds from when the step is reached.
- **Auto:** restores power with Solar Plant upgrades up to the configured ceiling, then follows the plan. This carries forward the earlier power/research controller. The full economy optimizer is not connected to a complete live economy reader yet.

Every upgrade checks its visible title, level, cost, queue state, resource reserves and per-resource cost limit. An insufficient balance waits until a later check. A durable intent journal is written before the click; an unknown result blocks later actions instead of repeating the click.

Supported building screens: Solar Plant, Gas Storage and Research Lab. Supported research: Energy, Laser, Ion, Hyperspace, Computer, Espionage, Astrophysics and Combustion Drive. The selector lists only these calibrated targets. The adapter uses the verified 470 by 912 colony layout, visible rendered control labels and OCR fallback. The resource header is read from rendered labels to preserve energy minus signs.

## Timing, rules and presets

The check interval is 10 seconds or more. Start and stop fields accept local dates/times and save an explicit timezone. Closing EOG leaves a started worker running. A scheduled stop or **Pause** ends it. A future schedule leaves its account scanning until the start time, then requests the account handoff.

Metal, crystal, gas, energy and safe nebula run rules raise local alerts at `<=` or `>=` thresholds. OCR abbreviations are treated as intervals; the full interval must satisfy the rule. Cooldowns prevent the same threshold producing an alert every check. Alerts and confirmed actions appear in **Live status**, with the current step, next check and latest screenshot. The screenshot is overwritten, rather than archived per check.

Save a preset to reuse mode, limits, plan steps and watch rules. Presets exclude account, colony, profile ID and schedule. Load one into a profile, review it and save. Changing a plan resets its step index; other edits retain the existing index. Profiles must be paused to edit or delete.

**Owned Gamma rule:** choose **Safe nebula runs**, `<= 0`, and **Use owned Gamma**. In Plan or Auto mode, EOG checks the actual nebula counter, returns to the verified colony, reads the owned Gamma inventory, verifies quantity one and the final item-use confirmation, then confirms both the inventory decrement and restored safe runs. Watch mode only alerts. The default limit is one Gamma per account in a rolling 24 hours, shared across its profiles and preserved across restarts. A cooldown also applies. Store purchases are disabled; an empty inventory produces an alert. An uncertain result stops further actions.

Safe-run checks visit position 21 only to inspect its counter; scanning still skips that fixed nebula slot. Returning to the colony requires its coordinate and Go here control to be visible in the owned-planet list; otherwise the profile stops without guessing a destination.

## Scanner handoff and recovery

An automation account reservation pauses only that account's scanner process. Its galaxy assignment and slot receipts remain intact. Other scanners continue. The automation worker waits for the supervisor to acknowledge the handoff before signing in, and releases the reservation after closing its browser. The scanner then resumes from its saved slots.

There is one OS file lock and action journal per account, shared across that account's profiles. A second profile cannot start on an already reserved account. Unresponsive workers are shown after three minutes without a status update; use Pause before restarting. A stale reservation can be released by Pause once the worker no longer holds the account lock. An uncertain action remains blocked in the journal and requires inspection/reconciliation; do not delete the journal to force a retry.

## Validation

Tests cover ordered completion, resource waits, reserves, watch-only behavior, cooldowns, persistent progress, schedule validation, preset privacy, account locks, scanner handoff and action transactions. UI verification covers blank new profiles, available targets, step reordering and form round-trips without starting workers or changing saved profiles. Live read-only checks on September 9, 2026 verified account/colony identity, all three building screens, all eight research rows (scrolling the clipped bottom rows into view), the owned Gamma count, the quantity-one dialog and final confirmation, and a complete scheduled Watch cycle that checked safe runs and returned to the correct colony. Gamma confirmation was cancelled; no upgrades or items were spent during validation. Post-action success and uncertain-result handling are covered by simulated transaction tests; actual spending was not exercised.
