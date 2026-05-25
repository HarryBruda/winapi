from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import httpx
import time
import math
from datetime import datetime, timezone, timedelta

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DRAW_BASE = "https://draw.ar-lottery01.com"

MARKETS = {
    "WinGo_30S":  {"game": "WinGo", "duration": "30S",   "seconds": 30},
    "WinGo_1M":   {"game": "WinGo", "duration": "1Min",  "seconds": 60},
    "WinGo_3M":   {"game": "WinGo", "duration": "3Min",  "seconds": 180},
    "WinGo_5M":   {"game": "WinGo", "duration": "5Min",  "seconds": 300},
    "WinGo_10M":  {"game": "WinGo", "duration": "10Min", "seconds": 600},
    "K3_1M":      {"game": "K3",    "duration": "1Min",  "seconds": 60},
    "K3_3M":      {"game": "K3",    "duration": "3Min",  "seconds": 180},
    "K3_5M":      {"game": "K3",    "duration": "5Min",  "seconds": 300},
    "5D_1M":      {"game": "5D",    "duration": "1Min",  "seconds": 60},
    "5D_3M":      {"game": "5D",    "duration": "3Min",  "seconds": 180},
    "5D_5M":      {"game": "5D",    "duration": "5Min",  "seconds": 300},
    "TrxWin_1M":  {"game": "TrxWin","duration": "1Min",  "seconds": 60},
    "TrxWin_3M":  {"game": "TrxWin","duration": "3Min",  "seconds": 180},
    "TrxWin_5M":  {"game": "TrxWin","duration": "5Min",  "seconds": 300},
}

# ─────────────────────────────────────────────
# PERIOD ID — ar-lottery01.com এর exact format
# issueNumber = YYYYMMDD + "10" + 8-digit-sequence
# sequence = দিনের শুরু থেকে কত নম্বর period চলছে
# ─────────────────────────────────────────────
def get_period_info(seconds: int):
    # UTC+8 timezone (ar-lottery01.com এর server time)
    tz8 = timezone(timedelta(hours=8))
    now = datetime.now(tz8)
    
    # দিনের শুরু থেকে কত সেকেন্ড গেছে
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((now - day_start).total_seconds())
    
    # বর্তমান period number (1 থেকে শুরু)
    current_period = elapsed // seconds + 1
    
    # Period শুরু ও শেষ time
    period_start_elapsed = (current_period - 1) * seconds
    period_end_elapsed = current_period * seconds
    
    period_start = day_start + timedelta(seconds=period_start_elapsed)
    period_end = day_start + timedelta(seconds=period_end_elapsed)
    
    # Remaining seconds
    remaining = int((period_end - now).total_seconds())
    if remaining < 0:
        remaining = 0

    # Issue number — YYYYMMDD + 10 + 8-digit sequence
    date_str = now.strftime("%Y%m%d")
    issue_number = f"{date_str}10{str(current_period).zfill(8)}"

    # Previous issue number
    prev_period = current_period - 1
    prev_issue = f"{date_str}10{str(prev_period).zfill(8)}" if prev_period > 0 else None

    return {
        "issueNumber": issue_number,
        "prevIssueNumber": prev_issue,
        "periodNumber": current_period,
        "timeRemaining": remaining,
        "durationSeconds": seconds,
        "periodStart": period_start.isoformat(),
        "periodEnd": period_end.isoformat(),
        "serverTime": int(now.timestamp() * 1000),
        "date": date_str,
    }


# ─────────────────────────────────────────────
# FETCH from Alibaba OSS
# ─────────────────────────────────────────────
async def fetch_oss(game: str, duration: str):
    # duration mapping: 1Min → 1M, 3Min → 3M etc (draw server uses M not Min)
    dur_map = {"30S": "30S", "1Min": "1M", "3Min": "3M", "5Min": "5M", "10Min": "10M"}
    dur = dur_map.get(duration, duration)
    url = f"{DRAW_BASE}/{game}/{game}_{dur}/GetHistoryIssuePage.json?ts={int(time.time()*1000)}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            r = await client.get(url, headers={
                "Accept": "*/*",
                "User-Agent": "Mozilla/5.0 (Linux; Android 12)",
                "Origin": "https://dkwin9.com",
                "Referer": "https://dkwin9.com/"
            })
            if r.status_code == 200:
                return {"ok": True, "data": r.json(), "url": url}
    except Exception as e:
        pass
    return {"ok": False, "url": url}


