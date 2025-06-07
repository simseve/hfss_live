from pydantic_settings import SettingsConfigDict, BaseSettings
from typing import List, Optional
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
    HFSS_SERVER: str
    GOOGLE_MAPS_API_KEY: str
    FLYMASTER_SECRET: str

    # Firebase configuration (optional)
    FIREBASE_CREDENTIALS: Optional[str] = None
    FIREBASE_KEY_PATH: Optional[str] = None

    def get_target_urls_list(self, target_urls: str) -> List[str]:
        target_urls_value = getattr(self, target_urls, "")
        return [url.strip() for url in target_urls_value.split(',') if url]

    class Config:
        env_file = '.env'


settings = Settings()
