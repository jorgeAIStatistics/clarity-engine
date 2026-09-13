"""Fast, grounded Q&A over one Clarity evidence profile.

Design goals:
- instant structured answers for common questions (no model call)
- compact question-specific retrieval for interpretive questions
- use study abstracts/effect quotes when available
- never use outside medical knowledge
- cache repeated questions in-process
"""
from __future__ import annotations

import json, math, os, re, time
from collections import Counter, OrderedDict
from typing import Any, Dict, Iterable, List, Tuple

_STOP = {
    "a","an","and","are","as","at","be","because","been","but","by","can","could","do","does","for","from",
    "had","has","have","how","i","if","in","is","it","its","me","my","of","on","or","should","so","than","that",
    "the","their","them","there","these","they","this","to","was","were","what","when","where","which","who","why",
    "will","with","would","you","your","about","any","much","really","take","taking",
    "un","una","y","o","de","del","la","las","el","los","en","para","por","que","qué","como","cómo","es","son",
    "se","su","sus","me","mi","puede","puedo","tiene",
}

_SYNONYMS = [
    {"safe","safety","risk","risks","adverse","side","effects","tolerability","danger","seguridad","riesgo","adversos"},
    {"weight","fat","obesity","appetite","satiety","loss","metabolic","peso","grasa","apetito","obesidad"},
    {"glucose","sugar","glycemic","insulin","diabetes","glucosa","azucar","azúcar","insulina"},
    {"strength","muscle","performance","exercise","training","fuerza","musculo","músculo","rendimiento"},
    {"sleep","insomnia","circadian","sueño","dormir","insomnio"},
    {"mood","anxiety","stress","depression","estado","animo","ánimo","ansiedad","estrés"},
    {"dose","dosing","dosage","mg","grams","dose-response","dosis","dosificacion","dosificación"},
    {"mechanism","pathway","receptor","works","action","mecanismo","receptor","funciona"},
    {"half-life","pharmacokinetic","pk","absorption","bioavailability","metabolism","clearance","vida","media","farmacocinetica","farmacocinética"},
    {"evidence","study","studies","trial","trials","rct","meta-analysis","research","evidencia","estudio","estudios","ensayo","investigacion","investigación"},
]

_CACHE: OrderedDict[tuple, dict] = OrderedDict()
_CACHE_MAX = int(os.environ.get("CLARITY_ASK_CACHE_SIZE", "256"))


def _tok(text: Any) -> List[str]:
    words = re.findall(r"[a-z0-9][a-z0-9+\-_/\.]*", str(text or "").lower())
    return [w for w in words if len(w) > 1 and w not in _STOP]


def _expand(tokens: Iterable[str]) -> set[str]:
    out = set(tokens)
    for group in _SYNONYMS:
        if out.intersection(group):
            out.update(group)
    return out


def _norm_q(q: str) -> str:
    return " ".join(_tok(q))[:500]


def _cache_key(profile: dict, q: str, lang: str) -> tuple:
    return (str(profile.get("name") or "").lower(), str(profile.get("_cached_at") or profile.get("study_count") or ""), lang, _norm_q(q))


def _cache_get(key):
    v = _CACHE.get(key)
    if v is not None:
        _CACHE.move_to_end(key)
        out = dict(v)
        out["cache_hit"] = True
        out.setdefault("timing", {})["total_ms"] = 0
        return out
    return None


def _cache_put(key, value):
    _CACHE[key] = dict(value)
    _CACHE.move_to_end(key)
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)


def _layers(c):
    return c.get("layers") or {}


def _human_n(c):
    L = _layers(c)
    return int(L.get("n_human_studies") or 0)


def _animal_n(c):
    L = _layers(c)
    return int(L.get("n_animal_studies") or 0)


def _ws(c):
    return c.get("weighted_score") or {}


def _score(c):
    w = _ws(c)
    return w.get("final_score") if w.get("final_score") is not None else c.get("score")


def _claim_sort(c):
    tier_rank = {"Strong":4,"Moderate":3,"Emerging":2,"Preliminary":1}
    return (tier_rank.get(c.get("tier"),0), _human_n(c), float(_score(c) or 0), int(c.get("n_studies") or 0))


