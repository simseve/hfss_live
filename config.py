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

    # Redis configuration
    # Full Redis URL (overrides individual settings)
    REDIS_URL: Optional[str] = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_MAX_CONNECTIONS: int = 20

    def get_redis_url(self) -> str:
        """Generate Redis URL based on environment (dev vs prod)"""
        if self.REDIS_URL:
            return self.REDIS_URL

        # Use different hostnames for dev vs prod
        host = "redis" if self.PROD else self.REDIS_HOST

        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{host}:{self.REDIS_PORT}/{self.REDIS_DB}"
        else:
            return f"redis://{host}:{self.REDIS_PORT}/{self.REDIS_DB}"

    def get_target_urls_list(self, target_urls: str) -> List[str]:
        target_urls_value = getattr(self, target_urls, "")
        return [url.strip() for url in target_urls_value.split(',') if url]

    class Config:
        env_file = '.env'


settings = Settings()
