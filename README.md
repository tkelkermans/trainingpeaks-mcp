# TrainingPeaks MCP Server

<a href="https://glama.ai/mcp/servers/@JamsusMaximus/TrainingPeaks-MCP">
  <img width="380" height="200" src="https://glama.ai/mcp/servers/@JamsusMaximus/TrainingPeaks-MCP/badge" alt="TrainingPeaks MCP server" />
</a>

Connect TrainingPeaks to Claude and other AI assistants via the Model Context Protocol (MCP). Query workouts, build structured intervals, manage your calendar, track fitness trends, and control your training through natural conversation.

**No API approval required.** The official Training Peaks API is approval-gated, but this server uses secure cookie authentication that any user can set up in minutes. Your cookie is stored in your system keyring, never transmitted anywhere except to TrainingPeaks.

## What You Can Do

![Example conversation with Claude using TrainingPeaks MCP](docs/images/screenshot.png)

Ask your AI assistant things like:
- "Build me a 4x8min threshold session for Tuesday with warm-up and cool-down"
- "Schedule my mobility session for April 14, 2026 at 16:45"
- "Compare my FTP progression this year vs last year"
- "Copy last week's long ride to this Saturday"
- "Move my 6am Tuesday ride to Thursday" (keeps the 6am start time automatically)
- "Log my weight at 74.5kg and sleep at 7.5 hours"
- "What's my weekly TSS so far? Am I on track for my ATP target?"
- "Show my race calendar and how many weeks until my A race"
- "Set my FTP to 310 and update my power zones"
- "Add a calendar note for next Monday: rest day, travel"

## Tools (65)

### Workouts
| Tool | Description |
|------|-------------|
| `tp_get_workouts` | List workouts in a date range (max 90 days) |
| `tp_get_workout` | Get full details for a single workout |
| `tp_create_workout` | Create a workout with optional simplified interval structure or native structured_workout payload, auto-computed IF/TSS, and optional planned start time |
| `tp_update_workout` | Update any field of an existing workout, including simplified structured intervals, native structured_workout payload, and planned start time |
| `tp_delete_workout` | Delete a workout |
| `tp_copy_workout` | Copy a workout to a new date (preserves structure and planned fields) |
| `tp_reorder_workouts` | Reorder workouts on a given day |
| `tp_pair_workout` | Pair a completed workout with a planned workout (merges into one) |
| `tp_unpair_workout` | Unpair a workout (splits into separate completed and planned workouts) |
| `tp_validate_structure` | Validate interval structure without creating a workout |
| `tp_get_workout_comments` | Get comments on a workout |
| `tp_add_workout_comment` | Add a comment to a workout |
| `tp_get_workout_note` | Get the private workout note for a workout |
| `tp_set_workout_note` | Set or update the private workout note |

### Workout Files
| Tool | Description |
|------|-------------|
| `tp_upload_workout_file` | Upload a workout file (.fit/.tcx/.gpx) to an existing workout |
| `tp_download_workout_file` | Download a workout file by file_id |
| `tp_delete_workout_file` | Delete a workout file by file_id |

### Analysis & Performance
| Tool | Description |
|------|-------------|
| `tp_analyze_workout` | Detailed analysis with time-series data, zones, and laps |
| `tp_get_peaks` | Power PRs (5s-90min) and running PRs (400m-marathon) |
| `tp_get_workout_prs` | PRs set during a specific session |
| `tp_get_fitness` | CTL, ATL, and TSB trend (fitness, fatigue, form) |
| `tp_get_weekly_summary` | Combined workouts + fitness for a week with totals |
| `tp_get_atp` | Annual Training Plan - weekly TSS targets, periods, races |

### Athlete Settings
| Tool | Description |
|------|-------------|
| `tp_get_athlete_settings` | Get FTP, thresholds, zones, profile |
| `tp_update_ftp` | Update FTP and recalculate the default power zones |
| `tp_update_hr_zones` | Update heart rate zones |
| `tp_update_speed_zones` | Update run/swim pace zones |
| `tp_update_nutrition` | Update daily planned calories |
| `tp_get_pool_length_settings` | Get pool length options |

