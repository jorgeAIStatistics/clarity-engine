"""
Profile one compound to find where the time actually goes.

Two performance 'fixes' made things slower because they were guesses. This
instruments each stage so the bottleneck is measured, not assumed.

    python3 profile_run.py "creatine monohydrate"
"""
import sys
import time
import collections

TIMINGS = collections.defaultdict(float)
COUNTS = collections.defaultdict(int)


def _wrap(module, name, label):
    orig = getattr(module, name)

    def timed(*a, **kw):
        t0 = time.time()
        try:
            return orig(*a, **kw)
        finally:
            TIMINGS[label] += time.time() - t0
            COUNTS[label] += 1
    setattr(module, name, timed)
    return orig


def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else "creatine monohydrate"

    import pubmed, classify, discover, grade, cache
    _wrap(pubmed, "esearch", "pubmed.esearch")
    _wrap(pubmed, "efetch", "pubmed.efetch")
    _wrap(discover, "discover_outcomes_llm", "LLM: discover outcomes")

    try:
        import llm_classify
        _wrap(llm_classify, "resolve", "LLM: classify population")
    except Exception:
        pass
    try:
        import direction
        _wrap(direction, "extract_direction", "LLM: direction")
    except Exception:
        pass
    try:
        import explain
        _wrap(explain, "explain", "LLM: explanation")
    except Exception:
        pass
    try:
        import appraise
        _wrap(appraise, "appraise", "LLM: appraisal")
    except Exception:
        pass
    try:
        import pubchem
        _wrap(pubchem, "fetch", "PubChem")
    except Exception:
        pass

    import run as runner
    cache.invalidate(topic)

    t0 = time.time()
    profile = runner.research(topic, verbose=False)
    total = time.time() - t0

    print(f"\n{topic}: {profile.get('tier')} — {profile.get('study_count')} studies")
    print(f"outcomes: {', '.join(c['outcome'] for c in profile.get('claims', []))}")
    print(f"\nTOTAL {total:.1f}s\n")
    print(f"{'STAGE':32}{'CALLS':>7}{'SECONDS':>10}{'%':>7}")
    for label, secs in sorted(TIMINGS.items(), key=lambda kv: -kv[1]):
        print(f"{label:32}{COUNTS[label]:>7}{secs:>10.1f}{100*secs/max(total,0.01):>6.0f}%")
    acct = sum(TIMINGS.values())
    print(f"{'(unaccounted)':32}{'':>7}{max(0, total-acct):>10.1f}"
          f"{100*max(0, total-acct)/max(total,0.01):>6.0f}%")
    print("\nNote: with parallel outcomes, stage times overlap and can exceed wall time.")


if __name__ == "__main__":
    main()
