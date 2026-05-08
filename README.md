# Baccarat WebSocket Capture

Local Playwright collector for Baccarat table WebSocket results and road updates.

## What It Captures

- Live game results from WebSocket `GameInfo` messages.
- `roadInfo` updates for table roads.
- Output files under `bac_capture/`:
  - `events.jsonl`
  - `road_store.json`

Runtime data is ignored by git because it may contain session-specific tokens.

## Setup

```powershell
pip install -r requirements.txt
playwright install chromium
```

## Run

```powershell
python bac_auto_capture.py
```

The browser uses the persistent profile in `bac_profile/`. Log in once in that browser window and enter the target Baccarat table. The collector will reuse that profile on later runs.

Optional environment variables:

```powershell
$env:BAC_USERNAME="your_username"
$env:BAC_PASSWORD="your_password"
$env:BAC_TABLE="1008"
python bac_auto_capture.py
```

Note: captcha/slider verification must be completed manually in the browser when the site requires it. The collector does not bypass anti-bot checks.

## API Server

Run locally:

```powershell
uvicorn api_server:app --host 0.0.0.0 --port 8000
```

Endpoints:

```text
GET /health
GET /road
GET /road/1008
GET /latest
GET /latest?table_id=1008
GET /events?limit=100
```

Railway uses `Procfile` / `railway.json` and starts the API with:

```bash
uvicorn api_server:app --host 0.0.0.0 --port $PORT
```

To also start the Playwright collector inside Railway, set:

```text
RUN_COLLECTOR=1
BAC_TABLE=1008
```

Without `RUN_COLLECTOR=1`, Railway runs the API only and serves whatever data exists in `bac_capture/`.

## Current Mapping

```text
winner=1 -> BANKER
winner=2 -> PLAYER
winner=3 -> TIE
winner=-1 -> DEALING
```
