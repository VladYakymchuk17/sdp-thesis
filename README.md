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
- `services/backend/` — NestJS orchestrator (planned)
- `services/frontend/` — React dashboard (planned)

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
