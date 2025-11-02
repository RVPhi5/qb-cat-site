# app.py
import os, json, math, random, time
from html import unescape
from urllib.parse import urlencode
from urllib.request import urlopen, Request
from flask import Flask, request, session, jsonify, render_template

API_RANDOM_BONUS = "https://www.qbreader.org/api/random-bonus"
API_CHECK_ANSWER = "https://www.qbreader.org/api/check-answer"
API_CATEGORIES   = "https://www.qbreader.org/api/categories"

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("FLASK_SECRET", "dev-secret-change-me")

LEVELS = [
    ("MS", 1),
    ("HS-Easy", 2),
    ("HS-Regular", 3),
    ("HS-Hard", 4),
    ("College-Medium", 7),
    ("College-Regionals", 7),
    ("College-Nationals", 8),
    ("Open", 9),
]
LEVEL_ANCHOR = {
    "MS": -2.0, "HS-Easy": -1.2, "HS-Regular": 0.0, "HS-Hard": 0.6,
    "College-Medium": 1.2, "College-Regionals": 1.6, "College-Nationals": 2.2, "Open": 3.0,
}
THETA_STEP = 0.5
BATCH_N, MAX_BATCHES = 20, 5

def _get_json(url, params=None, timeout=15):
    full = url + ("?" + urlencode(params, doseq=True) if params else "")
    with urlopen(Request(full, headers={"User-Agent": "python"}), timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))

def _strip_html(s):
    import re
    return re.sub(r"<[^>]+>", "", unescape(s or ""))

def _check_answer(answerline_html, given):
    params = {"answerline": answerline_html or "", "givenAnswer": given or ""}
    try:
        j = _get_json(API_CHECK_ANSWER, params, timeout=12)
        return (j or {}).get("directive", "reject")
    except Exception:
        return "reject"

def _bonus_key(b):
    bid = b.get("id") or b.get("_id")
    if bid: return str(bid)
    seto = b.get("set") or {}; pkt = b.get("packet") or {}
    return f"{seto.get('name','?')}|{seto.get('year','?')}|{pkt.get('number','?')}|{b.get('number','?')}"

def _batched_fetch(level_idx, category, subcat, alts, want_mods, seen):
    _, api_diff = LEVELS[level_idx]
    base = {
        "difficulties": api_diff, "threePartBonuses": True, "standardOnly": True,
        "categories": category, "number": BATCH_N,
    }
    if subcat: base["subcategories"] = subcat
    if alts:   base["alternateSubcategories"] = alts
    for _ in range(MAX_BATCHES):
        try:
            bonuses = _get_json(API_RANDOM_BONUS, base).get("bonuses", []) or []
            pool = []
            for b in bonuses:
                if _bonus_key(b) in seen: continue
                mods = b.get("difficultyModifiers")
                has_mods = isinstance(mods, (list, tuple)) and len(mods) > 0
                if want_mods and not has_mods: continue
                pool.append(b)
            if pool: return random.choice(pool)
        except Exception:
            time.sleep(0.25)
    return None

def _progressive_fetch(level_idx, category, subcat, alts, seen):
    # 1) mods+subcat
    b = _batched_fetch(level_idx, category, subcat, alts, True, seen)
    if b: return b, "mods+subcat"
    # 2) any+subcat
    b = _batched_fetch(level_idx, category, subcat, alts, False, seen)
    if b: return b, "any+subcat"
    # 3) any+broad
    b = _batched_fetch(level_idx, category, None, None, False, seen)
    if b: return b, "any+broad"
    # 4) neighbors in broad
    neigh = []
    if level_idx > 0: neigh.append(level_idx-1)
    if level_idx < len(LEVELS)-1: neigh.append(level_idx+1)
    random.shuffle(neigh)
    for li in neigh:
        b = _batched_fetch(li, category, None, None, False, seen)
        if b: return b, "any+neighbor"
    return None, ""

def _split_bonus(b):
    leadin = b.get("leadin_sanitized") or _strip_html(b.get("leadin", ""))
    parts  = b.get("parts_sanitized") or [_strip_html(p) for p in (b.get("parts") or [])]
    answers= b.get("answers") or b.get("answers_sanitized") or []
    return leadin, parts, answers

def _detect_medium_idx_from_mods(b, n):
    mods = b.get("difficultyModifiers")
    if isinstance(mods, (list, tuple)) and n>0:
        for i, v in enumerate(mods[:n]):
            if str(v).lower().startswith("m"): return i
        return 1 if n>=2 else 0
    return None

