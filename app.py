# app.py
import os
import json
import math
import time
import random
from typing import Dict, Any, List, Optional, Tuple

from flask import Flask, request, jsonify, render_template, session, redirect
from urllib.parse import urlencode
from urllib.request import urlopen, Request

# ----------------------
# Flask setup
# ----------------------
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET", "dev-secret")  # set FLASK_SECRET in prod

API_RANDOM_BONUS = "https://www.qbreader.org/api/random-bonus"
API_CHECK_ANSWER = "https://www.qbreader.org/api/check-answer"

# -----------------------------------------------------------
# Unified θ table (LEVEL • PART • θ • API difficulty mapping)
# - "api_diffs": list of QBReader 'difficulties' we can pull
# - "part_index": 0 (easy), 1 (medium), 2 (hard)
# Notes:
# * HS Nationals and College Easy share θ = -1.7 on "easy": we randomize
# * College Easy Hard (+1.7) ~ Open/College-Nats Medium (+1.6): near-tie logic handles this
# * For Open/College-Nats rows, api_diffs includes [8, 9] (College Nats or Open)
# -----------------------------------------------------------
THETA_ROWS: List[Dict[str, Any]] = [
    {"level": "Middle School",       "part": "Easy",   "theta": -4.2, "api_diffs": [1], "part_index": 0},
    {"level": "High School Easy",    "part": "Easy",   "theta": -2.5, "api_diffs": [2], "part_index": 0},
    {"level": "High School Regular", "part": "Easy",   "theta": -2.0, "api_diffs": [3], "part_index": 0},
    {"level": "Middle School",       "part": "Medium", "theta": -1.7, "api_diffs": [1], "part_index": 1},
    
    {"level": "High School Nationals","part":"Easy",   "theta": -1.3, "api_diffs": [5], "part_index": 0},
    {"level": "College Easy",        "part": "Easy",   "theta": -1.3, "api_diffs": [6], "part_index": 0},
    # {"level": "College Medium",      "part": "Easy",   "theta": -0.7, "api_diffs": [7], "part_index": 0},
    # {"level": "College Regionals",   "part": "Easy",   "theta": -0.7, "api_diffs": [7], "part_index": 0},
    {"level": "High School Easy",    "part": "Medium", "theta": -0.5, "api_diffs": [2], "part_index": 1},
    # {"level": "Open / College Nats", "part": "Easy",   "theta": -0.1, "api_diffs": [8, 9], "part_index": 0},
    {"level": "Middle School",       "part": "Hard",   "theta": -0.4, "api_diffs": [1], "part_index": 2},

    {"level": "High School Regular", "part": "Medium", "theta":  0.0, "api_diffs": [3], "part_index": 1},
    {"level": "College Easy",        "part": "Medium", "theta": +0.4, "api_diffs": [6], "part_index": 1},
    {"level": "High School Easy",    "part": "Hard",   "theta": +0.5, "api_diffs": [2], "part_index": 2},
    {"level": "High School Nationals","part":"Medium", "theta": +0.6, "api_diffs": [5], "part_index": 1},
    {"level": "College Medium",      "part": "Medium", "theta": +0.6, "api_diffs": [7], "part_index": 1},

    {"level": "High School Regular", "part": "Hard",   "theta": +0.8, "api_diffs": [3], "part_index": 2},
    {"level": "College Regionals",   "part": "Medium", "theta": +1.0, "api_diffs": [7], "part_index": 1},
    {"level": "Open / College Nats", "part": "Medium", "theta": +1.6, "api_diffs": [8, 9], "part_index": 1},
    {"level": "College Easy",        "part": "Hard",   "theta": +1.7, "api_diffs": [6], "part_index": 2},

    {"level": "College Medium",      "part": "Hard",   "theta": +2.3, "api_diffs": [7], "part_index": 2},
    {"level": "High School Nationals","part":"Hard",   "theta": +2.6, "api_diffs": [5], "part_index": 2},
    {"level": "College Regionals",   "part": "Hard",   "theta": +2.7, "api_diffs": [7], "part_index": 2},
    {"level": "Open / College Nats", "part": "Hard",   "theta": +3.3, "api_diffs": [8, 9], "part_index": 2},
]

# near-tie window (logits) — if several rows are within min_dist + EPS, choose random among them
NEAR_TIE_EPS = 0.12

# Rasch-like update
THETA_STEP = 0.5  # learning rate
THETA_MIN = -5.0
THETA_MAX = +5.0

# fetch behavior
FETCH_RETRIES = 3
NO_REPEAT_SET_MAX = 5000

