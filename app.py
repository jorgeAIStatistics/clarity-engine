"""Clarity Engine HTTP API — cache-first profiles + fast grounded Ask Clarity."""
import os, time, threading
from collections import defaultdict
from flask import Flask, request, jsonify
from flask_cors import CORS

import run
import cache
import ask_engine
import indications
import generate

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

# Production CORS is explicit. Set CLARITY_ALLOWED_ORIGINS to the comma-separated
# public frontend origin(s). Local Vite origins are allowed for development.
_raw_origins = os.environ.get("CLARITY_ALLOWED_ORIGINS", "").strip()
_allowed_origins = [x.strip() for x in _raw_origins.split(",") if x.strip()] or [
    "http://localhost:5173", "http://127.0.0.1:5173"
]
CORS(app, resources={r"/api/*": {"origins": _allowed_origins}})

DAILY_GENERATION_CAP = int(os.environ.get("CLARITY_DAILY_CAP", "50"))
PER_IP_MIN_INTERVAL = float(os.environ.get("CLARITY_IP_INTERVAL", "3.0"))
ASK_IP_MIN_INTERVAL = float(os.environ.get("CLARITY_ASK_IP_INTERVAL", "0.35"))
MAX_TOPIC_LEN = 80
MAX_QUESTION_LEN = 1200
ALLOW_LIVE_GENERATION = os.environ.get("CLARITY_ALLOW_LIVE_GENERATION", "0").strip().lower() in {"1", "true", "yes"}

_lock = threading.Lock()
_gen_day = [time.strftime("%Y-%m-%d"), 0]
_last_ip_call = defaultdict(float)
_last_ask_call = defaultdict(float)


def _client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",", 1)[0].strip()
    return request.remote_addr or "unknown"


def _profile_current(profile):
    if not profile:
        return False
    return (profile.get("engine_version") == generate.ENGINE_VERSION
            and int(profile.get("schema_version") or 0) >= generate.PROFILE_SCHEMA_VERSION)


@app.after_request
def _security_headers(resp):
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.path.startswith("/api/ask"):
        resp.headers["Cache-Control"] = "no-store"
    return resp


def _valid_topic(t):
    if not t or len(t) > MAX_TOPIC_LEN:
        return False
    allowed_punct = set(" -_()/+,.'")
    return all(c.isalnum() or c in allowed_punct for c in t)


def _rate_limited(ip, ask=False):
    now=time.time(); table=_last_ask_call if ask else _last_ip_call; gap=ASK_IP_MIN_INTERVAL if ask else PER_IP_MIN_INTERVAL
    with _lock:
        if now - table[ip] < gap: return True
        table[ip]=now
    return False


def _generation_budget_ok():
    today=time.strftime("%Y-%m-%d")
    with _lock:
        if _gen_day[0] != today: _gen_day[0],_gen_day[1]=today,0
        return _gen_day[1] < DAILY_GENERATION_CAP


def _count_generation():
    with _lock: _gen_day[1]+=1


def _resolve(topic, category=None):
    note=None
    try:
        import aliases as _aliases
        resolved, resolved_cat, note = _aliases.resolve(topic)
        if resolved: topic=resolved
        if resolved_cat: category=resolved_cat
    except Exception:
        pass
    return topic, category, note


@app.get("/api/health")
def health():
    return jsonify({"ok":True,"generations_today":_gen_day[1],"daily_cap":DAILY_GENERATION_CAP,
                    "ask_engine":"v2-fast-retrieval","indication_engine":"v1-canonical-outcomes",
                    "engine_version":generate.ENGINE_VERSION,
                    "schema_version":generate.PROFILE_SCHEMA_VERSION,
                    "live_generation":ALLOW_LIVE_GENERATION})


@app.get("/api/cached")
def cached():
    internal={"effect_sizes","llm_population","effect-sizes","llm-population","explanations","appraisals","translations","pubchem","directions","outcomes","citations","pharmacokinetics"}
    return jsonify({"cached":[s for s in cache.list_cached() if s not in internal]})


def _catalog_row_from_profile(slug, p, base=None):
    row=dict(base or {})
    row.update({"slug":slug,"name":p.get("name") or row.get("name") or slug,
                "category":p.get("category") or row.get("category"),
                "tier":p.get("tier") or row.get("tier"),
                "study_count":p.get("study_count",row.get("study_count",0)),
                "engine_version":p.get("engine_version"),
                "schema_version":p.get("schema_version"),
                "generated_at":p.get("generated_at")})
    row["stale"] = not _profile_current(p)
    try:
        row.update(indications.catalog_meta(p))
    except Exception:
        pass
    return row