def _rasch_update(theta, b_anchor, correct):
    P = 1.0/(1.0+math.exp(-(theta-b_anchor)))
    theta = theta + THETA_STEP*((1.0-P) if correct else -P)
    theta = max(-4.0, min(4.0, theta))
    return theta, P

def _level_from_theta(theta):
    best, gap = 0, 9e9
    for i,(name,_) in enumerate(LEVELS):
        g = abs(theta - LEVEL_ANCHOR[name])
        if g < gap: best, gap = i, g
    return best

@app.route("/")
def home():
    return render_template("index.html")

@app.post("/api/start")
def start():
    data = request.get_json(force=True) or {}
    category     = (data.get("category") or "").title()
    subcategory  = (data.get("subcategory") or None)
    alts         = data.get("alternateSubcategories") or None
    rounds       = int(data.get("rounds") or 10)

    session["cat"]  = category
    session["sub"]  = subcategory
    session["alts"] = alts
    session["N"]    = rounds
    session["r"]    = 0
    session["theta"]= 0.0
    session["info"] = 0.0
    session["seen"] = set()  # cannot store set in session directly; store as list
    session.modified = True
    return jsonify(ok=True)

@app.get("/api/next")
def next_question():
    # load session
    category = session.get("cat"); sub = session.get("sub"); alts = session.get("alts")
    r = session.get("r", 0); N = session.get("N", 10)
    theta = float(session.get("theta", 0.0))
    seen  = set(session.get("seen", []))

    if r >= N:
        return jsonify(done=True)

    level_idx = _level_from_theta(theta)
    b, mode = _progressive_fetch(level_idx, category, sub, alts, seen)
    if not b:
        return jsonify(error="sparse"), 200

    key = _bonus_key(b); seen.add(key)
    leadin, parts, answers = _split_bonus(b)
    n = min(len(parts), len(answers))
    if n == 0:
        return jsonify(error="malformed"), 200

    if mode == "mods+subcat":
        mid = _detect_medium_idx_from_mods(b, n)
        idx = (mid if (mid is not None and 0<=mid<n) else (1 if n>=2 else 0))
        label = "Medium Part" if mid is not None else "Second Clue (mods missing)"
    else:
        idx = 1 if n>=2 else 0
        label = "Second Clue (fallback)"

    seto = b.get("set") or {}; pkt = b.get("packet") or {}
    meta = {
        "set": seto.get("name","Unknown set"),
        "year": seto.get("year","?"),
        "packet": pkt.get("number","?"),
        "qnum": b.get("number","?")
    }

    # store current answerline and idx in session for grading
    session["curr_ans_html"] = answers[idx]
    session["r"] = r+1
    session["seen"] = list(seen)
    session["label"] = label
    session["leadin"] = leadin
    session["showLeadin"] = ((r) % 3 == 0)  # 1st/4th/7th...
    session["anchor_level"] = LEVELS[level_idx][0]
    session.modified = True

    return jsonify(
        done=False,
        mode=mode,
        label=label,
        showLeadin=session["showLeadin"],
        leadin=leadin,
        prompt=parts[idx],
        meta=meta,
        level=session["anchor_level"],
        theta=theta
    )

@app.post("/api/answer")
def answer():
    data = request.get_json(force=True) or {}
    user = data.get("answer","").strip()
    override = str(data.get("override","")).lower().startswith("y")

    ans_html = session.get("curr_ans_html","")
    theta = float(session.get("theta", 0.0))
    level_name = session.get("anchor_level","HS-Regular")
    b_anchor = LEVEL_ANCHOR.get(level_name, 0.0)

    verdict = _check_answer(ans_html, user)
    correct = (verdict=="accept")

    if verdict == "prompt" and not override:
        # tell client to refine
        return jsonify(prompt=True, message="Prompt — be more specific."), 200

    if override:
        correct = True
        verdict = "accept"

    theta, P = _rasch_update(theta, b_anchor, correct)
    info = float(session.get("info", 0.0)) + P*(1-P)
    se = (1/math.sqrt(info)) if info>0 else float("inf")
    lo, hi = theta - 1.96*se, theta + 1.96*se

    session["theta"] = theta
    session["info"]  = info
    session.modified = True

    return jsonify(
        correct=correct,
        verdict=verdict,
        officialAnswer=_strip_html(ans_html),
        theta=round(theta, 2),
        se=(round(se,2) if se!=float("inf") else None),
        ci=[round(lo,2), round(hi,2)] if info>0 else None
    )
