"""
Application Configuration Module

This module handles all application settings using Pydantic's BaseSettings.
Environment variables are automatically loaded from a .env file, making it
easy to manage different configurations for development and production.
"""

from pydantic_settings import BaseSettings
from pydantic import field_validator

class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    
    Pydantic automatically reads these values from:
    1. Environment variables (highest priority)
    2. .env file (if exists)
    3. Default values (if specified)
    
    This approach keeps secrets out of version control while providing
    type validation and IDE autocomplete support.
    """
    
    # Security key for signing JWT tokens and session data
    # Should be a long, random string in production
    SECRET_KEY: str
    
    # Additional secret for conference-specific authentication
    # Used to validate that users are legitimate conference attendees
    CONFERENCE_SECRET: str
    
    # API key for Resend email service
    # Used to send magic link authentication emails
    RESEND_API_KEY: str
    
    # Email address used as the sender for outgoing emails
    # Must be verified in Resend dashboard
    FROM_EMAIL: str
    
    # PostgreSQL database connection string
    # Format: postgresql+asyncpg://user:password@host:port/dbname
    DATABASE_URL: str
    
    # Redis connection string for caching and real-time features
    # Default points to local Redis instance
    REDIS_URL: str = "redis://localhost:6379"
    
    # Environment mode: "development" or "production"
    # Affects logging verbosity and debug features
    ENVIRONMENT: str = "production"

    # Comma-separated list of super user emails
    # These users have admin privileges (delete messages, ban users)
    SUPER_USERS: str = ""

    @field_validator("DATABASE_URL")
    def validate_database_url(cls, value):
        if not value:
            return ""
        if not value.startswith("postgresql+asyncpg://"):
            print("Invalid database URL format. Using default.")
            print("Value: ", value)
            print("New Value: ", value.replace("postgresql://", "postgresql+asyncpg://"))
            return value.replace("postgresql://", "postgresql+asyncpg://")
        return value

    class Config:
        """
        Pydantic configuration class.
        
        Tells Pydantic to load settings from a .env file,
        which should be placed in the project root directory.
        """
        env_file = ".env"


# Global settings instance used throughout the application
# Import this instance to access configuration values
settings = Settings()
