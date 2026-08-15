# Data Source Investigation (Phase 3 Scope)

**Status:** scoping only — no multi-source ingestion implemented yet.

## Objective

Assess data availability and ingestion feasibility for expanding Turgot beyond Service-Public, with **one isolated pipeline per source** (own download script, delta logic, Chroma collection, retrieval branch).

Candidate sources:

- Legifrance
- impots.gouv.fr (incl. BOFiP)
- ANTS
- CAF / mesdroitssociaux.gouv.fr
- URSSAF

---

## Critical baseline finding

**Most procedural Q&A for CAF, ANTS, URSSAF, and impots is already in Service-Public.**

Service-Public is published by the DILA as structured XML dumps on [data.gouv.fr](https://www.data.gouv.fr/) — the same corpus Turgot already ingests via `database/download.py` + `database/smart_parser.py` (collection `service_public`).

Evidence from our eval set (`backend/evals/retrieval_eval_set.jsonl`):

| Topic | Example question | Expected doc IDs (Service-Public) |
|-------|------------------|-----------------------------------|
| CAF | Déclarer mes ressources à la CAF | `F14199`, `R1361` |
| URSSAF | Créer mon espace auto-entrepreneur | `R14267`, `F36832` |
| ANTS / titres | Renouveler passeport, CNI, permis | `F556`, `F1341`, `F1255` |
| Impôts (procédures) | Déclarer impôts en ligne | `F358`, `F1265` |

Adding CAF/ANTS/URSSAF as **separate scraped websites** would mostly duplicate existing vectors, increase maintenance, and create citation conflicts — unless the goal is **source-branded UI** rather than new content.

**Distinct gaps** where a new source branch adds real value:

1. **Legifrance** — consolidated law text (articles de code, décrets), not procedural fiches
2. **BOFiP** — official tax doctrine (commentaires administratifs), authoritative for fiscal interpretation
3. Everything else — marginal incremental content vs. high ingestion cost

---

## Source-by-source assessment

### 1. Legifrance

| Dimension | Assessment |
|-----------|------------|
| **Value** | High — answers "que dit la loi ?" vs. Service-Public's "comment faire ?" |
| **Access modes** | (A) Daily LEGI tar.gz deltas on [echanges.dila.gouv.fr/OPENDATA/LEGI](https://echanges.dila.gouv.fr/OPENDATA/LEGI/) — Licence Ouverte 2.0; (B) Full global dump `Freemium_legi_global_*.tar.gz` ~1.1 GB compressed / ~15 GB extracted / 1M+ XML files; (C) [PISTE API](https://www.data.gouv.fr/dataservices/legifrance) — free registration, quotas; (D) [@socialgouv/legi-data](https://github.com/SocialGouv/legi-data) — pre-fetched JSON per code via API |
| **Update cadence** | Daily deltas (typically 0.9–12 MB; occasional spikes to ~23 MB) |
| **Delta strategy** | Track last processed `LEGI_YYYYMMDD-HHMMSS.tar.gz`; apply daily delta only; use `content_hash` per article CID + `ETAT` (filter `VIGUEUR`) |
| **Stable IDs** | `LEGITEXT*`, article CID, NOR — well-defined in DILA DTD |
| **Licence** | Licence Ouverte 2.0 ([legifrance open data page](https://www.legifrance.gouv.fr/contenu/pied-de-page/open-data-et-api)) |
| **Risks** | Volume (367k+ in-force articles if full corpus); XML complexity; versioning/abrogation; old parsers (legilibre) broken on 2025 dumps; embedding cost for initial load |
| **Ease score** | **Medium** (scoped pilot) / **Hard** (full corpus) |

**Why a prior attempt likely failed:** ingesting the full global dump or using abandoned tooling. Recommended pilot: **3–5 high-demand codes** (Code civil, Code du travail, Code de la sécurité sociale) via `@socialgouv/legi-data` JSON **or** daily deltas only — not the 1.1 GB global archive.

**Recommended collection:** `legifrance` — separate Chroma + `sources/legifrance/tracking.sqlite3`.

---

### 2. impots.gouv.fr / BOFiP

Two very different things hide behind "impots":

#### 2a. Citizen procedural pages (impots.gouv.fr)

| Dimension | Assessment |
|-----------|------------|
| **Value** | Low incremental — largely mirrored in Service-Public fiches |
| **Access** | HTML only; DGFiP open data is cadastre, fiscal statistics, communicable notes — not citizen how-to guides ([DGFiP open data](https://www.impots.gouv.fr/ouverture-des-donnees-publiques-de-la-dgfip)) |
| **APIs** | Restricted partner APIs (Impôt particulier, SFiP) via DataPass — not suitable for public RAG |
| **Ease score** | **Not recommended** as a separate source |

#### 2b. BOFiP — Bulletin officiel des finances publiques (tax doctrine)

| Dimension | Assessment |
|-----------|------------|
| **Value** | **High** for tax interpretation questions beyond procedural fiches |
| **Access** | Structured tar.gz archives with XML metadata + HTML/PDF content ([BOFiP publications en vigueur](https://www.data.gouv.fr/datasets/bofip-impots-publications-en-vigueur), [technical documentation](https://data.economie.gouv.fr/api/v2/catalog/datasets/bofip-impots/attachments/bofip_documentation_pdf)) |
| **Update cadence** | Weekly flux (`bofip_flux_live_AAAAMMJJ_*`) + monthly stock (`bofip_stock_live_AAAAMMJJ`); MD5 checksum files |
| **Delta strategy** | Same pattern as Service-Public: hash per `document.xml` + `contenu_id` (e.g. `BOI-IF-CFE-10-30-50-60`); apply weekly flux, full stock refresh monthly |
| **Stable IDs** | `bofip:contenu_id`, canonical URL `bofip.impots.gouv.fr` |
| **Licence** | Licence Ouverte 2.0 |
| **Risks** | Mixed content types (HTML, PDF, Office); hierarchical document tree; audience segmentation (particulier / pro) |
| **Ease score** | **Easiest new source to add** — closest to existing `smart_parser.py` pattern |

**Recommended collection:** `bofip` (brand as "impots" / BOFiP in UI source cards).

---

### 3. URSSAF

| Dimension | Assessment |
|-----------|------------|
| **Value** | Medium for employer/auto-entrepreneur — but procedural content largely in Service-Public already |
| **Open data** | [open.urssaf.fr](https://open.urssaf.fr/) — 124 datasets, mostly **statistics** (effectifs, embauches, auto-entrepreneurs par département) via [Explore API v2](https://www.data.gouv.fr/dataservices/api-donnees-ouvertes-de-lurssaf) — **not** procedural guides |
| **Guides** | ~35 PDF/HTML guides on [urssaf.fr](https://www.urssaf.fr/accueil/outils-documentation/guides.html) — no bulk XML dump |
| **Alternative** | [mon-entreprise.urssaf.fr](https://github.com/betagouv/mon-entreprise) uses **Publicodes rules** (`modele-social`) for calculations — computation engine, not narrative RAG corpus |
| **Update cadence** | Guides: ad hoc; statistics: varies |
| **Delta strategy** | Would require crawl + PDF extraction if pursued |
| **Risks** | Scraping ToS; PDF parsing quality; overlap with Service-Public; audience-specific contradictory guidance |
| **Ease score** | **Hard** (scraping) / **Low ROI** vs. Service-Public |

**Recommendation:** Do **not** add as separate ingestion source initially. If URSSAF-branded answers matter, split Service-Public retrieval by `organisme` metadata (many fiches already cite Urssaf) — zero new ingestion.

---

### 4. CAF / mesdroitssociaux.gouv.fr

| Dimension | Assessment |
|-----------|------------|
| **Value** | High user demand, but wrong tool for personalized entitlement |
| **CAF open data** | [data.caf.fr](https://data.caf.fr/) — beneficiary **statistics** by prestation/région, not eligibility guides |
| **mesdroitssociaux** | FranceConnect portal; **closed source**, no export API ([beta.gouv.fr Mes Aides page](https://beta.gouv.fr/startups/mes-aides.html)) |
| **Simulation logic** | [OpenFisca](https://www.data.gouv.fr/dataservices/openfisca) — rule engine used by mesdroitssociaux; computes amounts, not prose |
| **Procedural content** | CAF démarches already in Service-Public (`F14199`, `F12006` APL, etc.) |
| **Risks** | Hallucination on personalized amounts; legal liability; no static corpus for "ai-je droit à X avec mon QF ?" |
| **Ease score** | **Not suitable for RAG ingestion** |

**Recommendation:** Keep CAF answers from Service-Public branch; add **disclaimer + link to mesdroitssociaux.gouv.fr** for simulation. Future: optional OpenFisca tool call (Phase 3b), not vector ingestion.

---

### 5. ANTS (France Titres)

| Dimension | Assessment |
|-----------|------------|
| **Value** | Medium — procedural guidance for CNI, passeport, permis, carte grise |
| **Open data** | **None** for procedural content; operational SIV databases are restricted ([data.gouv.fr support FAQ](https://www.data.gouv.fr/support)) |
| **Procedural content** | Already in Service-Public (eval: `F556` passeport, `F1341` CNI, `F1050` immatriculation) |
| **Account workflows** | ants.gouv.fr user-specific status — **not** suitable for static RAG |
| **Update cadence** | N/A without scraping |
| **Ease score** | **Hard** / **Low ROI** |

**Recommendation:** Do not ingest ANTS separately. Route ANTS-intent queries to Service-Public branch with `organisme=ANTS` filter if source branding needed.

---

## Ease ranking (new distinct value)

| Rank | Source | Why | Pilot effort |
|------|--------|-----|--------------|
| **1** | **BOFiP** | Structured tar.gz + XML metadata + weekly flux; mirrors existing pipeline; real content gap for tax doctrine | ~1–2 weeks |
| **2** | **Legifrance (scoped)** | High product value ("lois"); daily deltas manageable; avoid full 1.1 GB dump | ~2–4 weeks |
| **3** | **Service-Public splits** | No new data — refactor existing index by `organisme`/`theme` for parallel retrieval + source cards | ~1 week (architecture only) |
| **4** | URSSAF guides (scrape) | PDF crawl, no stable dump, overlaps SP | ~3+ weeks, fragile |
| **5** | impots.gouv.fr pages (scrape) | HTML only, overlaps SP + BOFiP | Not recommended |
| **6** | CAF / mesdroitssociaux | No prose corpus; needs OpenFisca tool, not vectors | Different paradigm |
| **7** | ANTS (scrape) | No dump, overlaps SP | Not recommended |

---

## Recommended per-source architecture

Each source is a self-contained module — **not** vectors mixed into `service_public`.

```
sources/
  service_public/          # existing — move from database/
    download.py
    parser.py
    chroma_db/
    tracking.sqlite3
    config.yaml
  bofip/
    download.py            # fetch stock + weekly flux from data.economie.gouv.fr
    parser.py              # extract HTML from tar, parse document.xml metadata
    chroma_db/
    tracking.sqlite3
    config.yaml
  legifrance/
    download.py            # fetch daily LEGI_*.tar.gz
    parser.py              # DILA XML → articles en vigueur
    chroma_db/
    tracking.sqlite3
    config.yaml

config/sources.yaml        # registry: enabled, cron, delta_mode, collection_name
```

### Per-source config (`config.yaml` example)

```yaml
source_id: bofip
display_name: "BOFiP — Doctrine fiscale"
collection_name: bofip
canonical_domain: bofip.impots.gouv.fr
licence: LO-2.0
update:
  cron: "0 4 * * 1"          # weekly Monday 4am
  mode: flux_then_stock      # weekly delta; monthly full stock
  delta_url_pattern: "bofip_flux_live_{date}"
  stock_url_pattern: "bofip_stock_live_{date}"
delta:
  strategy: content_hash     # SHA-256 per document.xml + data.html
  id_field: contenu_id
retrieval:
  enabled: true
  default_k: 8
  audience_metadata: true    # particulier / professionnel
```

### Query orchestration (LangGraph)

```
                    ┌─────────────┐
                    │   Router    │  intent → which sources to query
                    └──────┬──────┘
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
   ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
   │ service_pub  │ │    bofip     │ │  legifrance  │   parallel retrieval
   │  retrieve +  │ │  retrieve +  │ │  retrieve +  │
   │   rerank     │ │   rerank     │ │   rerank     │
   └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
          └────────────────┼────────────────┘
                           ▼
                  ┌────────────────┐
                  │ Normalizer +   │  unified schema, cross-source dedup
                  │ Dedup          │  (drop SP chunk if BOFiP supersedes on tax)
                  └────────┬───────┘
                           ▼
                  ┌────────────────┐
                  │  Synthesis     │  ranked evidence, conflict flags
                  └────────┬───────┘
                           ▼
                  ┌────────────────┐
                  │  Generation    │  per-claim attribution
                  └────────────────┘
```

### Normalized chunk schema

Every chunk, regardless of source:

```json
{
  "source_id": "bofip",
  "document_id": "BOI-IF-CFE-10-30-50-60",
  "canonical_url": "https://bofip.impots.gouv.fr/bofip/...",
  "title": "...",
  "snippet": "...",
  "audience": "professionnel",
  "effective_date": "2025-07-04",
  "updated_at": "2026-06-11",
  "confidence": 0.87
}
```

### Operational safeguards

- Per-source kill switch in `config/sources.yaml`
- Per-source freshness metric (last successful update timestamp)
- Per-source eval subset in `backend/evals/`
- Circuit breaker: if source stale > N days, router skips it
- Licence checklist before enabling ingestion

---

## Suggested rollout

### Phase 3a — Architecture + first real source (BOFiP)

1. Refactor existing Service-Public into `sources/service_public/` (no data change)
2. Implement multi-collection retrieval interface in `retrieval.py`
3. Add LangGraph router + parallel fan-out (Service-Public + BOFiP)
4. BOFiP pilot: ingest publications en vigueur, weekly flux updates
5. Extend eval set with 10–15 tax-doctrine questions (distinct from procedural fiches)

### Phase 3b — Legifrance scoped pilot

1. Start with **CRPA only** (`LEGITEXT000031366350`) via `@socialgouv/legi-data` or daily LEGI deltas
2. Filter `ETAT=VIGUEUR` only; store article CID + legifrance URL
3. Add `legifrance_enabled` toggle + collapsible "Fondement légal" in UI
4. Eval set: ~10 "que dit la loi / recours administratif" questions

### Phase 3c — Source branding without new ingestion

1. Tag Service-Public chunks with `organisme` metadata (CAF, ANTS, Urssaf, DGFiP)
2. Router can prefer `organisme=CAF` branch for CAF questions — same DB, filtered retrieval
3. UI shows "Source : CAF (via Service-Public)" with link to caf.fr

### Explicitly defer

- Scraping urssaf.fr / ants.gouv.fr / impots.gouv.fr HTML
- CAF/mesdroitssociaux vector ingestion (use OpenFisca tool later if needed)
- Full Legifrance corpus (367k articles) until scoped pilot validates pipeline

---

## Product decisions (locked in)

| # | Decision |
|---|----------|
| 1 | **Primarily Service-Public** — procedural "comment faire" is the default; law/doctrine is supplementary when needed |
| 2 | **Dual attribution** — show both organisme URL (`caf.fr`, `urssaf.fr`, …) *and* Service-Public when content comes from DILA fiches |
| 3 | **Legifrance scope: start minimal** — one small, admin-relevant code first (see size table below), expand only after pilot |
| 4 | **Embed cost** — estimate on the fly during ingestion (`articles × tokens × price` logged before full embed) |

---

## Legifrance size when scoped

Yes — stripped Legifrance is **much** smaller than the full corpus.

| Scope | Articles (order of magnitude) | vs full LEGI (~367k) | Initial embed (rough) |
|-------|------------------------------|----------------------|------------------------|
| Full corpus (`VIGUEUR` only) | ~367 000 | 100% | €15–40 one-time |
| 4 codes in [@socialgouv/legi-data](https://github.com/SocialGouv/legi-data) (travail, sécu sociale, rural, CRPA) | ~25 000–50 000 | ~7–14% | €1–5 one-time |
| **Pilot: CRPA only** (`LEGITEXT000031366350` — relations public/administration) | ~1 500–3 000 | **<1%** | **<€0.50** one-time |
| Pilot + Code de la sécurité sociale | ~8 000–12 000 | ~3% | ~€0.50–1.50 |

Assumptions: ~400 tokens/article average, 1–1.5 chunks/article after splitting, Mistral Embed ≈ €0.10 / 1M tokens. Daily LEGI deltas touch dozens–hundreds of articles → **cents per week** for updates.

**Pilot recommendation:** ingest **CRPA only** first — smallest relevant code, aligns with Service-Public's domain (démarches, recours, délais, obligations des administrations). Add Code de la sécurité sociale in phase 2 if retrieval quality warrants it. Skip Code civil / full travail until user demand is proven.

Filters applied regardless of scope:

- `ETAT = VIGUEUR` only (drop abrogated)
- Skip empty / placeholder articles
- Store `article_id`, `cid`, code title, section breadcrumb for readable citations

---

## Legifrance UX — optional, not overwhelming

Law support must feel **opt-in** and **layered**, not the default answer mode.

### Default behaviour (Legifrance off)

- Router queries **Service-Public only** (and BOFiP when tax-doctrine intent detected).
- Answers read like today: practical steps, démarches, délais.
- Source cards show organisme + Service-Public link where applicable.

### User controls

1. **Session toggle** (chat input area): `Inclure les textes de loi` — off by default, persists for session via existing Redis session.
2. **Settings** (optional later): default on/off stored in `localStorage` for returning users.
3. **Per-message chip** when router detects legal intent but toggle is off: *« Cette question touche au droit — chercher dans Légifrance ? »* → one-click enable + re-run retrieval.

### Answer structure (Legifrance on)

Do **not** lead with raw article text. Use a two-layer response:

```
┌─────────────────────────────────────────┐
│ Réponse pratique (Service-Public)       │  ← always first, plain language
│ • étapes, délais, où aller              │
├─────────────────────────────────────────┤
│ ▼ Fondement légal (replié par défaut)   │  ← collapsible accordion
│   Art. L.114-2 CRPA — [lien Légifrance] │
│   extrait court (2–3 phrases max)       │
└─────────────────────────────────────────┘
```

### Source card differentiation

| Source | Card style | Link target |
|--------|------------|-------------|
| Service-Public | Blue, "Démarche" | `service-public.fr` + organisme if tagged |
| BOFiP | Amber, "Doctrine fiscale" | `bofip.impots.gouv.fr` |
| Légifrance | Slate + § icon, "Texte de loi" | `legifrance.gouv.fr` article URL |

### Router rules (backend)

- `legifrance_enabled=false` → never query `legifrance` collection, even if legal intent score is high (show chip instead).
- `legifrance_enabled=true` → parallel retrieve SP + Legifrance; synthesis **prioritises SP prose**; Legifrance chunks capped at **2–3** in final context (vs 8–10 for SP).
- Generator system prompt: *"Explain in plain French first; cite law only in the legal foundation section, never paste full articles."*

### API sketch

```json
POST /chat { "message": "...", "legifrance_enabled": false }
POST /chat-stream { ..., "legifrance_enabled": true }
```

---

## Revised rollout (reflecting decisions)

### Phase 3a — Architecture + BOFiP

Unchanged: multi-collection retrieval, parallel fan-out, BOFiP pilot.

### Phase 3b — Legifrance minimal + UX

1. Ingest **CRPA only** via `legi-data` JSON or daily LEGI delta
2. Add `legifrance_enabled` to chat API + session toggle in UI
3. Collapsible "Fondement légal" block in assistant messages
4. Cost estimator in `sources/legifrance/parser.py` — log token count before embed, abort if over threshold
5. Eval: ~10 questions where law citation adds value (délais de recours, obligations administration, etc.)

### Phase 3c — Organisme branding on Service-Public

Dual links: `caf.fr` + `service-public.fr/fr/x/F14199` on source cards.

---

## References

- [Service-Public open data (DILA)](https://www.service-public.fr/P10004)
- [LEGI dumps (DILA)](https://echanges.dila.gouv.fr/OPENDATA/LEGI/)
- [Legifrance API (PISTE)](https://www.data.gouv.fr/dataservices/legifrance)
- [SocialGouv legi-data](https://github.com/SocialGouv/legi-data)
- [BOFiP publications en vigueur](https://www.data.gouv.fr/datasets/bofip-impots-publications-en-vigueur)
- [BOFiP technical documentation (XML structure)](https://data.economie.gouv.fr/api/v2/catalog/datasets/bofip-impots/attachments/bofip_documentation_pdf)
- [URSSAF open data API](https://www.data.gouv.fr/dataservices/api-donnees-ouvertes-de-lurssaf)
- [CAF data portal](https://data.caf.fr/)
- [OpenFisca API](https://www.data.gouv.fr/dataservices/openfisca)
- [Mes Aides / mesdroitssociaux context](https://beta.gouv.fr/startups/mes-aides.html)
- [SocialGouv fiches-vdd](https://github.com/SocialGouv/fiches-vdd) (Service-Public JSON mirror)