def _matched_claims(profile: dict, q: str, limit=4) -> List[dict]:
    claims = profile.get("claims") or []
    qt = _expand(_tok(q))
    scored=[]
    for c in claims:
        out = str(c.get("outcome") or "")
        ot = _expand(_tok(out))
        s = 5.0 * len(qt.intersection(ot))
        if out and out.lower() in q.lower(): s += 12
        summary = str(c.get("summary") or "")
        s += 1.1 * len(qt.intersection(_expand(_tok(summary))))
        scored.append((s,c))
    scored.sort(key=lambda x:(x[0], _claim_sort(x[1])), reverse=True)
    if scored and scored[0][0] > 0:
        return [c for s,c in scored[:limit] if s > 0]
    return sorted(claims, key=_claim_sort, reverse=True)[:limit]


def _effect_sentence(c: dict, es=False) -> str:
    he = c.get("headline_effect") or {}
    if he.get("value") is None:
        return ""
    metric = str(he.get("metric") or "effect").upper()
    val = he.get("value")
    lo, hi = he.get("ci_low"), he.get("ci_high")
    s = f"{metric} {val}"
    if lo is not None and hi is not None:
        s += f" (95% CI {lo}–{hi})"
    return s


def _source_ref(study: dict) -> str | None:
    pmid = str(study.get("pmid") or "").strip()
    if pmid:
        return f"PMID:{pmid}"
    doi = str(study.get("doi") or "").strip().lower()
    if doi:
        return f"DOI:{doi}"
    epmc = str(study.get("epmc_id") or "").strip()
    if epmc:
        return f"EPMC:{epmc}"
    return None


def _instant_answer(profile: dict, question: str, language: str) -> dict | None:
    """Answer high-frequency questions without a model round-trip."""
    q = question.lower()
    es = language == "es"
    claims = profile.get("claims") or []
    expl = profile.get("explanation_es") if es and profile.get("explanation_es") else profile.get("explanation") or {}
    appraisal = profile.get("appraisal_es") if es and profile.get("appraisal_es") else profile.get("appraisal") or {}
    matched = _matched_claims(profile, question, 4)

    def base_meta(answer, coverage="high", pmids=None):
        return {"answer":answer, "pmids":pmids or [], "grounded":True, "coverage":coverage,
                "retrieved_studies":0, "matched_outcomes":[c.get("outcome") for c in matched],
                "model_used":False, "mode":"instant"}

    # What is it / mechanism
    if any(k in q for k in ("what is", "what's this", "what does it do", "mechanism", "how does", "how it works", "qué es", "mecanismo", "cómo funciona")):
        line = expl.get("how_it_works") if any(k in q for k in ("mechanism","how does","how it works","mecanismo","cómo funciona")) else expl.get("what_it_is")
        if line:
            return base_meta(str(line), "high")

    # Safety / risks
    if any(k in q for k in ("safe","safety","risk","risks","side effect","downside","interaction","seguridad","riesgo","efecto advers","interacción")):
        parts=[]
        for key in ("safety_line","safety_detail","caveats"):
            if expl.get(key) and str(expl.get(key)) not in parts: parts.append(str(expl.get(key)))
        for b in (expl.get("safety_bullets") or [])[:4]: parts.append(str(b))
        if isinstance(appraisal, dict) and appraisal.get("headline"): parts.append(str(appraisal.get("headline")))
        if parts:
            answer = ("Lo que respalda el perfil actual:\n" if es else "What the current profile supports:\n") + "\n".join(f"• {p}" for p in parts[:6])
            return base_meta(answer, "medium")

    # How many studies / people / animals
    if any(k in q for k in ("how many studies","how many human","how many animal","number of studies","cuántos estudios","cuantos estudios")):
        total = int(profile.get("study_count") or 0)
        h = int(profile.get("unique_human_study_count") or 0)
        a = int(profile.get("unique_animal_study_count") or 0)
        memberships = int(profile.get("outcome_study_memberships") or 0)
        ans = (f"Clarity currently grades {total} unique studies across {len(claims)} major outcomes: {h} unique human studies and {a} unique animal studies. The outcome cards contain {memberships} study-to-outcome memberships because one paper can inform more than one outcome."
               if not es else f"Clarity califica actualmente {total} estudios únicos en {len(claims)} resultados principales: {h} estudios humanos únicos y {a} estudios animales únicos. Las tarjetas de resultados contienen {memberships} asociaciones estudio-resultado porque un mismo artículo puede informar más de un resultado.")
        return base_meta(ans, "high")

    # If the user explicitly asks what the human studies *actually show* and
    # abstracts have been backfilled, let the synthesis path read those study texts.
    deep_human = any(k in q for k in ("human studies actually show","what do the human studies show","qué muestran realmente los estudios en humanos","que muestran realmente los estudios en humanos"))
    has_abstracts = any((s.get("abstract") for c in claims for s in (c.get("studies") or [])))
    if deep_human and has_abstracts:
        return None

    # Best / strongest / weakest / human evidence overview
    if any(k in q for k in ("best for","strongest","weakest","human evidence","most evidence","what works","mejor evidencia","más fuerte","evidencia humana")):
        ranked = sorted(claims, key=_claim_sort, reverse=True)
        if not ranked: return None
        lines=[]
        for c in ranked[:4]:
            out=c.get("outcome"); tier=c.get("tier"); nh=_human_n(c); ns=c.get("n_studies") or 0; eff=_effect_sentence(c,es)
            direction=_ws(c).get("direction")
            line=f"{out}: {tier} — {nh} human studies ({ns} graded total)"
            if eff: line += f"; {eff}"
            if direction == "null_result": line += "; overall direction: no clear benefit"
            elif direction == "favors_control": line += "; overall direction: favors control"
            elif direction == "favors_treatment": line += "; overall direction: favors treatment"
            lines.append(line + ".")
        intro = "The strongest human-supported outcomes in Clarity's current profile are:" if not es else "Los resultados con mayor respaldo humano en el perfil actual de Clarity son:"
        caveat = "This ranks confidence in the evidence, not how large the benefit is." if not es else "Esto ordena la confianza en la evidencia, no el tamaño del beneficio."
        return base_meta(intro+"\n"+"\n".join(f"• {x}" for x in lines)+"\n"+caveat, "high")

    # Why not stronger / biggest weakness
    if any(k in q for k in ("why isn't","why is not","why not stronger","biggest weakness","limitation","limitations","uncertain","por qué no","debilidad","limitación")):
        c = matched[0] if matched else (sorted(claims,key=_claim_sort,reverse=True)[0] if claims else None)
        reasons = (c.get("grade_reasons") or []) if c else []
        parts=[]
        if c:
            parts.append((f"For {c.get('outcome')}, the grade is {c.get('tier')}." if not es else f"Para {c.get('outcome')}, el nivel es {c.get('tier')}."))
        parts.extend(str(r) for r in reasons[:4])
        if isinstance(appraisal, dict):
            for k in ("headline","what_could_change_the_grade","missing_evidence"):
                if appraisal.get(k): parts.append(str(appraisal.get(k)))
        if len(parts)>1:
            return base_meta("\n".join(f"• {p}" for p in parts), "high")

    return None