@app.get("/api/catalog")
def catalog():
    rows=[]
    try:
        import db
        rows=db.list_catalog() if db.available() else []
    except Exception:
        rows=[]
    if rows:
        # Only vitamin cards need the outcome-aware metadata, so avoid parsing
        # 140 full JSON profiles just to build the lightweight catalog response.
        enriched=[]
        for row in rows:
            # New profiles already carry outcome-aware metadata in JSONB-backed
            # catalog fields. Vitamins still get a full-profile enrichment so
            # classic deficiency-vs-general-use differences are handled precisely.
            if row.get("outcome_dependent") and not row.get("display_tier"):
                row["display_tier"] = "Outcome-dependent"
            if str(row.get("category") or "").lower()=="vitamin":
                try:
                    p=cache.get(row.get("slug") or row.get("name")) or cache.get(row.get("name"))
                except Exception:
                    p=None
                if p:
                    row=_catalog_row_from_profile(row.get("slug") or row.get("name"),p,row)
            row["stale"] = (row.get("engine_version") != generate.ENGINE_VERSION
                            or int(row.get("schema_version") or 0) < generate.PROFILE_SCHEMA_VERSION)
            enriched.append(row)
        rows=enriched
    else:
        internal={"effect_sizes","llm_population","effect-sizes","llm-population","explanations","appraisals","translations","pubchem","directions","outcomes","citations","pharmacokinetics"}
        for slug in cache.list_cached():
            if slug in internal: continue
            try: p=cache.get(slug)
            except Exception: p=None
            if not p or not p.get("claims"): continue
            rows.append(_catalog_row_from_profile(slug,p))
    return jsonify({"catalog":rows})


@app.get("/api/profile")
def profile():
    topic=(request.args.get("topic") or "").strip(); category=(request.args.get("category") or "supplement").strip()
    ip=_client_ip()
    if not _valid_topic(topic): return jsonify({"error":"invalid topic"}),400
    topic,category,note=_resolve(topic,category)
    p=cache.get(topic)
    if p and _profile_current(p):
        return jsonify({"profile":p,"source":"cache","alias_note":note})
    # A stale profile is never served as current evidence, but it is deliberately
    # kept until the fresh replacement succeeds (run.research overwrites it).
    # Public launch defaults to an audited, pre-generated catalog. This prevents
    # an arbitrary user query from publishing a brand-new, unaudited profile.
    if not ALLOW_LIVE_GENERATION:
        if p:
            return jsonify({"error":"profile refresh required","code":"STALE_PROFILE","hint":"This profile was built by an older evidence engine and is temporarily unavailable until the catalog refresh completes."}),409
        return jsonify({"error":"compound not in audited catalog","code":"NOT_IN_CATALOG","hint":"Clarity currently serves the pre-generated, audited catalog only."}),404
    if _rate_limited(ip): return jsonify({"error":"rate limited; try again in a few seconds"}),429
    if not _generation_budget_ok(): return jsonify({"error":"daily research limit reached; try again tomorrow","hint":"already-researched compounds are still available"}),503
    try:
        _count_generation(); result=run.research(topic,category,use_cache=True,verbose=False)
        return jsonify({"profile":result,"source":"generated","alias_note":note})
    except Exception as e:
        return jsonify({"error":"generation failed","detail":type(e).__name__}),500


@app.post("/api/ask")
def ask():
    body=request.get_json(silent=True) or {}
    topic=str(body.get("topic") or "").strip(); category=str(body.get("category") or "supplement").strip()
    question=str(body.get("question") or "").strip(); history=body.get("history") or []; language=str(body.get("language") or "en")[:2]
    ip=_client_ip()
    if not _valid_topic(topic) or not question or len(question)>MAX_QUESTION_LEN: return jsonify({"error":"invalid request"}),400
    if _rate_limited(ip,ask=True): return jsonify({"error":"one moment between questions"}),429
    topic,category,_=_resolve(topic,category)
    # Bound conversational context so one public request cannot become an
    # arbitrarily large paid-model prompt.
    clean_history=[]
    for item in list(history)[-6:]:
        if not isinstance(item,dict): continue
        role=item.get("role")
        if role not in ("user","assistant"): continue
        clean_history.append({"role":role,"content":str(item.get("content") or "")[:1200]})
    p=cache.get(topic)
    if not p: return jsonify({"answer":"Research this compound first so I can answer from its graded evidence.","grounded":False}),404
    if not _profile_current(p):
        return jsonify({"answer":"This profile was generated by an older evidence engine and needs to be refreshed before Ask Clarity can use it.","grounded":False,"refresh_required":True}),409
    try:
        result=ask_engine.answer(p,question,history=clean_history,language=language)
    except Exception as e:
        return jsonify({"error":"ask failed","detail":type(e).__name__}),500
    try:
        import db
        eid=db.log_ask_event(topic,question,result.get("answer"),result.get("grounded",True),result.get("coverage"),result.get("retrieved_studies",0),result.get("mode")) if db.available() and hasattr(db,"log_ask_event") else None
        if eid: result["event_id"]=eid
    except Exception:
        pass
    return jsonify(result)


@app.post("/api/ask/feedback")
def ask_feedback():
    body=request.get_json(silent=True) or {}; eid=body.get("event_id"); helpful=body.get("helpful")
    if eid is None or not isinstance(helpful,bool): return jsonify({"error":"invalid request"}),400
    try:
        import db
        ok=db.set_ask_feedback(eid,helpful) if db.available() and hasattr(db,"set_ask_feedback") else False
    except Exception: ok=False
    return jsonify({"ok":bool(ok)})


if __name__ == "__main__":
    port=int(os.environ.get("PORT","8000")); app.run(host="0.0.0.0",port=port,debug=False)
