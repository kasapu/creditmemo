# Credit Memo GenAI

End-to-end GenAI credit-memo generation platform for financial analysts.
Given a stock ticker it pulls live SEC EDGAR financials, parses the actual
10-K / 10-Q filings, computes KPIs from a declarative model, runs parallel LLM
analysis agents (financial / risk / qualitative), pauses for human-in-the-loop
(HITL) approval, and composes a final structured credit memo — streamed live to
the browser over SSE.

This implementation is **runnable out of the box in offline / mock mode** (no
cloud keys required) and lights up real Azure services as you add credentials.

---

## Requirements

- **Python 3.11+** (3.11, 3.12 or 3.13). Ubuntu 20.04/22.04 ship an older
  Python (3.8/3.10) — install a newer one first:

  ```bash
  sudo add-apt-repository ppa:deadsnakes/ppa -y
  sudo apt update && sudo apt install -y python3.11 python3.11-venv
  ```

  Then point the launcher at it: `PYTHON=python3.11 ./run.sh`.
  (`run.sh` also auto-detects `python3.11/3.12/3.13` if present.)

## Quick start (offline / mock mode)

```bash
./run.sh                        # creates venv, installs deps, starts server
```

…or do it manually:

```bash
python3.11 -m venv .venv        # must be Python 3.11+
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env            # optional; defaults work offline

python run.py                   # serves http://127.0.0.1:8001
```

Open <http://127.0.0.1:8001>, enter a ticker (e.g. `AAPL`), and click
**Generate Credit Memo**. Approve at the HITL gate to compose the final memo.

> **Network note:** the SEC EDGAR API (`data.sec.gov`, `www.sec.gov`) must be
> reachable. If your environment blocks it, seed a sample fixture instead:
>
> ```bash
> PYTHONPATH=. python scripts/seed_sample.py   # caches a sample AAPL dataset
> ```
>
> The pipeline reads the local cache first, so seeded data runs fully offline.

---

## How "mock mode" works

`mock_mode` is on automatically whenever Azure OpenAI is not configured.

| Capability        | Real (keys present)                 | Offline fallback                                  |
|-------------------|-------------------------------------|---------------------------------------------------|
| Financials        | SEC EDGAR XBRL (always real)        | SEC EDGAR XBRL (always real) / seeded fixture     |
| LLM agents        | Azure OpenAI (`AzureChatOpenAI`)    | Deterministic templated output grounded in KPIs   |
| Doc Intelligence  | Playwright → PDF → Azure DI         | BeautifulSoup plain-text extraction               |
| Vector retrieval  | Azure AI Search (hybrid)            | Local lexical scorer over cached chunks           |
| KPI base metrics  | Azure SQL `sec_financial_facts`     | Computed directly from SEC EDGAR XBRL facts       |

Check the active mode any time: `GET /health`.

---

## Going live with Azure

```bash
pip install -r requirements-azure.txt
python -m playwright install chromium     # for SEC inline-XBRL rendering
```

Fill the relevant variables in `.env` (see `.env.example`). Each integration
activates independently as soon as its keys are present — you can enable just
Azure OpenAI, or the full stack.

---

## Architecture

```
credit_memo/
├── config.py              # pydantic settings + capability flags + mock detection
├── app.py                 # FastAPI app factory (+ serves the web UI)
├── core/
│   ├── state.py           # CreditMemoState (LangGraph TypedDict)
│   └── post_processing.py # state -> API response, credit-rating extraction
├── infra/
│   ├── sec_fetcher.py     # SEC EDGAR REST client (urllib, XBRL waterfalls)
│   ├── doc_intelligence.py# Azure DI + Playwright (offline: text extraction)
│   ├── ai_search.py       # Azure AI Search HNSW index (offline: no-op)
│   ├── chunker.py         # DI result -> chunk records
│   ├── storage.py         # filesystem cache (data/<TICKER>/)
│   └── llm.py             # Azure OpenAI client + deterministic mock + embeddings
├── pipeline/
│   ├── kpi_service.py     # KPI engine (SQL or SEC source, sandboxed eval)
│   ├── kpi_context.py     # KPI table + company-profile snapshot for prompts
│   ├── retrieval.py       # AI Search -> local lexical fallback + query sets
│   ├── agents.py          # graph nodes + 4 LLM agents + UI normalization
│   ├── graph.py           # 4 compiled LangGraph StateGraphs
│   ├── pipeline_service.py# orchestrator with progress tracking + HITL gate
│   └── task_service.py    # in-memory task store + asyncio approval gates
├── prompts/agent_prompts.py
└── api/routes.py          # task lifecycle, SSE stream, approve, KPIs
config/kpi.yaml            # declarative KPI semantic model
static/index.html          # single-file web UI (no build step)
scripts/seed_sample.py     # offline sample fixture
```

### Pipeline flow

```
SEC EDGAR (5–15%) → Document Intelligence (20–48%) → KPI + indexing (50–55%)
   → analysis agents [financial ∥ risk ∥ qualitative] (60–80%)
   → HITL approval gate (80%)  → memo composition (90%)  → done (100%)
```

The analysis runs as a LangGraph fan-out/fan-in; the memo composer runs as a
second graph after approval (`SKIP_HITL=true` bypasses the gate).

---

## API

| Method | Path                                            | Description                     |
|--------|-------------------------------------------------|---------------------------------|
| GET    | `/health`                                       | status + active capabilities    |
| POST   | `/analysis/{ticker}/report/task`                | start a pipeline task            |
| GET    | `/analysis/report/task/{id}`                    | poll task status (JSON)          |
| GET    | `/analysis/report/task/{id}/stream`             | SSE live progress                |
| POST   | `/analysis/report/task/{id}/approve`            | release the HITL gate            |
| GET    | `/analysis/cached-companies`                    | list locally cached tickers      |
| GET    | `/analysis/{ticker}/kpis`                       | KPI table for a ticker           |

Approve responses: `200` approved, `404` task expired, `409` not pending.

---

## KPI model (`config/kpi.yaml`)

Declarative `metrics` bind logical names to XBRL concept waterfalls (first match
wins, optional `default`). `kpis` define formulas evaluated in a sandboxed
namespace (`__builtins__` cleared, only `abs` exposed). Missing `requires`
inputs or division-by-zero yield a Note instead of crashing. Edit the YAML to
add or change KPIs — no code change needed.
