from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
import httpx
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional
import math

app = FastAPI(title="WinGo Lottery API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Constants ───────────────────────────────────────────────────────────────

DRAW_BASE = "https://draw.ar-lottery01.com"

GAME_MAP = {
    "wingo": "WinGo",
    "k3": "K3",
    "5d": "5D",
    "trxwin": "TrxWin",
}

DURATION_MAP = {
    "30s":  {"key": "30S",   "folder": "WinGo_30S",  "seconds": 30},
    "1min": {"key": "1M",    "folder": "WinGo_1M",   "seconds": 60},
    "3min": {"key": "3M",    "folder": "WinGo_3M",   "seconds": 180},
    "5min": {"key": "5M",    "folder": "WinGo_5M",   "seconds": 300},
    "10min":{"key": "10M",   "folder": "WinGo_10M",  "seconds": 600},
}

# ─── Period ID Logic ─────────────────────────────────────────────────────────
# issueNumber format: YYYYMMDD + "10" + NNNNNNN
# NNNNNNN = sequential draw number within that day for that market
# 30S  → ~2880 draws/day  → padded to 7 digits
# 1Min → ~1440 draws/day
# 3Min → ~480  draws/day
# etc.
# Draw day starts at 00:00:00 UTC+8 (IST-like, Asia/Dhaka = UTC+6 but platform uses UTC+8)

def get_platform_time() -> datetime:
    """Platform uses UTC+8 timezone."""
    return datetime.now(timezone(timedelta(hours=8)))

def calculate_period_id(duration_key: str) -> dict:
    """
    Calculate current period ID matching ar-lottery01.com format.
    issueNumber = YYYYMMDD + 10 + NNNNNNN (zero-padded to 7 digits)
    """
    info = DURATION_MAP.get(duration_key)
    if not info:
        return {}

    now = get_platform_time()
    date_str = now.strftime("%Y%m%d")

    # Seconds elapsed since midnight (platform time)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_seconds = int((now - midnight).total_seconds())

    seconds = info["seconds"]
    draw_number = (elapsed_seconds // seconds) + 1  # 1-indexed

    # Format: YYYYMMDD + "10" + 7-digit sequence
    issue_number = f"{date_str}10{draw_number:07d}"

    # Time remaining in current period
    seconds_into_period = elapsed_seconds % seconds
    remaining = seconds - seconds_into_period

    # Period start/end times
    period_start = midnight + timedelta(seconds=(draw_number - 1) * seconds)
    period_end   = period_start + timedelta(seconds=seconds)

    return {
        "issueNumber": issue_number,
        "drawNumber": draw_number,
        "remainingSeconds": remaining,
        "periodStart": period_start.strftime("%Y-%m-%d %H:%M:%S"),
        "periodEnd":   period_end.strftime("%Y-%m-%d %H:%M:%S"),
        "serverTime":  now.strftime("%Y-%m-%d %H:%M:%S"),
        "timezone":    "UTC+8",
    }

# ─── Draw Data Fetcher ────────────────────────────────────────────────────────

async def fetch_draw_history(game: str, duration: str, page: int = 1) -> dict:
    info = DURATION_MAP.get(duration)
    if not info:
        return {"error": f"Unknown duration: {duration}"}

    game_name = GAME_MAP.get(game, "WinGo")
    folder    = info["folder"]
    url = f"{DRAW_BASE}/{game_name}/{folder}/GetHistoryIssuePage.json"

    params = {"pageNo": page, "pageSize": 10, "ts": int(datetime.now().timestamp() * 1000)}

    headers = {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36",
        "Referer":    "https://dkwin9.com/",
        "Origin":     "https://dkwin9.com",
    }

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(url, params=params, headers=headers)
            r.raise_for_status()
            return r.json()
        except httpx.HTTPStatusError as e:
            return {"error": f"HTTP {e.response.status_code}", "url": url}
        except Exception as e:
            return {"error": str(e), "url": url}

# ─── Color/Number Helpers ────────────────────────────────────────────────────

def get_color(number: int) -> list[str]:
    color_map = {
        0: ["red", "violet"],
        1: ["green"],
        2: ["red"],
        3: ["green"],
        4: ["red"],
        5: ["green", "violet"],
        6: ["red"],
        7: ["green"],
        8: ["red"],
        9: ["green"],
    }
    return color_map.get(number, ["red"])

def get_size(number: int) -> str:
    return "Big" if number >= 5 else "Small"

# ─── API Routes ──────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    with open("static/index.html") as f:
        return HTMLResponse(f.read())

@app.get("/api/status")
async def status():
    periods = {}
    for k in DURATION_MAP:
        periods[k] = calculate_period_id(k)
    return {
        "status": "ok",
        "serverTime": get_platform_time().strftime("%Y-%m-%d %H:%M:%S"),
        "currentPeriods": periods
    }

@app.get("/api/wingo/period")
async def wingo_period(duration: str = Query("30s", description="30s|1min|3min|5min|10min")):
    duration = duration.lower()
    data = calculate_period_id(duration)
    if not data:
        return JSONResponse({"error": "Invalid duration"}, status_code=400)
    return {"code": 0, "msg": "Succeed", "data": data}

@app.get("/api/wingo/history")
async def wingo_history(
    duration: str = Query("30s"),
    page: int = Query(1, ge=1, le=50)
):
    duration = duration.lower()
    raw = await fetch_draw_history("wingo", duration, page)

    if "error" in raw:
        # Return mock data if upstream is down
        return _mock_history(duration, page)

    # Normalize / enrich response
    items = raw.get("data", {}).get("list", [])
    enriched = []
    for item in items:
        try:
            num = int(item.get("number", 0))
        except:
            num = 0
        enriched.append({
            "issueNumber":  item.get("issueNumber", ""),
            "number":       str(num),
            "color":        item.get("color", ",".join(get_color(num))),
            "size":         get_size(num),
            "premium":      item.get("premium", str(num)),
            "sum":          item.get("sum", 0),
        })

    period = calculate_period_id(duration)

    return {
        "code": 0,
        "msg": "Succeed",
        "data": {
            "list":        enriched,
            "pageNo":      raw.get("data", {}).get("pageNo", page),
            "totalPage":   raw.get("data", {}).get("totalPage", 50),
            "totalCount":  raw.get("data", {}).get("totalCount", 500),
            "currentPeriod": period,
        }
    }

@app.get("/api/wingo/result")
async def wingo_result(duration: str = Query("30s")):
    """Latest result + current period info."""
    duration = duration.lower()
    raw = await fetch_draw_history("wingo", duration, page=1)

    period = calculate_period_id(duration)
    latest = None

    if "error" not in raw:
        items = raw.get("data", {}).get("list", [])
        if items:
            item = items[0]
            try:
                num = int(item.get("number", 0))
            except:
                num = 0
            latest = {
                "issueNumber": item.get("issueNumber", ""),
                "number":      str(num),
                "color":       item.get("color", ",".join(get_color(num))),
                "size":        get_size(num),
                "premium":     item.get("premium", str(num)),
            }

    return {
        "code": 0,
        "msg": "Succeed",
        "data": {
            "latestResult":  latest,
            "currentPeriod": period,
        }
    }

@app.get("/api/lottery/history")
async def lottery_history(
    game:     str = Query("wingo"),
    duration: str = Query("30s"),
    page:     int = Query(1, ge=1)
):
    return await wingo_history(duration=duration, page=page)

@app.get("/api/draw/history")
async def draw_history(duration: str = Query("30s"), page: int = Query(1)):
    return await wingo_history(duration=duration, page=page)

@app.get("/api/game/wingo")
async def game_wingo(duration: str = Query("30s")):
    return await wingo_result(duration=duration)

# ─── All markets synchronized ─────────────────────────────────────────────────

@app.get("/api/sync")
async def sync_all():
    """All markets periods + latest results in one call."""
    tasks = [fetch_draw_history("wingo", k, 1) for k in DURATION_MAP]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    markets = {}
    for i, key in enumerate(DURATION_MAP):
        period = calculate_period_id(key)
        raw    = results[i]
        latest = None

        if isinstance(raw, dict) and "error" not in raw:
            items = raw.get("data", {}).get("list", [])
            if items:
                item = items[0]
                try: num = int(item.get("number", 0))
                except: num = 0
                latest = {
                    "issueNumber": item.get("issueNumber", ""),
                    "number":      str(num),
                    "color":       item.get("color", ",".join(get_color(num))),
                    "size":        get_size(num),
                }

        markets[key] = {
            "duration":      DURATION_MAP[key]["seconds"],
            "currentPeriod": period,
            "latestResult":  latest,
        }

    return {
        "code": 0,
        "msg":  "Succeed",
        "data": {
            "serverTime": get_platform_time().strftime("%Y-%m-%d %H:%M:%S"),
            "markets":    markets,
        }
    }

# ─── Mock fallback ────────────────────────────────────────────────────────────

def _mock_history(duration: str, page: int):
    """Fallback mock when upstream is unavailable."""
    import random
    now = get_platform_time()
    date_str = now.strftime("%Y%m%d")
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed  = int((now - midnight).total_seconds())
    seconds  = DURATION_MAP[duration]["seconds"]
    current_draw = elapsed // seconds

    items = []
    for i in range(10):
        draw_num = current_draw - i
        if draw_num <= 0:
            break
        issue = f"{date_str}10{draw_num:07d}"
        num   = random.randint(0, 9)
        items.append({
            "issueNumber": issue,
            "number":      str(num),
            "color":       ",".join(get_color(num)),
            "size":        get_size(num),
            "premium":     str(num),
            "sum":         0,
        })

    period = calculate_period_id(duration)
    return {
        "code": 0,
        "msg":  "Succeed (mock)",
        "data": {
            "list":          items,
            "pageNo":        page,
            "totalPage":     50,
            "totalCount":    500,
            "currentPeriod": period,
            "_mock":         True,
        }
    }


# ═══════════════════════════════════════════════════════════════════════════
# ADMIN PREDICTION SYSTEM
# ═══════════════════════════════════════════════════════════════════════════

from fastapi import Header, HTTPException
from pydantic import BaseModel
from typing import Optional as Opt
import json, os

# In-memory stores (Vercel serverless = ephemeral, use external DB for prod)
# Structure: { "30s": { "issueNumber": {...prediction} }, ... }
_predictions: dict = {}   # next period predictions
_queue:       dict = {}   # pre-queued future predictions { "30s": [pred1, pred2, ...] }
_history_override: dict = {}  # { "issueNumber": result_dict }

ADMIN_SECRET = os.environ.get("ADMIN_SECRET", "admin1234")  # set in Vercel env

# ── Models ────────────────────────────────────────────────────────────────────

class PredictionSet(BaseModel):
    duration: str          # 30s | 1min | 3min
    number: int            # 0-9
    issueNumber: Opt[str] = None  # if None → applies to NEXT period

class QueueAdd(BaseModel):
    duration: str
    predictions: list[int]  # list of numbers, e.g. [3,7,1,5]

class AdminAuth(BaseModel):
    secret: str

def verify_admin(x_admin_secret: str = Header(...)):
    if x_admin_secret != ADMIN_SECRET:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return True

def build_result(number: int, issue: str) -> dict:
    colors = get_color(number)
    return {
        "issueNumber": issue,
        "number":      str(number),
        "color":       ",".join(colors),
        "size":        get_size(number),
        "premium":     str(number),
        "adminSet":    True,
    }

# ── Admin: Set prediction for next period ─────────────────────────────────────

@app.post("/api/admin/predict")
async def admin_set_prediction(body: PredictionSet, auth=Depends(verify_admin)):
    dur = body.duration.lower()
    if dur not in DURATION_MAP:
        raise HTTPException(400, "Invalid duration")
    if not (0 <= body.number <= 9):
        raise HTTPException(400, "Number must be 0-9")

    period = calculate_period_id(dur)
    # Target: current period's issueNumber (will display when this period resolves)
    target_issue = body.issueNumber or period["issueNumber"]

    result = build_result(body.number, target_issue)
    _predictions[dur] = result

    return {"code": 0, "msg": "Prediction set", "data": result}

# ── Admin: Queue multiple future predictions ──────────────────────────────────

@app.post("/api/admin/queue")
async def admin_queue(body: QueueAdd, auth=Depends(verify_admin)):
    dur = body.duration.lower()
    if dur not in DURATION_MAP:
        raise HTTPException(400, "Invalid duration")

    period   = calculate_period_id(dur)
    seconds  = DURATION_MAP[dur]["seconds"]
    now_pt   = get_platform_time()
    midnight = now_pt.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed  = int((now_pt - midnight).total_seconds())
    date_str = now_pt.strftime("%Y%m%d")

    current_draw = elapsed // seconds
    queued = []

    for i, num in enumerate(body.predictions):
        if not (0 <= num <= 9):
            continue
        draw_num = current_draw + 1 + i   # starts from NEXT period
        issue    = f"{date_str}10{draw_num:07d}"
        queued.append(build_result(num, issue))

    if dur not in _queue:
        _queue[dur] = []
    _queue[dur].extend(queued)

    return {"code": 0, "msg": f"Queued {len(queued)} predictions", "data": queued}

# ── Admin: View current state ─────────────────────────────────────────────────

@app.get("/api/admin/state")
async def admin_state(auth=Depends(verify_admin)):
    state = {}
    for dur in ["30s", "1min", "3min"]:
        period = calculate_period_id(dur)
        state[dur] = {
            "currentPeriod":    period,
            "activePrediction": _predictions.get(dur),
            "queue":            _queue.get(dur, []),
            "queueLength":      len(_queue.get(dur, [])),
        }
    return {"code": 0, "data": state}

# ── Admin: Clear prediction / queue ───────────────────────────────────────────

@app.delete("/api/admin/clear/{duration}")
async def admin_clear(duration: str, auth=Depends(verify_admin)):
    dur = duration.lower()
    _predictions.pop(dur, None)
    _queue.pop(dur, None)
    return {"code": 0, "msg": f"Cleared {dur}"}

# ── Public: Get prediction for current period (used by user frontend) ─────────

@app.get("/api/predict")
async def get_prediction(duration: str = Query("30s")):
    dur = duration.lower()
    period = calculate_period_id(dur)
    current_issue = period["issueNumber"]

    # Check if there's a set prediction matching current period
    pred = _predictions.get(dur)
    if pred and pred.get("issueNumber") == current_issue:
        return {"code": 0, "data": {**pred, "currentPeriod": period}}

    # Check queue — pop first item if it matches current period
    queue = _queue.get(dur, [])
    if queue and queue[0].get("issueNumber") == current_issue:
        active = queue[0]  # don't pop yet, keep until period ends
        return {"code": 0, "data": {**active, "currentPeriod": period}}

    return {"code": 0, "data": {"currentPeriod": period, "prediction": None}}

# ── Period-change hook: auto-advance queue ────────────────────────────────────

@app.post("/api/admin/advance/{duration}")
async def advance_period(duration: str, auth=Depends(verify_admin)):
    """Call this when a period ends to pop queue and promote next prediction."""
    dur = duration.lower()
    _predictions.pop(dur, None)
    queue = _queue.get(dur, [])
    if queue:
        _queue[dur] = queue[1:]   # pop first
        if _queue[dur]:
            _predictions[dur] = _queue[dur][0]
    return {"code": 0, "msg": "Advanced", "nextPrediction": _predictions.get(dur)}


# Need Depends import
from fastapi import Depends
