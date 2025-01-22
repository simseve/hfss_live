from pydantic_settings import SettingsConfigDict, BaseSettings
from typing import List
from pydantic import UUID4

class Settings(BaseSettings):
    DATABASE_URI: str
    APP_NAME: str
    PROD: bool
    SECRET_KEY: str
    ALGORITHM: str
    BUCKET_HOST: str
    BUCKET_ACCESS: str
    BUCKET_SECRET: str
    BUCKET_NAME: str



    def get_target_urls_list(self, target_urls: str) -> List[str]:
        target_urls_value = getattr(self, target_urls, "")
        return [url.strip() for url in target_urls_value.split(',') if url]

    class Config:
        env_file = '.env'

settings = Settings()