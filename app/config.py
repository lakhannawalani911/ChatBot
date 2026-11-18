from pydantic_settings import BaseSettings
from functools import lru_cache
from pathlib import Path
from os.path import join as path_join
class Settings(BaseSettings):
    gemini_api_key:str
    gemini_model_name: str
    primary_model:str = "gemini-3.1-flash-lite"
    #langsmith
    langchain_tracing_v2: bool = True
    langchain_api_key:str = ""
    langchain_project:str ="production-api"

    #application
    app_env:str="development"
    log_level:str = "INFO"
    rate_limit:str = "20/minute"
    cache_ttl_seconds:int =300
    max_retries: int = 3
    model_config = {"env_file":path_join(str(Path(__file__).resolve().parent.parent),".env"),"extra":"ignore"}

    @property
    def is_production(self) -> bool:    
        return self.app_env == "production"

@lru_cache
def get_settings() -> Settings:
    """cached setting instances -loaded onces, resused everywhere"""
    return Settings()

if __name__ == "__main__":
    settings = get_settings()
    print(f"{settings.app_env=}")
    print(f"{settings.primary_model=}")
    print(f"{settings.rate_limit=}")
    print(f"{settings.cache_ttl_seconds=}")
    print(f"{settings.max_retries=}")
    print(f"{settings.is_production=}")
    print(f"{settings.gemini_api_key}")
    print(f"{settings.gemini_model_name=}")

    print("Config loaded successfully!")