### Health Metrics
| Tool | Description |
|------|-------------|
| `tp_log_metrics` | Log weight, HRV, sleep, steps, SpO2, pulse, RMR, injury |
| `tp_get_metrics` | Get health metrics for a date range |
| `tp_get_nutrition` | Get nutrition data for a date range |

### Equipment
| Tool | Description |
|------|-------------|
| `tp_get_equipment` | List bikes and shoes with distances |
| `tp_create_equipment` | Add a bike or shoe |
| `tp_update_equipment` | Update equipment details, retire |
| `tp_delete_equipment` | Delete equipment |

### Events & Calendar
| Tool | Description |
|------|-------------|
| `tp_get_focus_event` | Get A-priority focus event with goals |
| `tp_get_next_event` | Get nearest future event |
| `tp_get_events` | List events in a date range |
| `tp_create_event` | Add a race/event with priority (A/B/C) and CTL target |
| `tp_update_event` | Update event details, attach workouts as legs (multisport) |
| `tp_delete_event` | Delete an event |
| `tp_create_note` | Create a calendar note |
| `tp_list_notes` | List calendar notes for a date range |
| `tp_get_note` | Get a calendar note by ID |
| `tp_update_note` | Update title, description, date or visibility of a note |
| `tp_delete_note` | Delete a calendar note |
| `tp_get_note_comments` | List all comments on a note |
| `tp_add_note_comment` | Add a comment to a note |
| `tp_get_availability` | List unavailable/limited periods |
| `tp_create_availability` | Mark dates as unavailable or limited |
| `tp_delete_availability` | Remove availability entry |

### Workout Library
| Tool | Description |
|------|-------------|
| `tp_get_libraries` | List workout library folders |
| `tp_get_library_items` | List templates in a library |
| `tp_get_library_item` | Get full template details including structure |
| `tp_create_library` | Create a library folder |
| `tp_delete_library` | Delete a library folder |
| `tp_create_library_item` | Save a workout template |
| `tp_update_library_item` | Edit a template |
| `tp_schedule_library_workout` | Schedule a template to a calendar date |

### Reference & Auth
| Tool | Description |
|------|-------------|
| `tp_get_workout_types` | List all sport types and subtypes with IDs |
| `tp_get_profile` | Get athlete profile |
| `tp_auth_status` | Check authentication status |
| `tp_refresh_auth` | Re-authenticate from browser cookie |
| `tp_list_athletes` | List athletes available to this account (coach accounts) |

---

## Setup Options

The setup below installs the server locally and runs it over stdio (the default, no network exposure). If you'd rather run it remotely for claude.ai, Claude mobile, ChatGPT, or Grok, see **Option C: Hosted (Vercel)** below, which jumps to the [Hosted deployment](#hosted-deployment-vercel) section.

### Option A: Auto-Setup with Claude Code

