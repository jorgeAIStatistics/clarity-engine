"""Backfill study abstracts into existing Clarity profiles WITHOUT re-grading.

Why: older profiles intentionally stored compact study rows (PMID/title/design/N),
but Ask Clarity needs the actual abstract text to answer specific questions.
This script fetches abstracts by the PMIDs already bound to each claim, attaches
only source text/metadata, and leaves every tier, score, outcome and effect intact.

Usage:
  python3 add_ask_context.py --limit 3   # test
  python3 add_ask_context.py             # all profiles
  python3 add_ask_context.py --force     # replace already-present abstracts

If DATABASE_URL is configured, profiles are updated in Postgres directly.
Local cache/*.json files are also updated when present.
"""
import argparse, glob, json, os
import pubmed


def load_profiles(limit=None):
    rows=[]
    try:
        import db
        if db.available():
            for slug in db.list_cached():
                p=db.get(slug,max_age_days=100000)
                if p and p.get("claims"): rows.append((slug,p,"db"))
            if rows:
                return rows[:limit] if limit else rows
    except Exception as e:
        print(f"[ask-context] DB unavailable ({type(e).__name__}); using files")
    for path in sorted(glob.glob(os.path.join("cache","*.json"))):
        try: p=json.load(open(path))
        except Exception: continue
        if p.get("claims"):
            slug=os.path.splitext(os.path.basename(path))[0]
            rows.append((slug,p,"file"))
    return rows[:limit] if limit else rows


def save_profile(slug,p,source):
    ok=False
    try:
        import db
        if db.available(): ok=bool(db.put(slug,p))
    except Exception: pass
    path=os.path.join("cache",f"{slug}.json")
    if os.path.exists(path) or source=="file":
        os.makedirs("cache",exist_ok=True)
        with open(path,"w") as f: json.dump(p,f,indent=2,ensure_ascii=False)
        ok=True
    return ok


def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--limit",type=int); ap.add_argument("--force",action="store_true"); args=ap.parse_args()
    profiles=load_profiles(args.limit)
    if not profiles:
        print("No profiles found."); return

    wanted=set(); already=0
    for slug,p,source in profiles:
        for c in p.get("claims") or []:
            for s in c.get("studies") or []:
                pmid=str(s.get("pmid") or "").strip()
                if not pmid: continue
                if s.get("abstract") and not args.force: already += 1
                else: wanted.add(pmid)
    print(f"Profiles: {len(profiles)} | abstracts already present: {already} | PMIDs to fetch: {len(wanted)}")
    if not wanted:
        print("Nothing to backfill."); return

    fetched=pubmed.efetch(sorted(wanted))
    by_id={str(x.get("pmid")):x for x in fetched if x.get("pmid")}
    print(f"Fetched {len(by_id)} PubMed records.")

    changed_profiles=changed_studies=0
    for i,(slug,p,source) in enumerate(profiles,1):
        changed=False
        for c in p.get("claims") or []:
            for s in c.get("studies") or []:
                pmid=str(s.get("pmid") or "").strip(); rec=by_id.get(pmid)
                if not rec: continue
                if args.force or not s.get("abstract"):
                    abstract=(rec.get("abstract") or "").strip()
                    if abstract:
                        s["abstract"]=abstract[:3000]; changed=True; changed_studies += 1
                if rec.get("journal") and (args.force or not s.get("journal")):
                    s["journal"]=str(rec.get("journal"))[:180]; changed=True
        if changed:
            if save_profile(slug,p,source): changed_profiles += 1
        if i % 20 == 0: print(f"  processed {i}/{len(profiles)}")
    print(f"Done. Updated {changed_studies} study rows across {changed_profiles} profiles. No grades changed.")

if __name__ == "__main__": main()
