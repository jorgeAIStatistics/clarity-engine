"""Entity linking for question spans, with the hijack guard as a hard filter.

What this is: character n-gram TF-IDF vectors over every EntityAlias string, cosine retrieval,
then a filter. It is a lexical vector space, not a learned or neural embedding — no model is
trained and no API is called. It exists because exact alias matching misses ordinary variation
("Interleukin 18 levels", "chromogranin-A", "NT pro BNP") while remaining the only safe rule for
deciding what a question is about.

The filter is what keeps the graph honest, and it is deliberately stricter than the retrieval:
a candidate survives only when an alias is literally present in the span, or when it is both
similar enough AND shares a word stem with the span. Similarity alone can never attach an entity,
so a breast-cancer celebrity (BRCA, HER2, mammography) cannot ride along on an IL-18 title.

    python -m ml.linker          # gold-set and robustness evaluation
"""
import json
import re
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

REGISTRY = Path(__file__).resolve().parents[1] / "evidence" / "intent_graph"
THRESHOLD = 0.62
TOP_K = 5
STOP = {"the", "and", "for", "with", "in", "of", "a", "an", "to", "on", "by", "levels", "level", "test", "testing"}


def stems(text):
    """Crude word stems: enough to say two strings talk about the same thing, no more."""
    words = [w for w in re.split(r"[^a-z0-9]+", str(text).lower()) if w and w not in STOP]
    return {w[:-1] if len(w) > 4 and w.endswith("s") else w for w in words}


def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", str(text).lower()).strip()


# eGFR and EGFR are different molecules that differ only in case. For short alias tokens, case is
# not decoration: it is the identity, so those aliases are matched case-sensitively.
ACRONYM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9+./-]{0,7}$")


def case_sensitive(alias):
    return bool(ACRONYM.match(str(alias).strip())) and str(alias) != str(alias).lower()


def squeeze(text):
    return re.sub(r"[^A-Za-z0-9]+", "", str(text))


def present(alias, span):
    """Is this alias written in this span, respecting case when the alias is an acronym?

    Punctuation and spacing are not identity ("CA 125" is "CA-125"), but case is: eGFR is not EGFR.
    """
    target, haystack = squeeze(alias), squeeze(span)
    if not target:
        return False
    if not case_sensitive(alias):
        target, haystack = target.lower(), haystack.lower()
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(target)}(?![A-Za-z0-9])", haystack) is not None or target == haystack


def word_parts(text):
    """Words with their internal punctuation squeezed, so IL-18 is one word and not two.

    norm() splits IL-18 into "il 18", which then sits inside nothing: the containment test below
    could not see that the IL-18 protein is named inside "IL18 gene", and both were attached.
    Squeezing per word keeps the guard that matters — "ER" is still not inside "breast cancer".
    """
    return [squeeze(w).lower() for w in re.split(r"\s+", str(text).strip()) if squeeze(w)]


def inside(short, long):
    """Is one name a run of whole words inside the other? Substrings do not count."""
    a, b = word_parts(short), word_parts(long)
    if not a or len(a) >= len(b):
        return False
    return any(b[i:i + len(a)] == a for i in range(len(b) - len(a) + 1))


def prefix_of(alias, span):
    a, b = squeeze(alias).lower(), squeeze(span).lower()
    return len(b) >= 4 and len(a) >= 4 and (a.startswith(b) or b.startswith(a))


class AliasIndex:
    def __init__(self, nodes, common=2):
        self.rows = [(node["id"], node["type"], alias) for node in nodes for alias in node["aliases"]]
        self.vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        self.matrix = self.vectorizer.fit_transform([norm(alias) for _, _, alias in self.rows])
        self.by_id = {node["id"]: node for node in nodes}
        # Which alias words are distinctive is read off the registry, not from a hand-written list:
        # "mutation", "cancer" and "screening" name many entities, so sharing one says nothing.
        owners = {}
        for node in nodes:
            for token in {t for alias in node["aliases"] for t in stems(alias)}:
                owners.setdefault(token, set()).add(node["id"])
        self.distinctive = {token for token, ids in owners.items() if len(ids) <= common}
        # A name written in the question must never depend on how cosine ranked it: two-letter
        # acronyms like ER never reach a char n-gram top-k, and they are still the answer.
        self.exact = {}
        for entity_id, _, alias in self.rows:
            self.exact.setdefault(squeeze(alias) if case_sensitive(alias) else squeeze(alias).lower(), []).append((entity_id, alias))

    def specific(self, alias):
        return stems(alias) & self.distinctive

    def candidates(self, span, k=TOP_K):
        scores = cosine_similarity(self.vectorizer.transform([norm(span)]), self.matrix)[0]
        best = {}
        for index in scores.argsort()[::-1][: k * 4]:
            entity_id, _, alias = self.rows[index]
            if entity_id not in best or scores[index] > best[entity_id][0]:
                best[entity_id] = (float(scores[index]), alias)
            if len(best) >= k:
                break
        return sorted(({"id": i, "score": s, "alias": a} for i, (s, a) in best.items()), key=lambda c: -c["score"])

    def written(self, span):
        """Entities whose alias is literally this span, found without retrieval."""
        key = squeeze(span)
        return [{"id": entity_id, "alias": alias, "score": 1.0, "reason": "alias_in_span"}
                for entity_id, alias in self.exact.get(key, []) + self.exact.get(key.lower(), [])
                if present(alias, span)]

    def link(self, span, k=TOP_K, threshold=THRESHOLD):
        """Candidates that survive the filter, with the reason each one survived."""
        span_stems, span_norm = stems(span), norm(span)
        kept = list({c["id"]: c for c in self.written(span)}.values())
        seen = {c["id"] for c in kept}
        for candidate in (c for c in self.candidates(span, k) if c["id"] not in seen):
            alias = candidate["alias"]
            if present(alias, span):
                kept.append({**candidate, "reason": "alias_in_span"})
            elif case_sensitive(alias):
                continue  # an acronym that is not written here, in this case, is not this entity
            elif candidate["score"] >= threshold and prefix_of(alias, span) and self.specific(alias) & span_stems:
                # Similarity alone attaches nothing: one string must be the start of the other, so
                # "neurofilament light" reaches its chain but "associated" reaches no-one.
                kept.append({**candidate, "reason": "one_name_starts_the_other"})
        return kept

    def best(self, span, **kw):
        kept = self.link(span, **kw)
        if not kept:
            return None
        exact = [c for c in kept if c["reason"] == "alias_in_span"]
        pool = exact or kept
        # The most specific match wins: the longest alias, then the highest similarity.
        winner = max(pool, key=lambda c: (len(norm(c["alias"])), c["score"]))
        return winner["id"], winner["alias"], winner["reason"]