# ─────────────────────────────────────────────
# ROUTES
# ─────────────────────────────────────────────

@app.get("/api")
def root():
    return {"code": 0, "msg": "WinGo API Running", "markets": list(MARKETS.keys())}


# Current period info — period ID, countdown, etc
@app.get("/api/current/{market}")
def current_period(market: str):
    m = MARKETS.get(market)
    if not m:
        raise HTTPException(400, f"Invalid market. Valid: {list(MARKETS.keys())}")
    info = get_period_info(m["seconds"])
    return {
        "code": 0,
        "msg": "Success",
        "market": market,
        "game": m["game"],
        "duration": m["duration"],
        "data": info
    }


# All markets current period — একসাথে সব market এর period দেখো
@app.get("/api/current")
def all_current():
    result = {}
    for market, m in MARKETS.items():
        info = get_period_info(m["seconds"])
        result[market] = {
            "issueNumber": info["issueNumber"],
            "timeRemaining": info["timeRemaining"],
            "durationSeconds": m["seconds"],
            "periodNumber": info["periodNumber"],
        }
    return {"code": 0, "msg": "Success", "data": result, "serverTime": int(time.time() * 1000)}


# History — ar-lottery01.com থেকে real data
@app.get("/api/history/{market}")
async def get_history(market: str, page: int = Query(1)):
    m = MARKETS.get(market)
    if not m:
        raise HTTPException(400, f"Invalid market. Valid: {list(MARKETS.keys())}")
    
    result = await fetch_oss(m["game"], m["duration"])
    if not result["ok"]:
        raise HTTPException(502, "Upstream fetch failed")
    
    data = result["data"]
    lst = data.get("data", {}).get("list", [])

    return {
        "code": 0,
        "msg": "Success",
        "market": market,
        "game": m["game"],
        "duration": m["duration"],
        "sourceUrl": result["url"],
        "data": {
            "list": lst,
            "pageNo": data.get("data", {}).get("pageNo", 1),
            "totalPage": data.get("data", {}).get("totalPage", 1),
            "totalCount": data.get("data", {}).get("totalCount", len(lst)),
        }
    }


# Latest result — শুধু সর্বশেষ result
@app.get("/api/latest/{market}")
async def get_latest(market: str):
    m = MARKETS.get(market)
    if not m:
        raise HTTPException(400, "Invalid market")

    result = await fetch_oss(m["game"], m["duration"])
    period = get_period_info(m["seconds"])

    if result["ok"]:
        lst = result["data"].get("data", {}).get("list", [])
        latest = lst[0] if lst else None
    else:
        latest = None

    return {
        "code": 0,
        "msg": "Success",
        "market": market,
        "data": {
            "latest": latest,
            "current": {
                "issueNumber": period["issueNumber"],
                "timeRemaining": period["timeRemaining"],
            }
        }
    }


# Stats
@app.get("/api/stats/{market}")
async def get_stats(market: str):
    m = MARKETS.get(market)
    if not m:
        raise HTTPException(400, "Invalid market")

    result = await fetch_oss(m["game"], m["duration"])
    if not result["ok"]:
        raise HTTPException(502, "Fetch failed")

    lst = result["data"].get("data", {}).get("list", [])
    color_freq: dict = {}
    number_freq: dict = {}
    big = small = 0

    for item in lst:
        for c in str(item.get("color", "")).split(","):
            c = c.strip()
            if c:
                color_freq[c] = color_freq.get(c, 0) + 1
        n = str(item.get("number", ""))
        number_freq[n] = number_freq.get(n, 0) + 1
        if n.isdigit():
            if int(n) >= 5:
                big += 1
            else:
                small += 1

    return {
        "code": 0,
        "msg": "Success",
        "market": market,
        "totalRecords": len(lst),
        "stats": {
            "colorFrequency": color_freq,
            "numberFrequency": number_freq,
            "bigSmall": {"Big": big, "Small": small},
            "latestResult": lst[0] if lst else None,
        }
    }


@app.get("/api/health")
def health():
    tz8 = timezone(timedelta(hours=8))
    return {
        "status": "ok",
        "serverTime": datetime.now(tz8).isoformat(),
        "utcTime": datetime.now(timezone.utc).isoformat(),
    }
