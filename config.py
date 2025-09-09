from pydantic_settings import SettingsConfigDict, BaseSettings
from typing import List, Optional
from pydantic import UUID4


class Settings(BaseSettings):
    DATABASE_URL: str  # Primary database connection
    # Legacy support - will use DATABASE_URL if not set
    @property
    def DATABASE_URI(self) -> str:
        """Backward compatibility for DATABASE_URI"""
        return self.DATABASE_URL
    # Read-only replica database URI (defaults to primary if not set)
    DATABASE_REPLICA_URI: Optional[str] = None
    # Flag to enable/disable replica usage
    USE_REPLICA: bool = True  # Default to True, can be overridden by env
    # Flag to indicate if using Neon DB
    USE_NEON: bool = False
    
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

    # GPS TCP Server configuration
    GPS_TCP_PORT: int = 9090
    GPS_TCP_ENABLED: bool = False
    
    # Redis configuration
    # Full Redis URL (overrides individual settings)
    REDIS_URL: Optional[str] = None
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: Optional[str] = None
    REDIS_MAX_CONNECTIONS: int = 20
    
    # Datadog configuration (optional)
    DD_API_KEY: Optional[str] = None
    DD_APP_KEY: Optional[str] = None
    DD_AGENT_HOST: str = "localhost"
    DD_DOGSTATSD_PORT: int = 8125
    DD_ENV: str = "development"
    DD_VERSION: str = "1.0.0"
    
    # Alert thresholds
    ALERT_QUEUE_PENDING_WARN: int = 1000
    ALERT_QUEUE_PENDING_CRIT: int = 5000
    ALERT_DLQ_WARN: int = 10
    ALERT_DLQ_CRIT: int = 100
    ALERT_PROCESSING_LAG: int = 300
    ALERT_NO_DATA_MINUTES: int = 5
    ALERT_ERROR_RATE: float = 5.0
    ALERT_LATENCY_WARN: int = 1000
    ALERT_LATENCY_CRIT: int = 5000

    def get_redis_url(self) -> str:
        """Get Redis URL from environment or construct from individual settings"""
        # Always prefer REDIS_URL from environment if set
        if self.REDIS_URL:
            return self.REDIS_URL

        # Fallback to constructing URL from individual settings
        host = self.REDIS_HOST
        
        if self.REDIS_PASSWORD:
            # Include password in URL for authentication
            return f"redis://:{self.REDIS_PASSWORD}@{host}:{self.REDIS_PORT}/{self.REDIS_DB}"
        else:
            return f"redis://{host}:{self.REDIS_PORT}/{self.REDIS_DB}"

    def get_target_urls_list(self, target_urls: str) -> List[str]:
        target_urls_value = getattr(self, target_urls, "")
        return [url.strip() for url in target_urls_value.split(',') if url]

    class Config:
        env_file = '.env'


settings = Settings()
