import os
import json
import logging
from datetime import datetime
from typing import Optional

import mysql.connector
from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ─── LOGGING ────────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─── APP ────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Ticket Analytics API",
    description="Queries aiagent_transactions and returns categorised ticket data",
    version="1.0.0",
)

# Allow the GitHub Pages frontend (and localhost) to call this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten this to your GitHub Pages URL in production
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ─── DB CONFIG ───────────────────────────────────────────────────────────────
# Values come from Railway environment variables (set in the Railway dashboard).
# Fallback to the values you provided for local development.
DB_CONFIG = {
    "host":     os.getenv("DB_HOST",     "masterdb.c6b8otohjvox.ap-south-1.rds.amazonaws.com"),
    "port":     int(os.getenv("DB_PORT", "3306")),
    "user":     os.getenv("DB_USER",     "readonly_user"),
    "password": os.getenv("DB_PASSWORD", "z7t&aP,)@4cDTZW"),
    "database": os.getenv("DB_NAME",     "services"),
    "connection_timeout": 10,
}


def get_connection():
    """Open a fresh MySQL connection."""
    return mysql.connector.connect(**DB_CONFIG)


# ─── CATEGORY RESOLUTION ─────────────────────────────────────────────────────
def resolve_category(response: dict) -> tuple[str, str]:
    """
    Mirror the logic used to build categorization_2.csv:
      - If judge.verdict == 'disagree' AND judge provides a category → use judge values
      - Otherwise → use response.suggested_category / response.suggested_subcategory
    """
    if not response:
        return "", ""

    inner = response.get("response", {}) or {}
    judge = inner.get("judge", {}) or {}

    verdict      = judge.get("verdict", "")
    judge_cat    = judge.get("suggested_category") or ""
    judge_sub    = judge.get("suggested_subcategory") or ""
    suggest_cat  = inner.get("suggested_category") or ""
    suggest_sub  = inner.get("suggested_subcategory") or ""

    if verdict == "disagree" and judge_cat and judge_cat not in ("null", "None"):
        return judge_cat, (judge_sub if judge_sub and judge_sub not in ("null", "None") else suggest_sub)

    return suggest_cat, suggest_sub


# ─── ENDPOINTS ───────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    """Railway uses this to confirm the service is alive."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/tickets")
def get_tickets(
    from_date: str = Query(..., alias="from", description="Start date YYYY-MM-DD"),
    to_date:   str = Query(..., alias="to",   description="End date   YYYY-MM-DD"),
):
    """
    Returns categorised ticket data for the given date range.

    Response shape:
    {
      "total": 472,
      "from":  "2026-02-01",
      "to":    "2026-02-28",
      "parse_errors": 0,
      "tickets": [
        { "id": "2026-FEB-PLOMNI-6772", "category": "GENERAL", "subcategory": "TASK_STUCK" },
        ...
      ]
    }
    """
    # Validate dates
    try:
        datetime.strptime(from_date, "%Y-%m-%d")
        datetime.strptime(to_date,   "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Dates must be in YYYY-MM-DD format")

    if from_date > to_date:
        raise HTTPException(status_code=400, detail="'from' date must be before 'to' date")

    from_dt = from_date + " 00:00:00"
    to_dt   = to_date   + " 23:59:59"

    sql = """
        SELECT unique_id, response
        FROM   services.aiagent_transactions
        WHERE  transaction_category = 'ticket_categorization_insights'
          AND  STR_TO_DATE(
                 JSON_UNQUOTE(JSON_EXTRACT(response, '$.meta.timestamp')),
                 '%%Y-%%m-%%dT%%H:%%i:%%s'
               )
               BETWEEN %s AND %s
    """

    tickets     = []
    parse_errors = 0

    try:
        conn   = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (from_dt, to_dt))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
    except mysql.connector.Error as e:
        logger.error("DB error: %s", e)
        raise HTTPException(status_code=503, detail=f"Database error: {e.msg}")

    logger.info("Query returned %d rows for %s → %s", len(rows), from_dt, to_dt)

    for row in rows:
        unique_id    = row.get("unique_id", "")
        response_raw = row.get("response", "")

        # Parse the JSON response column
        response_json = None
        if response_raw:
            try:
                response_json = json.loads(response_raw) if isinstance(response_raw, str) else response_raw
            except (json.JSONDecodeError, TypeError):
                parse_errors += 1
                logger.warning("JSON parse failed for unique_id=%s", unique_id)
                continue

        category, subcategory = resolve_category(response_json)

        if not category:
            # Skip rows with no resolved category (error/null responses)
            parse_errors += 1
            continue

        tickets.append({
            "id":          unique_id,
            "category":    category,
            "subcategory": subcategory,
        })

    logger.info("Returning %d tickets, %d parse errors", len(tickets), parse_errors)

    return JSONResponse({
        "total":        len(tickets),
        "from":         from_date,
        "to":           to_date,
        "parse_errors": parse_errors,
        "tickets":      tickets,
    })
