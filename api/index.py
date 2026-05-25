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
