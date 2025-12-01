"""
Rate Limiting Configuration

This module sets up the slowapi Limiter using Redis as the storage backend.
It provides a centralized limiter instance that can be imported and used
to decorate routes throughout the application.
"""

from slowapi import Limiter
from slowapi.util import get_remote_address
from app.config import settings

# Initialize Limiter
# key_func=get_remote_address: Uses the client's IP address as the unique identifier
# storage_uri: Connects to Redis for persisting limit counters
limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=settings.REDIS_URL,
    strategy="fixed-window" # Standard fixed window algorithm
)
