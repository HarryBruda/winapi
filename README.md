# WinGo Clone API — Vercel Deploy Guide

## Vercel এ Deploy করো (Free)

### Method 1: GitHub দিয়ে (সহজ)

```bash
# 1. GitHub এ repo বানাও
# 2. এই files গুলো push করো
# 3. vercel.com এ গিয়ে GitHub repo connect করো
# 4. Deploy!
```

### Method 2: Vercel CLI দিয়ে (Termux থেকে)

```bash
# Node.js install করো
pkg install nodejs

# Vercel CLI install করো
npm install -g vercel

# Project folder এ যাও
cd wingo-clone

# Deploy করো
vercel

# Production deploy
vercel --prod
```

## Project Structure

```
wingo-clone/
├── vercel.json          ← Vercel config
├── requirements.txt     ← Python packages
├── api/
│   └── index.py         ← FastAPI backend (all routes)
└── public/
    └── index.html       ← Frontend dashboard
```

## API Endpoints

| Endpoint | কী করে |
|----------|--------|
| `GET /api/games` | সব game list |
| `GET /api/history/WinGo/30S` | History (real বা generated) |
| `GET /api/history/WinGo/30S?source=real` | Real data only |
| `GET /api/history/WinGo/30S?source=fake` | Generated data |
| `GET /api/current/WinGo/30S` | Current issue + countdown |
| `GET /api/draw/WinGo/30S` | নিজস্ব draw (random) |
| `GET /api/stats/WinGo/30S` | Color & number stats |
| `GET /api/proxy/WinGo/30S` | ar-lottery01.com থেকে real data |
| `GET /api/health` | Health check |

## Color Rules

- 0 → Red + Violet
- 1,3,7,9 → Green
- 2,4,6,8 → Red  
- 5 → Green + Violet

## Features

✅ নিজস্ব Draw System (random number generation)
✅ Real data proxy (ar-lottery01.com থেকে)
✅ Fallback to generated data
✅ Color & number statistics
✅ Live countdown timer
✅ Auto-draw mode
✅ Vercel serverless compatible
