# Config UI — Playwright sweep results

- Date: 2026-05-28T14:14:42.467Z
- Target: C:/Projects/ai-playbook/config-ui  (config-ui at repo root after move; identical to GTM-Advisor copy pre-move)
- Playwright: 1.60.0
- Chromium: 148.0.7778.96

## Scenario A: file://

_No findings._

## Scenario B: http://localhost:8765

_No findings — every control behaved as expected._

## Console / network log digest

```
[A requestfailed] file:///C:/Projects/ai-playbook/applied-config.js — net::ERR_FILE_NOT_FOUND
[A console.error] Failed to load resource: net::ERR_FILE_NOT_FOUND
[A requestfailed] file:///C:/Projects/.ai-playbook-state/files-state.js — net::ERR_FILE_NOT_FOUND
[A console.error] Failed to load resource: net::ERR_FILE_NOT_FOUND
[A requestfailed] file:///C:/Projects/ai-playbook/dashboard-data.js — net::ERR_FILE_NOT_FOUND
[A console.error] Failed to load resource: net::ERR_FILE_NOT_FOUND
[A console.error] Fetch API cannot load file:///C:/Projects/ai-playbook/config-ui/rules-inventory.json. URL scheme "file" is not supported.
[A console.error] Fetch API cannot load file:///C:/Projects/ai-playbook/config-ui/features-inventory.json. URL scheme "file" is not supported.
[A console.error] Fetch API cannot load file:///C:/Projects/ai-playbook/config-ui/global-flags-inventory.json. URL scheme "file" is not supported.
[A console.error] Fetch API cannot load file:///C:/Projects/ai-playbook/config-ui/skills-inventory.json. URL scheme "file" is not supported.
[A console.error] Fetch API cannot load file:///C:/Projects/ai-playbook/config-ui/mcps-inventory.json. URL scheme "file" is not supported.
[A console.error] Fetch API cannot load file:///C:/Projects/ai-playbook/config-ui/defaults.json. URL scheme "file" is not supported.
[B console.error] Failed to load resource: the server responded with a status of 404 (File not found)
[B requestfailed] http://localhost:8765/applied-config.js — net::ERR_ABORTED
[B console.error] Failed to load resource: the server responded with a status of 404 (File not found)
[B requestfailed] http://localhost:8765/dashboard-data.js — net::ERR_ABORTED
[B console.error] Failed to load resource: the server responded with a status of 404 (File not found)
[B requestfailed] http://localhost:8765/.ai-playbook-state/files-state.js — net::ERR_ABORTED
```

## Suggested fix anchors (informational, not in this plan)

- `config-ui/app.js:29-35` — wrap each required fetch with `.catch(emptyFallback)` like skills/mcps already do.
- `config-ui/app.js:80-83` — degrade gracefully; do not leave `state` null on init error.

_Severity: blocker (UI dead) | broken (control misbehaves) | degraded (works but suboptimal) | cosmetic (visual only)._