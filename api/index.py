from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import httpx
import random
import time
import math
from datetime import datetime, timezone

app = FastAPI(title="WinGo Clone API", version="1.0.0")

# CORS - সব origin থেকে access দাও
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============================================
# CONFIG
# ============================================
DRAW_BASE = "https://draw.ar-lottery01.com"
GAME_TYPES = ["WinGo", "K3", "5D", "TrxWin"]
DURATIONS  = ["30S", "1Min", "3Min", "5Min", "10Min"]

HEADERS = {
    "Accept": "application/json, */*",
    "User-Agent": "Mozilla/5.0 (Linux; Android 12; SM-G991B) AppleWebKit/537.36",
}

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_color(number: int) -> str:
    """WinGo color logic: 0=red+violet, 5=green+violet, even=red, odd=green"""
    if number == 0:
        return "red,violet"
    elif number == 5:
        return "green,violet"
    elif number % 2 == 0:
        return "red"
    else:
        return "green"

def generate_issue_number(duration: str) -> str:
    """Issue number generate করো based on current time"""
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y%m%d")
    
    duration_seconds = {
        "30S": 30, "1Min": 60, "3Min": 180, "5Min": 300, "10Min": 600
    }
    secs = duration_seconds.get(duration, 60)
    period = int(time.time() / secs)
    
    return f"{date_str}10{str(period).zfill(8)}"

def generate_result() -> dict:
    """Random WinGo result generate করো"""
    number = random.randint(0, 9)
    color = get_color(number)
    big_small = "Big" if number >= 5 else "Small"
    return {
        "number": str(number),
        "color": color,
        "premium": str(number),
        "bigSmall": big_small,
        "sum": 0
    }

def generate_history(count: int = 10, duration: str = "30S") -> list:
    """Fake history list generate করো"""
    results = []
    now = int(time.time())
    
    duration_seconds = {
        "30S": 30, "1Min": 60, "3Min": 180, "5Min": 300, "10Min": 600
    }
    secs = duration_seconds.get(duration, 60)
    
    for i in range(count):
        period = int((now - i * secs) / secs)
        date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
        issue = f"{date_str}10{str(period).zfill(8)}"
        result = generate_result()
        result["issueNumber"] = issue
        results.append(result)
    
    return results

async def fetch_upstream(game: str, duration: str, endpoint: str = "GetHistoryIssuePage") -> dict:
    """আসল ar-lottery01.com থেকে data fetch করো"""
    url = f"{DRAW_BASE}/{game}/{game}_{duration}/{endpoint}.json"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code == 200:
                return {"success": True, "data": resp.json(), "url": url}
    except Exception as e:
        pass
    return {"success": False, "url": url}


# ============================================
# ROOT
# ============================================
@app.get("/api")
async def root():
    return {
        "code": 0,
        "msg": "WinGo Clone API is running",
        "version": "1.0.0",
        "endpoints": [
            "/api/games",
            "/api/history/{game}/{duration}",
            "/api/current/{game}/{duration}",
            "/api/stats/{game}/{duration}",
            "/api/draw/{game}/{duration}",
            "/api/proxy/{game}/{duration}",
        ]
    }


# ============================================
# GAME LIST
# ============================================
@app.get("/api/games")
async def get_games():
    return {
        "code": 0,
        "msg": "Success",
        "data": {
            "games": GAME_TYPES,
            "durations": DURATIONS,
            "combinations": [
                {"game": g, "duration": d}
                for g in GAME_TYPES for d in DURATIONS
            ]
        }
    }


# ============================================
# PROXY — আসল site থেকে data আনো
# ============================================
@app.get("/api/proxy/{game}/{duration}")
async def proxy_history(game: str, duration: str):
    """ar-lottery01.com থেকে real data proxy করো"""
    if game not in GAME_TYPES:
        raise HTTPException(400, f"Invalid game. Use: {', '.join(GAME_TYPES)}")
    if duration not in DURATIONS:
        raise HTTPException(400, f"Invalid duration. Use: {', '.join(DURATIONS)}")

    result = await fetch_upstream(game, duration)
    if not result["success"]:
        raise HTTPException(502, "Upstream fetch failed")

    return {
        "code": 0,
        "msg": "Success (proxied)",
        "source": result["url"],
        "game": game,
        "duration": duration,
        "data": result["data"].get("data", result["data"])
    }