If you have [Claude Code](https://claude.ai/code), paste this prompt:

```
Set up the TrainingPeaks MCP server from https://github.com/JamsusMaximus/trainingpeaks-mcp - clone it, create a venv, install it, then walk me through getting my TrainingPeaks cookie from my browser and run tp-mcp auth. Finally, add it to my Claude Desktop config.
```

Claude will handle the installation and guide you through authentication step-by-step.

### Option B: Manual Setup

#### Step 1: Install

```bash
git clone https://github.com/JamsusMaximus/trainingpeaks-mcp.git
cd trainingpeaks-mcp
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

#### Step 2: Authenticate

**Option A: Auto-extract from browser (easiest)**

If you're logged into TrainingPeaks in your browser:

```bash
pip install -e ".[browser]"  # One-time: install browser support against your clone
tp-mcp auth --from-browser chrome  # Or: firefox, safari, edge, chromium, brave, opera, auto
```

> **macOS note:** Reading a browser's cookie database requires **Full Disk Access** for your terminal (System Settings > Privacy & Security > Full Disk Access), plus a Keychain prompt. Browser cookies are encrypted and require permission to read. If you can't grant Full Disk Access, use Option B (manual cookie entry) instead.

**Option B: Manual cookie entry**

1. Log into [app.trainingpeaks.com](https://app.trainingpeaks.com)
2. Open DevTools (`F12`) -> **Application** tab -> **Cookies**
3. Find `Production_tpAuth` and copy its value
4. Run `tp-mcp auth` and paste when prompted

**Other auth commands:**
```bash
tp-mcp auth-status  # Check if authenticated
tp-mcp auth-clear   # Remove stored cookie
```

#### Step 3: Add to Claude Desktop

Run this to get your config snippet:

```bash
tp-mcp config
```

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows) and paste it inside `mcpServers`. Example with multiple servers:

```json
{
  "mcpServers": {
    "some-other-server": {
      "command": "npx",
      "args": ["some-other-mcp"]
    },
    "trainingpeaks": {
      "command": "/Users/you/trainingpeaks-mcp/.venv/bin/tp-mcp",
      "args": ["serve"]
    }
  }
}
```

Restart Claude Desktop. You're ready to go!

### Option C: Hosted (Vercel)

Prefer a remote server you can reach from claude.ai, Claude mobile, ChatGPT, or Grok? Skip the local install and deploy to Vercel instead - see [Hosted deployment (Vercel)](#hosted-deployment-vercel) below.

---

## Structured Workouts

Create workouts with full interval structure. The server auto-computes duration, IF, and TSS from the structure:

```json
{
  "date": "2026-03-01",
  "sport": "Bike",
  "title": "Sweet Spot Intervals",
  "structure": {
    "primaryIntensityMetric": "percentOfFtp",
    "steps": [
      {"name": "Warm Up", "duration_seconds": 600, "intensity_min": 40, "intensity_max": 55, "intensityClass": "warmUp"},
      {"type": "repetition", "reps": 4, "steps": [
        {"name": "Sweet Spot", "duration_seconds": 480, "intensity_min": 88, "intensity_max": 93, "intensityClass": "active"},
        {"name": "Recovery", "duration_seconds": 120, "intensity_min": 50, "intensity_max": 60, "intensityClass": "rest"}
      ]},
      {"name": "Cool Down", "duration_seconds": 600, "intensity_min": 40, "intensity_max": 55, "intensityClass": "coolDown"}
    ]
  }
}
```

The LLM builds this JSON naturally from conversation - just say "build me 4x8min sweet spot with 2min rest".

You can use the same simplified `structure` object with `tp_update_workout`:

```json
{
  "workout_id": "3658666303",
  "duration_minutes": 57,
  "tss_planned": 62.3,
  "structure": {
    "primaryIntensityMetric": "percentOfThresholdHr",
    "steps": [
      {"name": "Warm-up", "duration_seconds": 900, "intensity_min": 65, "intensity_max": 80, "intensityClass": "warmUp"},
      {"type": "repetition", "name": "4x5min controlled tempo", "reps": 4, "steps": [
        {"name": "Interval", "duration_seconds": 300, "intensity_min": 89, "intensity_max": 94, "intensityClass": "active"},
        {"name": "Jog recovery", "duration_seconds": 180, "intensity_min": 65, "intensity_max": 83, "intensityClass": "rest"}
      ]},
      {"name": "Cool-down", "duration_seconds": 600, "intensity_min": 65, "intensity_max": 80, "intensityClass": "coolDown"}
    ]
  }
}
```

If `duration_minutes` and `tss_planned` are omitted, they are derived from the structure. If you pass them explicitly, they override the derived values.

For advanced round-trip use cases, `tp_create_workout` and `tp_update_workout` also accept a native `structured_workout` payload in TrainingPeaks builder format. When a workout already has a native structure, `tp_get_workout` returns it as `structured_workout`.

Workout comments are exposed via `tp_get_workout()["workout_comments"]` or `tp_get_workout_comments()`. The older top-level `coach_comments` and `athlete_comments` fields are no longer returned by `tp_get_workout`.

```json
{
  "workout_id": "3658666303",
  "structured_workout": {
    "structure": [],
    "polyline": [],
    "primaryLengthMetric": "duration",
    "primaryIntensityMetric": "percentOfFtp",
    "primaryIntensityTargetOrRange": "range"
  }
}
```

Use either `structure` or `structured_workout` in a single create/update call, not both - passing both raises a validation error. Reach for `structured_workout` when you already have a native TP payload to preserve losslessly (e.g. you called `tp_get_workout` on a workout that returned a `structured_workout` field, edited it, and want to save it back exactly as TrainingPeaks built it). Use the simplified `structure` for everything else, including anything you're building from conversation - it's what `tp_validate_structure` checks, and what auto-computes duration/IF/TSS. `tp_validate_structure` does not validate native `structured_workout` payloads.

For planned workout scheduling, `tp_create_workout` and `tp_update_workout` accept:

- `YYYY-MM-DD` for all-day planning on a calendar date
- `YYYY-MM-DDTHH:MM:SS` for a planned start time on that date

TrainingPeaks stores planned workout times separately from the calendar day. Internally this means:

- `workoutDay` stays at midnight for the selected date
- `startTimePlanned` stores the planned start time
- planned end time is derived from `startTimePlanned + totalTimePlanned`

**Moving a workout to a new day preserves its time-of-day.** If a workout already has a planned start time and you call `tp_update_workout` with just a bare `YYYY-MM-DD` date (no time), the existing time-of-day carries over to the new date - TrainingPeaks doesn't reset it to midnight. To change both the day and the time in one call, pass the full `YYYY-MM-DDTHH:MM:SS` instead.

Example with a planned start time:

```json
{
  "date": "2026-04-14T16:45:00",
  "sport": "Strength",
  "title": "Core & Mobility",
  "duration_minutes": 60,
  "description": "Core-Stabilisation und Dehnung."
}
```

## What is MCP?

[Model Context Protocol](https://modelcontextprotocol.io) is an open standard for connecting AI assistants to external data sources. MCP servers expose tools that AI models can call to fetch real-time data, enabling assistants like Claude to access your Training Peaks account through natural language.

## Security

**TL;DR: Your cookie is encrypted on disk, exchanged for short-lived OAuth tokens, never shown to Claude, and only ever sent to TrainingPeaks. By default the server uses stdio and opens no network ports; an opt-in HTTP transport exists for hosted/remote use and is protected by a required `MCP_AUTH_SECRET`.**

This server is designed with defence-in-depth. Your TrainingPeaks session cookie is sensitive - it grants access to your training data - so we treat it accordingly.

> **Write access:** v2.0 adds full calendar management (create, update, delete workouts, events, notes, equipment, settings). All mutations go through Pydantic validation. The server cannot access billing or payment info.

### Cookie Storage

| Platform | Primary Storage | Fallback |
|----------|----------------|----------|
| macOS | System Keychain | Encrypted file |
| Windows | Windows Credential Manager | Encrypted file |
| Linux | Secret Service (GNOME/KDE) | Encrypted file |

Your cookie is **never** stored in plaintext. The encrypted file fallback uses AES-256-GCM authenticated encryption with a PBKDF2-derived key (600,000 iterations) and a machine-specific salt.

### Cookie Never Leaks to AI

The AI assistant (Claude) **never sees your cookie value**. Multiple layers ensure this:

1. **Return value sanitisation**: Tool results are scrubbed for any keys containing `cookie`, `token`, `auth`, `credential`, `password`, or `secret` before being sent to Claude
2. **Masked repr()**: The `BrowserCookieResult` and `CredentialResult` classes override `__repr__` to show `cookie=<present>` instead of the actual value
3. **Sanitised exceptions**: Error messages use only exception type names, never full messages that could contain data
4. **No logging**: Cookie values are never written to any log

### Domain Hardcoding (Cannot Be Changed)

The browser cookie extraction **only** accesses `.trainingpeaks.com`:

```python
# From src/tp_mcp/auth/browser.py - HARDCODED, not a parameter
cj = func(domain_name=".trainingpeaks.com")
```

Claude cannot modify this via tool parameters. The only parameter is `browser` (chrome/firefox/etc), not the domain. To change the domain would require modifying the source code.

### Network Exposure

By default the MCP server communicates with Claude Desktop over **stdio** (stdin/stdout) with no network exposure - no HTTP server, no open ports, no remote access.

An optional HTTP transport is available for hosted deployments (`tp-mcp serve --transport http`, and the Vercel deployment). It **fails closed**: the app refuses to start unless `MCP_AUTH_SECRET` is set (binding to a non-localhost host without it raises an error). When the secret is set, every request is authenticated with a constant-time comparison (`hmac.compare_digest`) - either via the secret URL path segment `/mcp/<secret>` or an `Authorization: Bearer <secret>` header on bare `/mcp`. When self-hosted, that URL secret is the credential, so treat the endpoint URL like a password and prefer the Bearer header where your client supports it. See the [Hosted deployment](#hosted-deployment-vercel) section for details.

### Open Source

This server is fully open source. You can audit every line of code before running it. Key security files:
- [`src/tp_mcp/auth/browser.py`](src/tp_mcp/auth/browser.py) - Cookie extraction with hardcoded domain
- [`src/tp_mcp/auth/encrypted.py`](src/tp_mcp/auth/encrypted.py) - AES-256-GCM credential encryption
- [`src/tp_mcp/tools/_validation.py`](src/tp_mcp/tools/_validation.py) - Pydantic input validation
- [`src/tp_mcp/tools/refresh_auth.py`](src/tp_mcp/tools/refresh_auth.py) - Result sanitisation
- [`tests/test_tools/test_refresh_auth_security.py`](tests/test_tools/test_refresh_auth_security.py) - Security tests

## Authentication Flow

The server uses a two-step authentication process:

1. **Cookie to OAuth Token**: Your stored cookie is exchanged for a short-lived OAuth access token (expires in 1 hour)
2. **Automatic Refresh**: Tokens are cached in memory and automatically refreshed before expiry

This means:
- You only need to authenticate once with `tp-mcp auth`
- API calls use proper Bearer token auth, not cookies
- If your session cookie expires (typically after several weeks), use `tp_refresh_auth` in Claude or run `tp-mcp auth` again

In **hosted (HTTP) mode** the cookie doesn't come from the keyring - it's read from the `TP_AUTH_COOKIE` environment variable and refreshed with `tp-mcp push-cookie` rather than `tp-mcp auth`. See the [Hosted deployment](#hosted-deployment-vercel) section.

## CLI reference

All commands: `tp-mcp <command> [options]`. Run `tp-mcp help` any time for the built-in summary.

| Command | Flags | Description |
|---|---|---|
| `auth` | `--from-browser <browser>` | Authenticate with TrainingPeaks. With no flag, prompts for the `Production_tpAuth` cookie manually (hidden input). With `--from-browser`, extracts it from a local browser instead. `<browser>` is one of `chrome`, `firefox`, `safari`, `edge`, `chromium`, `brave`, `opera`, or `auto` (tries all supported browsers in turn). Requires macOS Full Disk Access for the terminal when reading from a browser. |
| `auth-status` | - | Checks whether a stored cookie exists and is still valid; prints email, athlete ID, and storage backend. Exit code 0 if authenticated, 1 otherwise. |
| `auth-clear` | - | Deletes the stored credential (keychain or encrypted file). |
| `config` | - | Prints a ready-to-paste Claude Desktop `mcpServers` JSON snippet pointing at the local `tp-mcp` binary with `args: ["serve"]`. |
| `serve` | `--transport stdio\|http` (default `stdio`)<br>`--host <host>` (default `127.0.0.1`, http only)<br>`--port <port>` (default `8000`, http only) | Starts the MCP server. `stdio` is the default and matches all prior behavior (what Claude Desktop uses via `config`). `http` starts a Starlette/uvicorn ASGI server exposing streamable-HTTP MCP at `/mcp` and a health check at `/`. The http transport **fails closed**: if `MCP_AUTH_SECRET` is unset and `--host` is anything other than `127.0.0.1`/`localhost`/`::1`, it refuses to start; on localhost with no secret it starts unauthenticated (local dev only) and prints a warning. When `MCP_AUTH_SECRET` is set, requests must include the secret either as the path segment `/mcp/<secret>` or as `Authorization: Bearer <secret>` on bare `/mcp` (compared with `hmac.compare_digest`). |
| `push-cookie` | `--from-browser <browser>` (default `chrome` if neither source flag given)<br>`--from-stored`<br>`--target <env>` (default `production`) | Extracts a fresh TrainingPeaks cookie and pushes it to Vercel as the `TP_AUTH_COOKIE` env var, then - only when `--target production` - runs `vercel deploy --prod --yes` to bake it into the live deployment. `--from-browser` and `--from-stored` are **mutually exclusive**; `--from-stored` reads the cookie already saved locally via `tp-mcp auth`, avoiding the browser-extraction Full Disk Access requirement entirely. Requires the `vercel` CLI on `PATH`. Validates the cookie before pushing and aborts if it's invalid. |
| `schedule` | - | Prints (to stdout) a macOS `launchd` plist that runs `tp-mcp push-cookie --from-browser chrome` every Monday at 09:00, plus setup instructions (to stderr). The scheduled job uses browser extraction, so it needs Full Disk Access too. |
| `help` (also `--help`, `-h`, or no args) | - | Prints command/flag summary and usage examples. |

```bash
tp-mcp auth                              # Manual cookie entry
tp-mcp auth --from-browser auto          # Auto-detect browser
tp-mcp serve                             # stdio (default) - what Claude Desktop uses
tp-mcp serve --transport http --port 8000
MCP_AUTH_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))') \
  tp-mcp serve --transport http --host 0.0.0.0 --port 8000
