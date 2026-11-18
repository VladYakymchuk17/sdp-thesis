# SDP for TypeScript

Master's thesis project — predicting defect-prone files in TypeScript repositories using git history metrics, static code analysis (TS Compiler API), and ML classifiers.

## How it works

```
Git repo → PyDriller mining → Static analysis (TS AST) → SZZ bug labeling
                                                                  ↓
                                                       Dataset assembly
                                                                  ↓
                                                    ML training (RF, XGBoost, LightGBM, ...)
                                                                  ↓
                                                    SHAP + LLM explanations
                                                                  ↓
                                                    FastAPI prediction API
```

## Structure

- `services/ml-service/` — Python ML pipeline (mining, training, API)
- `services/ts-analyzer/` — TypeScript static metrics CLI
- `services/backend/` — NestJS BFF (proxies FastAPI, optional)
- `services/frontend/` — React + Tailwind dashboard (dark UI, risk colors, SHAP + LLM panel)

## Setup

Prerequisites: Docker, Python 3.11+, Node.js 18+

```bash
# start postgres
docker compose up -d postgres

# python env
cd services/ml-service
python -m venv .venv
.\.venv\Scripts\Activate.ps1   # windows
pip install -r requirements.txt

# build ts-analyzer
cd ../ts-analyzer
npm install && npm run build
```

## Running the pipeline

```bash
cd services/ml-service

# 1. mine a repo
python run_mining.py https://github.com/nestjs/nest --branch master

# 2. static analysis
python run_static_analysis.py

# 3. SZZ labeling
python run_szz.py

# 4. assemble dataset
python run_dataset_assembly.py

# 5. train models
python run_training.py
python run_advanced_training.py --skip-shap
```

## Tech stack

| Component | Technology |
|---|---|
| Git Mining | PyDriller |
| Static Metrics | TypeScript Compiler API |
| ML | scikit-learn, XGBoost, LightGBM |
| Bug Labeling | SZZ algorithm |
| Database | PostgreSQL |
| API | FastAPI |
| Orchestrator | FastAPI (+ optional Express BFF on :3001) |
| Frontend | React + Vite + Tailwind |

## Web dashboard

Postgres and trained models must already exist.

```bash
# 1. ML API (ensemble + SHAP + LLM)
cd services/ml-service
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

# 2. React UI
cd services/frontend
npm install
npm run dev
```

Open http://localhost:5173 and sign in (default `admin` / `sdp2026`, see
`SDP_ADMIN_USERNAME` / `SDP_ADMIN_PASSWORD`).

> Do not add `--reload` when you intend to run full-cycle analyses. Analysis jobs
> run in background threads, and an autoreload kills them mid-run. Such jobs are
> marked failed on the next startup rather than being left as "running".

### Analyzing a new repository

The **Analyze repo** page runs the whole pipeline against any public repository:
clone, mine commit history, TypeScript static analysis, SZZ labelling, then
ensemble scoring. Progress is polled per stage and the run can be cancelled
between stages.

History depth defaults to the last two years, which keeps a first run to a few
minutes; choose "Full history" for a complete mine. Clones and already-mined
commits are cached, so re-running a repository skips ahead.

Equivalent CLI path, if you prefer running the stages by hand:

```bash
cd services/ml-service
python run_mining.py <repo-url> --branch main
python run_static_analysis.py --repo-id <id>
python run_szz.py --repo-id <id>
```

Optional API proxy on :3001:

```bash
cd services/backend
npm install
node src/main.js
```

### How to test ML / LLM in the UI

1. Overview page — cards load from `/api/v1/dashboard-summary`. If ML is down you will see an error.
2. Open **class-validator** (smallest repo, id=1). Click **Score files (ensemble)**. Wait until predictions appear with red/yellow/green badges. That is the 5-model majority vote.
3. Click a high-risk file. The side panel runs `/api/v1/analyze/{id}/file` and shows:
   - **Assessment** — what the score means for this file, in prose
   - **What to do about it** — ordered remediation steps derived from the metrics
     that are actually elevated
   - **Driving the risk / Working in its favour** — each contributing metric with
     its measured value, how it compares to the repository average, the mechanism
     by which it leads to defects, and how to reduce it (click to expand)
   - **Ensemble votes** — per-model probability and label
4. To test real LLM text: install Ollama, `ollama pull llama3.2`, keep it running, click another file. The badge next to "Assessment" reads `LLM` or `rule-based` so you always know which produced the text.

Note that a metric can push the prediction toward "buggy" while its own value is
normal — that is how tree models work. The panel labels each metric's level and
withholds remediation advice for values that are not actually elevated, so it
will say the risk comes from the combination rather than inventing a refactor.

Swagger for the same APIs: http://localhost:8000/docs
