# Clarity public-launch checklist

This package intentionally keeps the disclosed peptide affiliate links.
Commercial links remain separate from grading logic and do not change tiers.

## 1. Configure production environment

Frontend:

```bash
VITE_API_BASE_URL=https://clarity-engine-api.onrender.com
```

Backend required values:

```bash
CLARITY_ENGINE_VERSION=2026.09-launch.2
CLARITY_ALLOW_LIVE_GENERATION=0
CLARITY_ALLOWED_ORIGINS=https://YOUR-FRONTEND-DOMAIN.com
CLARITY_CONTACT_EMAIL=you@YOUR-DOMAIN.com
CLARITY_STORE_ASK_TEXT=0
ANTHROPIC_API_KEY=...
```


For the first public release, `CLARITY_ALLOW_LIVE_GENERATION=0` is intentional.
It means visitors can only open profiles that were generated in your release pass
and checked by `launch_audit.py`. Unknown searches do not publish an unaudited
profile on demand. You can enable live generation later once you have automated
post-generation auditing and are comfortable with that workflow.

The included `render.yaml` uses paid production-sized Render plan identifiers.
Review the cost in Render before creating/updating the Blueprint. It deliberately
uses one Gunicorn process with threads so the existing in-memory generation and
rate counters do not diverge between worker processes.

## 2. Make browser routes refresh-safe

`Clarity.jsx` now uses real browser paths such as:

- `/`
- `/research`
- `/compound/bpc-157`
- `/learn/basics`
- `/learn/evidence`
- `/methodology`
- `/privacy`
- `/terms`

Your static frontend host MUST rewrite unknown application paths to `index.html`.
Without that SPA fallback, a direct refresh of `/compound/...` will 404 even
though navigation inside the app works.

## 3. Freshly regenerate every compound

The engine/schema is versioned. Old cached profiles are intentionally treated as
stale and should not be mixed with launch profiles.

If the database is currently the source of truth, pull it first:

```bash
python3 db.py --pull
```

Test a few profiles:

```bash
python3 regrade_all.py --limit 5
```

Then refresh the complete catalog:

```bash
python3 regrade_all.py
```

Important changes in this release include unique compound-level study counts,
preprint exclusion from published grades, conservative handling when direction
cannot be verified, canonical vitamin indications, and engine provenance.

## 4. Refresh derived prose

After evidence changes, regenerate all text derived from the profile:

```bash
python3 add_explanations.py --force
python3 add_appraisals.py --force
python3 add_translations.py --force
python3 add_ask_context.py
```

Then sync local profiles to production Postgres if that is your workflow:

```bash
python3 db.py --sync
```

## 5. Run the release gate

```bash
python3 launch_audit.py
```

Do not publish while it reports any `ERROR` items. Warnings should be manually
reviewed, especially missing prose/appraisal/Spanish content.

The audit checks, among other things:

- every profile uses the current engine/schema;
- headline study counts are unique papers, not outcome-membership sums;
- human/animal unique counts recompute correctly;
- preprints do not sit inside the published graded evidence set;
- Strong outcomes completed direction verification;
- claims have inspectable source identifiers;
- provenance and generation timestamps exist;
- placeholder LLM text cannot ship.

## 6. Scientific gold-set QA

Before announcing the site, manually inspect representative positive, negative,
mixed and preclinical evidence. Suggested cases include creatine/strength,
semaglutide/weight loss, BPC-157/tissue healing, KPV, B12/deficiency,
folate/neural-tube prevention, biotin/hair in non-deficient adults, vitamin E,
ginkgo and chromium.

For each case check retrieval relevance, deduplication, human/animal population,
design classification, outcome assignment, direction, effect/CI, tier, citations,
summary and Ask Clarity answers.

## 7. Frontend production build

From the actual frontend project (where `package.json` and the lockfile live):

```bash
npm ci
npm run build
```

Then serve/test the production `dist/` build, not only Vite dev mode. Test:

- desktop and mobile;
- direct-link refresh of compound/learn/legal pages;
- browser Back/Forward;
- English/Spanish;
- keyboard-only navigation and visible focus;
- reduced-motion preference;
- Ask Clarity error/slow paths;
- affiliate disclosure and links.

## 8. Backups and monitoring

Before launch, take a database backup/snapshot and confirm you can restore it.
Monitor API 4xx/5xx rates, response latency, generation use, Ask Clarity failures,
and external source failures. Scientific grades should never silently mutate from
user questions; user feedback is quality telemetry only.
