from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "SDP ML Service"
    debug: bool = False

    database_url: str = "postgresql://sdp:sdp_password@localhost:5432/sdp_thesis"

    repos_clone_dir: str = "./data/repos"

    # LLM API for explainability (Ollama by default — no API key needed)
    llm_api_key: str = ""
    llm_api_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3.2"

    trained_models_dir: str = "./trained_models"

    # Auth (simple admin token for the dashboard)
    admin_username: str = "admin"
    admin_password: str = "sdp2026"
    jwt_secret: str = "sdp-thesis-secret-key-change-in-prod"

    model_config = {"env_file": ".env", "env_prefix": "SDP_"}


settings = Settings()
