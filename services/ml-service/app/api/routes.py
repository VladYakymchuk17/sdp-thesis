from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class MineRequest(BaseModel):
    repo_url: str
    branch: str = "main"


class PredictRequest(BaseModel):
    repo_url: str
    file_path: str


class PredictResponse(BaseModel):
    file_path: str
    risk_score: float
    risk_level: str  # "high", "medium", "low"
    top_features: dict[str, float]
    explanation: str


@router.post("/mine")
async def mine_repository(request: MineRequest) -> dict[str, str]:
    return {"status": "queued", "repo": request.repo_url}


@router.post("/predict", response_model=PredictResponse)
async def predict_defect(request: PredictRequest) -> PredictResponse:
    raise HTTPException(status_code=501, detail="Not implemented yet")


@router.get("/repositories")
async def list_repositories() -> dict[str, list]:
    return {"repositories": []}


@router.get("/metrics/{repo_id}")
async def get_metrics(repo_id: int) -> dict:
    raise HTTPException(status_code=404, detail="Repository not found")
