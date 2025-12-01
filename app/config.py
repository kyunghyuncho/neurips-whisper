from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    SECRET_KEY: str
    CONFERENCE_SECRET: str
    RESEND_API_KEY: str
    FROM_EMAIL: str
    DATABASE_URL: str
    REDIS_URL: str = "redis://localhost:6379"
    ENVIRONMENT: str = "production"

    class Config:
        env_file = ".env"

settings = Settings()
