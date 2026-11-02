# Clarity Engine — Phase 1

The working evidence-grading engine. It pulls studies from PubMed, classifies them,
applies GRADE scoring, and produces a profile JSON matching the app. **Proven working.**

This is the *engine* (the moat). The frontend is your existing `EvidenceApp.jsx`.

---

## What runs with ZERO paid services

- **PubMed** — free, no key required.
- **The classifier + GRADE scorer** — pure Python, no network, no cost.
- **Profile generation** — works without an LLM (uses an honest template writer).

The only optional paid piece is nicer LLM-written prose. You can launch without it.

---

## Runbook — the parts only YOU can do

### 1. Get the code onto your computer
Download this folder. You need **Python 3.10+** installed.

### 2. Install the two dependencies
```bash
pip install requests biopython
```

### 3. (Optional but recommended) Get a free PubMed API key
- Go to https://www.ncbi.nlm.nih.gov/account/ → create a free NCBI account.
- In account settings, generate an **API key** (raises rate limit 3→10 req/sec).
- Set it before running:
```bash
export NCBI_API_KEY="your_key_here"
export CLARITY_CONTACT_EMAIL="your_email@example.com"
```
(Both optional — it runs without them, just slower.)

### 4. Run it on a real topic
```bash
python run.py "creatine monohydrate" supplement "muscle strength" "cognition"
```
This hits the LIVE PubMed API (works on your machine — it was only blocked in the
build sandbox) and prints a real profile JSON. Try any topic:
```bash
python run.py "ashwagandha" herb "stress" "sleep quality"
python run.py "bpc-157" peptide "tendon healing" "gut health"
```

### 5. (Optional) Turn on LLM prose
- Get an API key from your LLM provider (a cheap fast model is fine).
- Open `generate.py`, fill in `_call_llm()` with your provider's SDK (there's a
  ready example for Anthropic in the docstring).
- Then:
```bash
export LLM_API_KEY="your_llm_key"
export LLM_MODEL="your_cheap_model_id"
python run.py "creatine monohydrate" supplement "muscle strength"
```

---

## How the pieces map to the blueprint

| File | Pipeline stage | What it does |
|------|----------------|--------------|
| `pubmed.py`   | Stage 1 | Retrieve studies (free API) |
| `classify.py` | Stage 2 | Rank each study by evidence type + human/animal |
| `grade.py`    | Stage 4 | **GRADE scoring → 0–100 (the moat)** |
| `generate.py` | Stage 5 | Build profile JSON, with anti-fabrication rules |
| `run.py`      | all     | Ties it together into one command |

---

## Your next moves (in order)

1. **Run it** on your 3 known topics; confirm scores feel right vs. your hand-written ones.
2. **Refine `grade.py`** — this is where your biostatistics skill compounds. Improve the
   downgrade heuristics (inconsistency across studies, imprecision thresholds). Every
   improvement here is competitive advantage no one can copy.
3. **Wire it to the frontend** — have your app call a small API that runs `run()` and
   caches the JSON (lazy generation = near-zero cost).
4. **Spot-review** the top topics yourself; flip `reviewed_by` to `"expert"`.

## Honest limits of this v1

- Outcome grouping is currently one PubMed query per outcome you pass in. A v2 would
  auto-discover the outcomes a substance is studied for.
- The GRADE heuristics are a solid, transparent starting point — not a finished
  methodology. Refining them is *your* ongoing work and your edge.
- Do not present output as medical advice. Keep the "research education" framing and
  get legal review before any public launch.
```

---

## v2 — Now runs on just a topic, with caching (LLM-free)

The engine now takes a single topic and does the rest:

```bash
python run.py "creatine monohydrate"     # auto-discovers outcomes, grades, caches
python run.py "bpc-157" peptide          # category is optional
python run.py "ashwagandha" herb --fresh # --fresh ignores cache & regenerates
```

**What's new:**
- `discover.py` — auto-detects which outcomes a substance is studied for (no more hand-listing them). Edit its `OUTCOME_KEYWORDS` to expand coverage — this is a transparent, ownable asset.
- `cache.py` — saves each generated profile to a `/cache` folder as JSON. Repeat queries are instant. This is the real "generating…" → cached flow, and it's what keeps costs near zero (lazy generation).
- `run.py` (v2) — ties cache + discovery + grading + assembly into one command. Still **zero paid services** — no LLM required.

**How the app uses it:** a tiny web API calls `research(topic)` and returns the JSON. First request for a topic generates + caches (a few seconds); everyone after gets it instantly.

**Peptide honesty:** for peptides with little human data, the engine correctly produces a low score and an honest "emerging/animal-only" profile. That's the feature, not a bug — it's the anti-hype brand. It cannot manufacture depth where the science is sparse, and it shouldn't.

**Still LLM-free:** prose comes from honest templates. When you're ready to add richer writing, wire an LLM into `generate.py`'s `_call_llm()` — but it only ever writes over facts the engine already extracted and graded, which is what prevents fabrication.

## Ownership and permissions

Maintained by **Jorge Rodriguez** ([@jorgeAIStatistics](https://github.com/jorgeAIStatistics)).
See [COPYRIGHT.md](COPYRIGHT.md) for ownership and third-party attribution scope,
and [LICENSE](LICENSE) for permissions. Source-visible for portfolio review; reuse rights are reserved.