def _study_text(study: dict, outcome: str, effect_by_pmid: dict) -> str:
    pmid = str(study.get("pmid") or "")
    effect = effect_by_pmid.get((pmid, outcome)) or effect_by_pmid.get((pmid, "*"))
    fields = [outcome, pmid, study.get("title"), study.get("design"), study.get("population"), study.get("year"), study.get("n") or study.get("sample_size"), study.get("abstract")]
    if effect: fields.extend([effect.get("metric"), effect.get("value"), effect.get("ci_low"), effect.get("ci_high"), effect.get("direction"), effect.get("quote")])
    return " ".join(str(x) for x in fields if x is not None)


def retrieve(profile: dict, question: str, language="en", max_studies=8) -> dict:
    t0=time.perf_counter()
    qtok=_expand(_tok(question)); qlow=question.lower()
    claims=profile.get("claims") or []
    broad = any(k in qlow for k in ("overall","best","strongest","compare outcomes","all outcomes","human studies actually show","evidence overall","en general","mejor","todos los resultados"))
    claim_limit = min(8,len(claims)) if broad else 3
    selected_claims=_matched_claims(profile,question,claim_limit)

    effect_by_pmid={}
    for c in selected_claims:
        out=str(c.get("outcome") or "")
        for e in ((c.get("effects") or {}).get("plottable") or []):
            p=str(e.get("pmid") or "")
            if p: effect_by_pmid[(p,out)] = e

    rows=[]
    for c in selected_claims:
        out=str(c.get("outcome") or "")
        for s in (c.get("studies") or []):
            text=_study_text(s,out,effect_by_pmid)
            dtok=_expand(_tok(text))
            overlap=qtok.intersection(dtok)
            score=4.0*len(overlap)
            if out.lower() in qlow: score += 14
            pop=str(s.get("population") or "").lower(); design=str(s.get("design") or "").lower()
            if "human" in pop: score += 1.5
            if any(k in design for k in ("meta","systematic","rct")): score += 1.2
            if s.get("abstract"): score += 0.8
            rows.append((score,out,s,effect_by_pmid.get((str(s.get("pmid") or ""),out))))
    rows.sort(key=lambda x:x[0], reverse=True)
    selected_rows=rows[:max_studies]

    expl = profile.get("explanation_es") if language=="es" and profile.get("explanation_es") else profile.get("explanation") or {}
    appraisal = profile.get("appraisal_es") if language=="es" and profile.get("appraisal_es") else profile.get("appraisal") or {}
    include_safety=any(k in qlow for k in ("safe","safety","risk","adverse","interaction","seguridad","riesgo"))
    include_mech=any(k in qlow for k in ("mechanism","how does","works","mecanismo","funciona"))
    include_pk=any(k in qlow for k in ("half-life","pharmacok","absorption","bioavailability","metabolism","tmax","cmax","vida media","farmacocin"))
    include_chem=any(k in qlow for k in ("formula","molecular","chemistry","chemical","xlogp","tpsa","química","quimica"))

    claim_packets=[]
    for c in selected_claims:
        claim_packets.append({
            "outcome":c.get("outcome"),"tier":c.get("tier"),"certainty":c.get("certainty"),"n_studies":c.get("n_studies"),
            "layers":c.get("layers"),"grade_reasons":(c.get("grade_reasons") or [])[:4],"headline_effect":c.get("headline_effect"),
            "weighted_score":c.get("weighted_score"),"summary":c.get("summary"),
            "effects":((c.get("effects") or {}).get("plottable") or [])[:4],
        })
    study_packets=[]; pmids=[]; source_refs=[]
    for score,out,s,e in selected_rows:
        p=str(s.get("pmid") or "")
        if p and p not in pmids: pmids.append(p)
        ref=_source_ref(s)
        if ref and ref not in source_refs: source_refs.append(ref)
        study_packets.append({
            "outcome":out,"source_ref":ref,"pmid":p or None,"doi":s.get("doi"),"epmc_id":s.get("epmc_id"),"url":s.get("url"),
            "title":s.get("title"),"year":s.get("year"),"design":s.get("design"),
            "population":s.get("population"),"n":s.get("n") or s.get("sample_size"),
            "abstract":str(s.get("abstract") or "")[:1800] or None,"effect":e,
        })
    packet={
        "compound":profile.get("name"),"overall_tier":profile.get("tier"),"best_tier":profile.get("best_tier"),
        "best_outcome":profile.get("best_outcome"),"outcome_dependent":profile.get("outcome_dependent"),
        "overall_tier_basis":profile.get("overall_tier_basis"),"study_count":profile.get("study_count"),
        "unique_human_study_count":profile.get("unique_human_study_count"),
        "weighted_score":profile.get("weighted_score"),"claims":claim_packets,"studies":study_packets,
    }
    if include_safety: packet["safety"]={k:expl.get(k) for k in ("safety_line","safety_detail","safety_bullets","caveats") if expl.get(k)}; packet["appraisal"]=appraisal
    if include_mech: packet["mechanism"]={k:expl.get(k) for k in ("what_it_is","how_it_works") if expl.get(k)}
    if include_pk: packet["pharmacokinetics"]=profile.get("pharmacokinetics") or profile.get("pk")
    if include_chem: packet["chemistry"]=profile.get("chemistry")
    return {"packet":packet,"pmids":pmids,"source_refs":source_refs,"outcomes":[c.get("outcome") for c in selected_claims],"retrieved_studies":len(study_packets),"retrieval_ms":round((time.perf_counter()-t0)*1000)}