def spans_of(question, nodes):
    """Every alias-sized window of the question, so the linker sees the same spans the parser would."""
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9+.\-/]*", question)
    widest = max(len(re.findall(r"\S+", alias)) for node in nodes for alias in node["aliases"])
    return [" ".join(words[i:i + n]) for n in range(1, min(widest, 6) + 1) for i in range(len(words) - n + 1)]


def resolve_question(index, question, nodes):
    # Keep the BEST evidence for each entity, not the last window that happened to match it. A
    # literal alias written in the span beats a prefix or vector match, and a longer written alias
    # beats a shorter one. Keeping the last hit let "IL18 gene polymorphism and" overwrite the
    # literal "IL18 gene", which disarmed the suppression rule below and attached the IL-18 protein
    # to a question about the IL18 gene.
    found, literal = {}, {}
    strength = {}
    for span in spans_of(question, nodes):
        hit = index.best(span)
        if hit:
            entity_id, alias, reason = hit
            score = (reason == "alias_in_span", len(str(alias)))
            if score >= strength.get(entity_id, (False, -1)):
                found[entity_id] = span
                literal[entity_id] = reason == "alias_in_span"
                strength[entity_id] = score
    # "EGFR" inside "EGFR mutation" is the gene inside the variant: keep the more specific entity.
    # Only an entity whose own matched alias is contained in another's is dropped, so a drug named
    # beside a marker ("response to trastuzumab") keeps both.
    aliases = {entity_id: (index.by_id[entity_id]["aliases"] if entity_id in index.by_id else []) for entity_id in found}
    def matched_alias(entity_id, span):
        written = [a for a in aliases[entity_id] if present(a, span)]
        return max(written, key=len) if written else span
    chosen = {entity_id: matched_alias(entity_id, span) for entity_id, span in found.items()}
    for entity_id, alias in list(chosen.items()):
        # Only a name actually written in the question may suppress another entity, and only when
        # it contains that name as whole words: "ER" is not inside "breast cancer".
        if any(other != entity_id and literal.get(other) and inside(alias, chosen[other]) for other in chosen):
            found.pop(entity_id, None)
    return set(found)


def evaluate():
    nodes = json.loads((REGISTRY / "registry.json").read_text())
    cases = json.loads((REGISTRY / "gold.json").read_text())
    index = AliasIndex(nodes)
    tp = fp = fn = 0
    hijacks, misses = [], []
    for case in cases:
        found = resolve_question(index, case["question"], nodes)
        expected, forbidden = set(case["expected"]), set(case["forbidden"])
        tp += len(found & expected)
        fp += len(found - expected)
        fn += len(expected - found)
        if found & forbidden:
            hijacks.append({"question": case["question"], "attached": sorted(found & forbidden)})
        if found != expected:
            misses.append({"question": case["question"], "expected": sorted(expected), "found": sorted(found)})
    gold = {"cases": len(cases), "precision": tp / (tp + fp) if tp + fp else 0, "recall": tp / (tp + fn) if tp + fn else 0,
            "true_positives": tp, "false_positives": fp, "false_negatives": fn, "hijacks": hijacks, "mismatches": misses}

    # Where exact matching fails and this is meant to help: ordinary spelling and spacing variation.
    robustness = [("Interleukin 18 levels", "biomarker:il-18"), ("IL18", "biomarker:il-18"),
                  ("chromogranin-A", "biomarker:chromogranin-a"), ("Chromogranin  A", "biomarker:chromogranin-a"),
                  ("NT pro BNP", "biomarker:nt-probnp"), ("CA 125", "biomarker:ca-125"),
                  ("CA-19-9", "biomarker:ca19-9"), ("neurofilament light", "biomarker:nfl"),
                  ("EGFR mutations", "variant:egfr-activating-mutation"), ("p-tau 181", "biomarker:p-tau181")]
    from evidence.intent_graph.intent import alias_present
    exact_hits = sum(1 for span, want in robustness if any(alias_present(a, span) for a in index.by_id.get(want, {"aliases": []})["aliases"]))
    linked = {span: (index.best(span) or (None, None, None))[0] for span, _ in robustness}
    linker_hits = sum(1 for span, want in robustness if linked[span] == want)
    detail = [{"span": span, "expected": want, "linked": linked[span]} for span, want in robustness]
    return {"version": "clarity-linker-v1", "method": "char n-gram TF-IDF over alias strings, cosine retrieval, hard filter (no learned embedding)",
            "threshold": THRESHOLD, "gold": gold,
            "robustness": {"cases": len(robustness), "exact_alias_matches": exact_hits, "linker_matches": linker_hits, "detail": detail}}


if __name__ == "__main__":
    report = evaluate()
    print(json.dumps(report, indent=1))
