from functools import lru_cache

# from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import HttpUrl
from typing import Any

# had to use load_dotenv() to get the env variables to work during testing
# load_dotenv()


class Settings(BaseSettings):
    database_name: str
    db_username: str
    db_password: str
    db_host: str
    db_protocol: str
    testing: bool = False

    oidc_issuer: str
    hydroshare_meta_read_url: HttpUrl
    hydroshare_file_read_url: HttpUrl
    search_relevance_score_threshold: float = 1.4

    vite_app_name: str = "iguide-catalog"
    vite_app_url: HttpUrl = "http://localhost:5173"
    vite_app_api_url: HttpUrl = "http://localhost:8000/api/v1"
    vite_app_login_url: HttpUrl = "http://localhost:5173/login"
    vite_app_google_maps_api_key: str = ""
    vite_app_support_email: str = ""
    vite_app_client_id: str = ""

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if self.testing:
            self.database_name = f"{self.database_name}"

    @property
    def db_connection_string(self):
        return f"{self.db_protocol}://{self.db_username}:{self.db_password}@{self.db_host}/?retryWrites=true&w=majority"

    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()
