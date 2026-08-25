from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "SDP ML Service"
    debug: bool = False

    database_url: str = "postgresql://sdp:sdp_password@localhost:5432/sdp_thesis"

    repos_clone_dir: str = "./data/repos"

    # LLM API for explainability
    llm_api_key: str = ""
    llm_api_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    trained_models_dir: str = "./trained_models"

    model_config = {"env_file": ".env", "env_prefix": "SDP_"}


settings = Settings()
