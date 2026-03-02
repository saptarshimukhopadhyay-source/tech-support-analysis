# Ticket Analytics — Deployment Guide

## Architecture

```
[Frontend — GitHub Pages / Vercel]     [Backend — Railway / Render]     [AWS RDS MySQL]
    index.html (report)          →→→   Flask API (/api/tickets)    →→→   aiagent_transactions
    (no DB credentials)                (env vars only)                    (read-only)
```

---

## Step 1 — Deploy the Backend API (Railway — recommended)

### 1.1  Create a GitHub repo for the backend

```bash
mkdir ticket-analytics-api && cd ticket-analytics-api
cp -r /path/to/backend/* .
git init && git add . && git commit -m "initial"
git remote add origin https://github.com/YOUR_ORG/ticket-analytics-api.git
git push -u origin main
```

### 1.2  Deploy on Railway

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select `ticket-analytics-api`
3. Railway auto-detects Python and runs `gunicorn` via `Procfile`

### 1.3  Set environment variables in Railway dashboard

Go to your service → **Variables** → add these:

| Variable     | Value                                             |
|--------------|---------------------------------------------------|
| `DB_HOST`    | `masterdb.c6b8otohjvox.ap-south-1.rds.amazonaws.com` |
| `DB_PORT`    | `3306`                                            |
| `DB_USER`    | `readonly_user`                                   |
| `DB_PASSWORD`| `z7t&aP,)@4cDTZW`                                 |
| `DB_NAME`    | `services`                                        |

> Railway automatically provides `PORT`. Do not add it manually.

### 1.4  Get your backend URL

Railway assigns a public URL like:
`https://ticket-analytics-api-production.up.railway.app`

Test it:
```
curl https://YOUR-API-URL.railway.app/health
# → {"status":"ok","timestamp":"..."}

curl "https://YOUR-API-URL.railway.app/api/tickets?from=2026-02-01&to=2026-02-28"
# → {"from":"2026-02-01","to":"2026-02-28","total":472,"tickets":[...]}
```

---

## Step 2 — Configure the Frontend

Edit `frontend/index.html` — find this line near the top of the `<script>` block:

```js
var API_BASE = (function() {
  ...
  return window.ANALYTICS_API_URL || '';
})();
```

**Option A** — hardcode for simplicity (quickest):
```js
return 'https://YOUR-API-URL.railway.app';
```

**Option B** — set via a config file (best for teams):
Create a `config.js` file:
```js
window.ANALYTICS_API_URL = 'https://YOUR-API-URL.railway.app';
```
And add before the closing `</body>` in `index.html`:
```html
<script src="config.js"></script>
```

---

## Step 3 — Deploy the Frontend

### Option A: Vercel (easiest, ~2 minutes)

1. Go to [vercel.com](https://vercel.com) → **New Project** → Import your GitHub repo
2. Framework: **Other** (static)
3. Root directory: `frontend/`
4. Deploy → get a URL like `https://ticket-analytics.vercel.app`

### Option B: GitHub Pages

1. Push `frontend/index.html` to a GitHub repo
2. Go to repo Settings → Pages → Source: `main` branch → `/frontend` folder
3. URL: `https://YOUR_ORG.github.io/ticket-analytics/`

### Option C: Netlify

1. Drag and drop the `frontend/` folder to [app.netlify.com/drop](https://app.netlify.com/drop)
2. Instant URL, no account needed for testing

---

## Step 4 — CORS (if needed)

The backend already has `flask-cors` with `CORS(app)` which allows all origins.

If you want to restrict it to your frontend domain only, edit `app.py`:
```python
CORS(app, origins=["https://ticket-analytics.vercel.app"])
```

---

## Local Development

### Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env   # fill in real values
python app.py          # runs on http://localhost:5000
```

### Frontend
```bash
# Just open frontend/index.html in a browser
# It auto-detects localhost and points to http://localhost:5000
```

---

## File Structure

```
ticket-analytics/
├── backend/
│   ├── app.py              # Flask API server
│   ├── requirements.txt    # Python dependencies
│   ├── Procfile            # gunicorn start command
│   ├── railway.json        # Railway config
│   ├── .env.example        # Env var template (commit this)
│   └── .gitignore          # Excludes .env (never commit)
└── frontend/
    └── index.html          # The full analytics report
```

---

## API Reference

### `GET /health`
Health check — returns `{"status":"ok"}`

### `GET /api/tickets?from=YYYY-MM-DD&to=YYYY-MM-DD`
Returns categorized ticket data for the date range.

**Response:**
```json
{
  "from": "2026-02-01",
  "to": "2026-02-28",
  "total": 472,
  "parse_errors": 0,
  "tickets": [
    {
      "id": "2026-FEB-PLOMNI-6772",
      "category": "GENERAL",
      "subcategory": "OPS_TASK_STUCK",
      "status": "completed",
      "feedback": ""
    }
  ]
}
```