# ---------------------------------
# Helpers: HTTP and parsing
# ---------------------------------
def get_json(url: str, params: Dict[str, Any] = None, timeout: int = 15) -> Dict[str, Any]:
    full = url + ("?" + urlencode(params, doseq=True) if params else "")
    with urlopen(Request(full, headers={"User-Agent": "python"}), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def check_answer(answerline_html: str, user_answer: str) -> str:
    params = {"answerline": answerline_html or "", "givenAnswer": user_answer or ""}
    full = API_CHECK_ANSWER + "?" + urlencode(params, doseq=True)
    for attempt in range(3):
        try:
            with urlopen(Request(full, headers={"User-Agent": "python"}), timeout=12) as resp:
                j = json.loads(resp.read().decode("utf-8"))
            return (j or {}).get("directive", "reject")
        except Exception:
            time.sleep(0.2 * (attempt + 1))
    return "reject"

def strip_html(s: str) -> str:
    import re
    from html import unescape
    return re.sub(r"<[^>]+>", "", unescape(s or ""))

def stable_bonus_key(b: Dict[str, Any]) -> str:
    set_obj = b.get("set") or {}
    pkt     = b.get("packet") or {}
    return f"{set_obj.get('name','?')}|{set_obj.get('year','?')}|{pkt.get('number','?')}|{b.get('number','?')}"

def split_bonus(b: Dict[str, Any]) -> Tuple[str, List[str], List[str]]:
    leadin = b.get("leadin_sanitized")
    if not leadin:
        leadin = strip_html(b.get("leadin", "") or "")
    parts_display = b.get("parts_sanitized") or [strip_html(p) for p in (b.get("parts") or [])]
    answers_html  = b.get("answers") or b.get("answers_sanitized") or []
    return leadin, parts_display, answers_html

# ---------------------------------
# θ selection from table
# ---------------------------------
def choose_row_for_theta(theta: float) -> Dict[str, Any]:
    # find min distance
    dists = [abs(theta - r["theta"]) for r in THETA_ROWS]
    min_d = min(dists)
    # collect all rows that are "within" near-tie of min
    candidates = [THETA_ROWS[i] for i, d in enumerate(dists) if d <= min_d + NEAR_TIE_EPS]
    return random.choice(candidates)

# ---------------------------------
# Session state in Flask session
# ---------------------------------
def new_state() -> Dict[str, Any]:
    return {
        "theta": 0.0,
        "info_sum": 0.0,
        "rounds_total": 12,
        "rounds_done": 0,
        "category": None,                 # "All" means None
        "subcategory": None,
        "alt_subcats": None,
        "seen": set(),
        "last_item": None,                # store data needed for /answer
    }

def state() -> Dict[str, Any]:
    s = session.get("game")
    if not s:
        s = new_state()
        session["game"] = s
    # convert seen to set if serialized as list
    if isinstance(s.get("seen"), list):
        s["seen"] = set(s["seen"])
    return s

def persist(s: Dict[str, Any]) -> None:
    # turn set to list for session serialization
    s2 = dict(s)
    if isinstance(s2.get("seen"), set):
        s2["seen"] = list(s2["seen"])
    session["game"] = s2

# ---------------------------------
# Rasch update utils
# ---------------------------------
def rasch_update(theta: float, b_anchor: float, correct: bool, step: float = THETA_STEP) -> Tuple[float, float]:
    # 1PL: P(correct) = logistic(theta - b)
    P = 1.0 / (1.0 + math.exp(-(theta - b_anchor)))
    if correct:
        theta += step * (1.0 - P)
    else:
        theta -= step * P
    theta = max(THETA_MIN, min(THETA_MAX, theta))
    return theta, P

def se_from_info(info_sum: float) -> Optional[float]:
    if info_sum <= 0:
        return None
    return 1.0 / math.sqrt(info_sum)

# ---------------------------------
# Flask routes
# ---------------------------------
@app.route("/")
def index():
    return render_template("index.html")

@app.post("/api/start")
def api_start():
    payload = request.get_json(force=True) or {}
    category = payload.get("category")  # "All" allowed
    if category and category.lower() == "all":
        category = None
    subcat   = payload.get("subcategory") or None
    alts     = payload.get("alternateSubcategories") or None
    rounds   = int(payload.get("rounds") or 12)

    s = new_state()
    s["category"]   = category
    s["subcategory"]= subcat
    s["alt_subcats"]= alts
    s["rounds_total"]= max(1, rounds)
    s["theta"]      = 0.0
    s["info_sum"]   = 0.0
    s["rounds_done"]= 0
    s["seen"]       = set()
    s["last_item"]  = None
    persist(s)
    return jsonify({"ok": True})

def fetch_one_bonus(params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    for _ in range(FETCH_RETRIES):
        try:
            data = get_json(API_RANDOM_BONUS, params)
            arr = data.get("bonuses", []) or []
            if arr:
                return random.choice(arr)
        except Exception:
            time.sleep(0.2)
    return None

@app.get("/api/next")
def api_next():
    s = state()
    if s["rounds_done"] >= s["rounds_total"]:
        # final stats
        se = se_from_info(s["info_sum"])
        ci = None
        if se is not None:
            lo, hi = s["theta"] - 1.96 * se, s["theta"] + 1.96 * se
            ci = [round(lo, 2), round(hi, 2)]
        return jsonify({
            "done": True,
            "theta": round(s["theta"], 2),
            "se": None if se is None else round(se, 2),
            "ci": ci
        })

    # choose target row by θ with random tie-breaking
    row = choose_row_for_theta(s["theta"])
    api_diff = random.choice(row["api_diffs"])  # handles Open/College Nats choice
    part_idx = row["part_index"]

    # we'll try two passes:
    # 1) with hasDifficultyModifiers=True
    # 2) fallback: without it
    def attempt_fetch(params):
        # Fetch & ensure usable + not repeated
        for _ in range(8):  # multiple tries to avoid repeats/short items
            b = fetch_one_bonus(params)
            if not b:
                continue
            key = stable_bonus_key(b)
            if key in s["seen"]:
                continue
            leadin, parts_display, answers_html = split_bonus(b)
            n = min(len(parts_display), len(answers_html))
            if n == 0:
                continue
            # clip part index if bonus has fewer than 3 parts
            idx = min(part_idx, max(0, n - 1))

            # record chosen item & lock it in session
            s["seen"].add(key)
            s["last_item"] = {
                "answer_html": answers_html[idx],
                "b_anchor": row["theta"],   # difficulty we asked
                "level": row["level"],
                "part": row["part"],        # "Easy" / "Medium" / "Hard" from the θ table
                "meta": {
                    "set": (b.get("set") or {}).get("name", "Unknown set"),
                    "year": (b.get("set") or {}).get("year", "?"),
                    "packet": (b.get("packet") or {}).get("number", "?"),
                    "qnum": b.get("number", "?"),
                },
                "prompt": parts_display[idx],
                "leadin": leadin,
            }
            persist(s)

            # First of each block of three → show lead-in (client displays if non-empty)
            show_leadin = ((s["rounds_done"]) % 3 == 0)

            return {
                "done": False,
                "mode": "theta-table",
                "theta": round(s["theta"], 2),
                "level": row["level"],
                "part": row["part"],
                "partLabel": row["part"],  # for "(Easy)" etc.
                "meta": s["last_item"]["meta"],
                "prompt": s["last_item"]["prompt"],
                "leadin": s["last_item"]["leadin"],
                "showLeadin": show_leadin
            }
        return None

    # ---------- 1) primary: require difficulty modifiers ----------
    params_primary = {
        "number": 1,
        "difficulties": api_diff,
        "threePartBonuses": True,
        "standardOnly": True,
        "hasDifficultyModifiers": True,
    }
    if s["category"]:
        params_primary["categories"] = s["category"]
    if s["subcategory"]:
        params_primary["subcategories"] = s["subcategory"]
    if s["alt_subcats"]:
        params_primary["alternateSubcategories"] = s["alt_subcats"]

    result = attempt_fetch(params_primary)
    if result is not None:
        return jsonify(result)

    # ---------- 2) fallback: same query, but WITHOUT hasDifficultyModifiers ----------
    params_fallback = {
        "number": 1,
        "difficulties": api_diff,
        "threePartBonuses": True,
        "standardOnly": True,
    }
    if s["category"]:
        params_fallback["categories"] = s["category"]
    if s["subcategory"]:
        params_fallback["subcategories"] = s["subcategory"]
    if s["alt_subcats"]:
        params_fallback["alternateSubcategories"] = s["alt_subcats"]

    result2 = attempt_fetch(params_fallback)
    if result2 is not None:
        # tell the frontend this was the fallback
        result2["mode"] = "theta-table-fallback"
        return jsonify(result2)

    # Nothing usable this round
    return jsonify({"done": False, "error": "sparse"})

@app.post("/api/answer")
def api_answer():
    s = state()
    li = s.get("last_item") or {}
    if not li:
        return jsonify({"error": "no current question"})

    payload = request.get_json(force=True) or {}
    answer = payload.get("answer", "")
    override = str(payload.get("override", "")).strip().lower().startswith("y")

    if override:
        correct = True
        prompt_flag = False
        verdict = "accept"
    else:
        verdict = check_answer(li["answer_html"], answer)
        prompt_flag = (verdict == "prompt")
        correct = (verdict == "accept")

    # Update θ against the selected row's θ (b-anchor)
    theta_before = s["theta"]
    theta_after, P = rasch_update(theta_before, li["b_anchor"], correct)
    s["theta"] = theta_after
    s["info_sum"] += P * (1 - P)
    s["rounds_done"] += 1
    persist(s)

    # compute stats
    se = se_from_info(s["info_sum"])
    ci = None
    if se is not None:
        lo, hi = s["theta"] - 1.96 * se, s["theta"] + 1.96 * se
        ci = [round(lo, 2), round(hi, 2)]

    return jsonify({
        "prompt": prompt_flag,
        "verdict": verdict,
        "correct": correct,
        "officialAnswer": strip_html(li["answer_html"]),
        "theta": round(s["theta"], 2),
        "se": None if se is None else round(se, 2),
        "ci": ci
    })

# ----------------------
# Run locally
# ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
