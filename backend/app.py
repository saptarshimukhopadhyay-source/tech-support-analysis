import os
import json
import mysql.connector
from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)  # Allow requests from the frontend (GitHub Pages / Vercel / etc.)

# ── DB CONFIG — loaded from environment variables only, never hardcoded ──────
DB_CONFIG = {
    "host":     os.environ.get("DB_HOST"),
    "port":     int(os.environ.get("DB_PORT", 3306)),
    "user":     os.environ.get("DB_USER"),
    "password": os.environ.get("DB_PASSWORD"),
    "database": os.environ.get("DB_NAME", "services"),
    "connect_timeout": 10,
    "ssl_disabled": False,
}


def get_connection():
    return mysql.connector.connect(**DB_CONFIG)


def safe_get(obj, path, default=""):
    """Safely traverse nested dict by dot-path."""
    if not obj:
        return default
    parts = path.split(".")
    cur = obj
    for p in parts:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(p)
        if cur is None:
            return default
    return "" if cur == "null" else str(cur) if cur is not None else default


def resolve_category(resp):
    """
    Category resolution logic — mirrors the original categorization_2 pipeline:
    - If judge.verdict == 'disagree' AND judge provides a category → use judge override
    - Otherwise → use response.suggested_category (final AI answer)
    """
    if not resp:
        return "", ""

    resp_inner = resp.get("response", {}) or {}
    judge = resp_inner.get("judge", {}) or {}
    verdict = judge.get("verdict", "")
    judge_cat = judge.get("suggested_category") or ""
    judge_sub = judge.get("suggested_subcategory") or ""
    sug_cat = resp_inner.get("suggested_category") or ""
    sug_sub = resp_inner.get("suggested_subcategory") or ""

    if verdict == "disagree" and judge_cat and judge_cat not in ("null", ""):
        return judge_cat, (judge_sub if judge_sub and judge_sub != "null" else sug_sub)

    return sug_cat, sug_sub


def parse_response_json(raw):
    """Parse the response JSON column from the DB row."""
    if not raw:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        try:
            return json.loads(raw.replace("\\\\", "\\"))
        except Exception:
            return None


# ── HEALTH CHECK ─────────────────────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": datetime.utcnow().isoformat()})


# ── MAIN DATA ENDPOINT ───────────────────────────────────────────────────────
@app.route("/api/tickets", methods=["GET"])
def get_tickets():
    """
    Query params:
        from  — start date  e.g. 2026-02-01
        to    — end date    e.g. 2026-02-28
    Returns:
        JSON list of { unique_id, category, subcategory }
    """
    date_from = request.args.get("from", "")
    date_to   = request.args.get("to", "")

    # Validate date format
    for d in [date_from, date_to]:
        if d:
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                return jsonify({"error": f"Invalid date format '{d}'. Use YYYY-MM-DD."}), 400

    if not date_from or not date_to:
        return jsonify({"error": "Both 'from' and 'to' query params are required."}), 400

    from_dt = f"{date_from} 00:00:00"
    to_dt   = f"{date_to} 23:59:59"

    sql = """
        SELECT transaction_id, unique_id, response, status, feedback, feedback_comment
        FROM services.aiagent_transactions
        WHERE transaction_category = 'ticket_categorization_insights'
          AND STR_TO_DATE(
                JSON_UNQUOTE(JSON_EXTRACT(response, '$.meta.timestamp')),
                '%Y-%m-%dT%%H:%i:%s'
              )
              BETWEEN %s AND %s
    """

    try:
        conn = get_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, (from_dt, to_dt))
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
    except Exception as e:
        return jsonify({"error": f"Database error: {str(e)}"}), 500

    tickets = []
    errors  = 0

    for row in rows:
        resp = parse_response_json(row.get("response"))
        if resp is None:
            errors += 1
            continue

        category, subcategory = resolve_category(resp)

        tickets.append({
            "id":          row.get("unique_id", ""),
            "category":    category,
            "subcategory": subcategory,
            "status":      row.get("status", ""),
            "feedback":    row.get("feedback", ""),
        })

    return jsonify({
        "from":        date_from,
        "to":          date_to,
        "total":       len(tickets),
        "parse_errors": errors,
        "tickets":     tickets,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