def _fallback(profile, question, ret, language):
    # Use the instant engine as fallback even when the question wasn't a canonical fast intent.
    out=_instant_answer(profile,question,language)
    if out: return out
    claims=_matched_claims(profile,question,2); es=language=="es"
    if not claims:
        ans="El perfil no contiene suficiente evidencia estructurada para responder esa pregunta." if es else "The profile does not contain enough structured evidence to answer that question."
    else:
        lines=[]
        for c in claims:
            lines.append(f"{c.get('outcome')}: {c.get('tier')}; {_human_n(c)} human studies; {c.get('n_studies',0)} graded studies.")
        ans=("Lo más relevante que contiene el perfil es:\n" if es else "The most relevant evidence in the profile is:\n")+"\n".join("• "+x for x in lines)
    return {"answer":ans,"pmids":ret.get("pmids",[])[:6],"source_refs":ret.get("source_refs",[])[:6],"grounded":True,"coverage":"low","retrieved_studies":ret.get("retrieved_studies",0),"matched_outcomes":ret.get("outcomes",[]),"model_used":False,"mode":"fallback"}


def answer(profile: Dict[str,Any], question: str, history=None, language="en") -> Dict[str,Any]:
    start=time.perf_counter(); key=_cache_key(profile,question,language)
    cached=_cache_get(key)
    if cached: return cached

    fast=_instant_answer(profile,question,language)
    if fast:
        fast["timing"]={"retrieve_ms":0,"llm_ms":0,"total_ms":round((time.perf_counter()-start)*1000)}
        _cache_put(key,fast); return fast

    ret=retrieve(profile,question,language,max_studies=int(os.environ.get("CLARITY_ASK_MAX_STUDIES","8")))
    api_key=os.environ.get("ANTHROPIC_API_KEY","").strip()
    model=(os.environ.get("CLARITY_ASK_MODEL") or os.environ.get("LLM_MODEL") or os.environ.get("ANTHROPIC_MODEL") or "").strip()
    if not api_key or not model:
        out=_fallback(profile,question,ret,language); out["timing"]={"retrieve_ms":ret["retrieval_ms"],"llm_ms":0,"total_ms":round((time.perf_counter()-start)*1000)}; _cache_put(key,out); return out

    hist=[]
    for m in (history or [])[-4:]:
        role="assistant" if m.get("role")=="assistant" else "user"; content=str(m.get("content") or "")[:700]
        if content: hist.append({"role":role,"content":content})
    lang_rule="Answer in Spanish." if language=="es" else "Answer in English."
    system=f"""You are Ask Clarity, an evidence interpreter for ONE compound. {lang_rule}

Your job is to answer the user's actual question directly using only EVIDENCE_PACKET.
Do not give a generic overview unless the user asked for one.

Rules:
- Use ONLY facts in EVIDENCE_PACKET. No outside medical knowledge.
- Start with a direct answer in 1-2 sentences, then explain why.
- Use concrete numbers/designs/results when present. Prefer specificity over boilerplate.
- Distinguish human, animal, and mechanistic evidence.
- Evidence-strength scores are confidence/strength measures, not probability of benefit.
- If a CI includes the no-effect value, explain that plainly.
- If abstracts conflict or evidence is incomplete, say so.
- Never invent dose, safety, interactions, effect sizes, or study findings.
- You may cite only source_ref values present in the packet. Render them as [PMID 123], [DOI 10.x/...], or [EPMC SOURCE:ID]. Use 1-4 useful citations.
- Do not repeat generic disclaimers unless the question actually asks for personalized medical advice.
- If the packet cannot answer a detail, say what evidence is missing.
- Aim for 120-280 words unless the user asks for detail.

Return JSON only:
{{"answer":"...","source_refs":["PMID:123"],"coverage":"high|medium|low","limitation":""}}
"""
    prompt="QUESTION:\n"+question+"\n\nEVIDENCE_PACKET:\n"+json.dumps(ret["packet"],ensure_ascii=False,separators=(",",":"))
    llm0=time.perf_counter()
    try:
        import anthropic
        client=anthropic.Anthropic(api_key=api_key)
        resp=client.messages.create(model=model,max_tokens=int(os.environ.get("CLARITY_ASK_MAX_TOKENS","500")),temperature=0.1,system=system,messages=hist+[{"role":"user","content":prompt}])
        raw="".join(getattr(b,"text","") for b in resp.content).strip()
        raw=re.sub(r"^```(?:json)?\s*|\s*```$","",raw,flags=re.I|re.S).strip()
        data=json.loads(raw); ans=str(data.get("answer") or "").strip()
        if not ans: raise ValueError("empty answer")
        allowed_refs=set(ret.get("source_refs") or [])
        requested_refs=[str(x).strip() for x in (data.get("source_refs") or [])]
        cited_refs=[x for x in requested_refs if x in allowed_refs][:6]
        cited_pmids=[x.split(":",1)[1] for x in cited_refs if x.startswith("PMID:")]
        out={"answer":ans,"pmids":cited_pmids,"source_refs":cited_refs,"grounded":True,"coverage":data.get("coverage") if data.get("coverage") in {"high","medium","low"} else "medium",
             "limitation":str(data.get("limitation") or "")[:240],"retrieved_studies":ret["retrieved_studies"],"matched_outcomes":ret["outcomes"],"model_used":True,"mode":"synthesis"}
    except Exception as e:
        out=_fallback(profile,question,ret,language); out["fallback_reason"]=type(e).__name__
    llm_ms=round((time.perf_counter()-llm0)*1000); total=round((time.perf_counter()-start)*1000)
    out["timing"]={"retrieve_ms":ret["retrieval_ms"],"llm_ms":llm_ms,"total_ms":total}
    _cache_put(key,out); return out