tp-mcp push-cookie --from-browser chrome
tp-mcp push-cookie --from-stored         # no browser access needed
tp-mcp push-cookie --target preview      # pushes cookie but skips redeploy
tp-mcp schedule > ~/Library/LaunchAgents/com.trainingpeaks-mcp.refresh.plist
launchctl load ~/Library/LaunchAgents/com.trainingpeaks-mcp.refresh.plist
```

## Development

The repo ships a committed `uv.lock` that pins dependencies, so [uv](https://docs.astral.sh/uv/) is the recommended dependency manager:

```bash
uv sync --extra dev
uv run pytest tests/ -v
uv run mypy src/
uv run ruff check src/
```

The equivalent pip-based flow (matching CI) also works:

```bash
pip install -e ".[dev]"
pytest tests/ -v
mypy src/
ruff check src/
```

## Licence

MIT

---

## Hosted deployment (Vercel)

The setup above runs the server as a local stdio subprocess, so it's only reachable from the machine it's installed on. If you'd rather use TrainingPeaks from claude.ai, Claude mobile, Claude Code, ChatGPT, or Grok, you can deploy the server to Vercel instead. It runs there over the streamable HTTP transport behind a secret URL, and is designed for single-user use (your own TrainingPeaks account, your own deployment).

### Deploy

Both env vars (`MCP_AUTH_SECRET` and `TP_AUTH_COOKIE`) must exist **before** the first deploy that serves traffic - the app fails closed, so a deploy without `MCP_AUTH_SECRET` returns 500 on every request.

```bash
# one-time setup
vercel link                                # links this dir to a Vercel project (see GitHub note below)
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'  # -> MCP_AUTH_SECRET
vercel env add MCP_AUTH_SECRET production  # paste the value from the line above
tp-mcp push-cookie --from-browser chrome   # extracts + validates + uploads TP_AUTH_COOKIE, then deploys
```

`tp-mcp push-cookie --target production` (the default) already runs `vercel deploy --prod --yes` after uploading the cookie, so that command deploys for you - there is no `vercel redeploy --prod`. If you set the secret but haven't pushed a cookie yet, run one explicit `vercel deploy --prod --yes` for the very first deploy; afterwards `push-cookie` handles it.

> **`vercel link` and GitHub:** `vercel link` offers to connect a GitHub repo. That connection is **optional** - it only enables push-to-deploy, and `vercel deploy --prod` works without it. It also **fails if you lack write access to the repo** (e.g. you cloned someone else's project). If so, either skip it, or fork the repo, authorize the Vercel GitHub App at <https://github.com/settings/installations>, and run `vercel git connect <your-fork-url> --yes`.

Your endpoint is `https://<public-alias>/mcp/<MCP_AUTH_SECRET>`. Vercel mints **several aliases per deployment**, and not all are public: the short project alias (e.g. `https://<project>-<hash>.vercel.app`) is usually public and works, while the team-scoped alias (`https://<project>-<team>.vercel.app`) often sits behind Vercel deployment protection and 302-redirects to an SSO page that silently breaks MCP clients. Find your real public alias with `vercel inspect <deployment-url>` (look at the Aliases list) or `vercel ls`, then verify it (see below). Treat the full URL like a password.