# ============================================
# HISTORY — নিজের generated data
# ============================================
@app.get("/api/history/{game}/{duration}")
async def get_history(
    game: str,
    duration: str,
    page: int = Query(1, ge=1),
    pageSize: int = Query(10, ge=1, le=100),
    source: str = Query("auto", description="auto | real | fake")
):
    if game not in GAME_TYPES:
        raise HTTPException(400, f"Invalid game. Use: {', '.join(GAME_TYPES)}")
    if duration not in DURATIONS:
        raise HTTPException(400, f"Invalid duration. Use: {', '.join(DURATIONS)}")

    # auto mode: আগে real try করো, fail করলে fake দাও
    if source in ("auto", "real"):
        upstream = await fetch_upstream(game, duration)
        if upstream["success"]:
            data = upstream["data"].get("data", {})
            return {
                "code": 0,
                "msg": "Success",
                "game": game,
                "duration": duration,
                "dataSource": "real",
                "data": data
            }

    # Fake generated data
    history = generate_history(count=pageSize, duration=duration)
    total = 500
    total_pages = math.ceil(total / pageSize)

    return {
        "code": 0,
        "msg": "Success",
        "game": game,
        "duration": duration,
        "dataSource": "generated",
        "data": {
            "list": history,
            "pageNo": page,
            "totalPage": total_pages,
            "totalCount": total
        }
    }


# ============================================
# CURRENT ISSUE — latest issue কী চলছে
# ============================================
@app.get("/api/current/{game}/{duration}")
async def get_current(game: str, duration: str):
    if game not in GAME_TYPES:
        raise HTTPException(400, f"Invalid game")
    if duration not in DURATIONS:
        raise HTTPException(400, f"Invalid duration")

    issue_number = generate_issue_number(duration)
    
    duration_seconds = {
        "30S": 30, "1Min": 60, "3Min": 180, "5Min": 300, "10Min": 600
    }
    secs = duration_seconds.get(duration, 60)
    now = time.time()
    period_start = int(now / secs) * secs
    time_remaining = int(period_start + secs - now)

    return {
        "code": 0,
        "msg": "Success",
        "game": game,
        "duration": duration,
        "data": {
            "issueNumber": issue_number,
            "timeRemaining": time_remaining,
            "durationSeconds": secs,
            "serverTime": int(now * 1000)
        }
    }


# ============================================
# DRAW — নিজস্ব random draw করো
# ============================================
@app.get("/api/draw/{game}/{duration}")
async def do_draw(game: str, duration: str):
    """নিজস্ব draw system — random result generate করো"""
    if game not in GAME_TYPES:
        raise HTTPException(400, "Invalid game")
    if duration not in DURATIONS:
        raise HTTPException(400, "Invalid duration")

    issue_number = generate_issue_number(duration)
    result = generate_result()

    return {
        "code": 0,
        "msg": "Draw complete",
        "game": game,
        "duration": duration,
        "data": {
            "issueNumber": issue_number,
            "result": result,
            "drawnAt": int(time.time() * 1000)
        }
    }


# ============================================
# STATS — color ও number frequency
# ============================================
@app.get("/api/stats/{game}/{duration}")
async def get_stats(game: str, duration: str):
    if game not in GAME_TYPES:
        raise HTTPException(400, "Invalid game")
    if duration not in DURATIONS:
        raise HTTPException(400, "Invalid duration")

    # upstream থেকে real data নেওয়ার চেষ্টা
    upstream = await fetch_upstream(game, duration)
    
    if upstream["success"]:
        lst = upstream["data"].get("data", {}).get("list", [])
        data_source = "real"
    else:
        lst = generate_history(50, duration)
        data_source = "generated"

    color_count: dict = {}
    number_count: dict = {}
    big_small = {"Big": 0, "Small": 0}

    for item in lst:
        # Color count
        for c in str(item.get("color", "")).split(","):
            c = c.strip()
            if c:
                color_count[c] = color_count.get(c, 0) + 1
        # Number count
        n = str(item.get("number", ""))
        number_count[n] = number_count.get(n, 0) + 1
        # Big/Small
        if n.isdigit():
            if int(n) >= 5:
                big_small["Big"] += 1
            else:
                big_small["Small"] += 1

    return {
        "code": 0,
        "msg": "Success",
        "game": game,
        "duration": duration,
        "dataSource": data_source,
        "totalRecords": len(lst),
        "stats": {
            "colorFrequency": color_count,
            "numberFrequency": number_count,
            "bigSmall": big_small,
            "latestResult": lst[0] if lst else None
        }
    }


# ============================================
# HEALTH CHECK
# ============================================
@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "WinGo Clone API"
    }