### Security model

The secret in the URL path acts as a password - it's compared with a constant-time check (`hmac.compare_digest`), so it can't be leaked via timing attacks. If your client supports custom headers instead, you can call `/mcp` with `Authorization: Bearer <secret>` rather than putting the secret in the path.

To rotate the secret, set a new `MCP_AUTH_SECRET` env var and redeploy - the old URL stops working immediately.

Note that because the secret lives in the URL, it will appear in Vercel's request logs. This is an accepted tradeoff for a single-user deployment; if that's not acceptable for your use case, use the Bearer header form instead and avoid the path variant.

### Verify your deployment

Before pointing a client at your endpoint, confirm the alias is public and the auth works. Replace `<alias>` with your public alias and `<secret>` with your `MCP_AUTH_SECRET`:

```bash
# 1. Health check - should be 200 with {"status":"ok","service":"trainingpeaks-mcp"}
curl https://<alias>/

# 2. Wrong secret - should be 401 {"error":"unauthorized"}
curl -X POST https://<alias>/mcp/wrong \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'

# 3. Correct secret - should be 200 and list the tools
curl -X POST https://<alias>/mcp/<secret> \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

If the health check redirects (302) to a Vercel/SSO login page, you're hitting a protected alias - pick the public one from `vercel inspect`/`vercel ls`, or disable deployment protection for the project.

### Connect your client

- **claude.ai**: Settings -> Connectors -> Add custom connector -> paste your endpoint URL.
- **Claude Code**: `claude mcp add --transport http trainingpeaks <url>`
- **ChatGPT**: Settings -> Apps & Connectors (developer mode) -> Add MCP server -> paste your endpoint URL.
- **Grok**: Settings -> Connectors -> add a remote MCP URL.

### Refreshing the cookie

TrainingPeaks' login form is protected by reCAPTCHA, so the server can't log itself in - the `Production_tpAuth` cookie has to be minted from a real, already-logged-in browser (or pasted manually) and pushed up. `tp-mcp push-cookie` does the whole thing in one command: it validates the cookie against TrainingPeaks, uploads it as the `TP_AUTH_COOKIE` env var, and (for `--target production`, the default) runs `vercel deploy --prod --yes` to bake it in. Use `--target preview` or `--target development` to push the env var without deploying. It supports two sources - pick one:

```bash
tp-mcp push-cookie --from-browser chrome   # chrome/firefox/safari/edge/chromium/brave/opera/auto, validates + uploads + deploys
tp-mcp push-cookie --from-stored           # reuses the cookie already stored by `tp-mcp auth`, validates + uploads + deploys
```

**If browser extraction fails**: on macOS, reading a browser's cookie database requires Full Disk Access for your terminal (System Settings > Privacy & Security > Full Disk Access). If you can't or don't want to grant that, run `tp-mcp auth` once to paste the cookie manually, then use `tp-mcp push-cookie --from-stored` instead - no browser access needed.

To make this hands-off, schedule it to run weekly:

```bash
tp-mcp schedule > ~/Library/LaunchAgents/com.trainingpeaks-mcp.refresh.plist
launchctl load ~/Library/LaunchAgents/com.trainingpeaks-mcp.refresh.plist
```

The scheduled job uses browser extraction (`--from-browser`), so the process running it (the `tp-mcp` binary's parent, e.g. `launchd`) needs Full Disk Access granted, or the weekly run will fail. If you haven't granted that (or don't want to), skip the schedule and refresh manually instead whenever the cookie expires: `tp-mcp auth` once, then `tp-mcp push-cookie --from-stored`.

### Local HTTP mode

You can also run the HTTP transport locally instead of deploying:

```bash
MCP_AUTH_SECRET=devsecret tp-mcp serve --transport http --port 8000
```

Binding to `localhost` works without a secret configured; binding to any non-localhost host refuses to start unless `MCP_AUTH_SECRET` is set.

### Known limitations

- File tools (`tp_download_workout_file`, `tp_analyze_workout` artifacts) write to the function's ephemeral tmp directory, so the paths they return are meaningless to a remote client - prefer base64 upload where the client supports it.
- Vercel enforces a 4.5 MB request/response body cap.
- When the cookie expires, tool calls fail with `AUTH_EXPIRED` - just run `tp-mcp push-cookie` again.
- Vercel's deployment protection blocks MCP clients with an SSO page (a 302 redirect). This affects both preview deployments **and** team-scoped production aliases - "use the production deployment" isn't enough on its own if you hit a protected alias. Pick and test your public alias with `vercel inspect`/`vercel ls` (see [Deploy](#deploy) and [Verify your deployment](#verify-your-deployment)), or disable deployment protection for the project.
