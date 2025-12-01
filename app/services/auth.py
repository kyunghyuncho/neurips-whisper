"""
JWT Token Authentication Service

This module handles creation and verification of JSON Web Tokens (JWTs)
for stateless authentication. JWTs are self-contained tokens that encode
user information and are cryptographically signed to prevent tampering.

Key concepts:
- Tokens are signed with HMAC-SHA256 using the secret key
- Tokens include an expiration time for security
- No database lookup needed to verify tokens (stateless)
"""

from datetime import datetime, timedelta
from jose import jwt
from app.config import settings


# HMAC-SHA256 algorithm for signing JWT tokens
# This is a symmetric signing method (same key for sign/verify)
# More secure than "none" or "HS256" alone, commonly used for server-to-server auth
ALGORITHM = "HS256"


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """
    Create a JWT access token with the given payload data.
    
    The token is signed with the SECRET_KEY and includes an expiration time.
    This creates a tamper-proof token that can be verified without database access.
    
    Args:
        data: Payload to encode in the token (typically {"sub": email})
              "sub" is the JWT standard claim for the subject (user identifier)
        expires_delta: Optional custom expiration time delta
                      If not provided, defaults to 15 minutes
    
    Returns:
        Encoded JWT string that can be sent to the client
        
    Example:
        token = create_access_token({"sub": "user@example.com"})
        # Returns: "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
    """
    # Copy the data to avoid mutating the original dict
    to_encode = data.copy()
    
    # Calculate expiration time
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        # Default: token expires in 15 minutes
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    # Add "exp" claim (expiration time as Unix timestamp)
    # This is a JWT standard claim that the library will check automatically
    to_encode.update({"exp": expire})
    
    # Encode and sign the JWT with our secret key
    # The resulting string has three parts separated by dots:
    # 1. Header (algorithm and type)
    # 2. Payload (our data + expiration)
    # 3. Signature (HMAC of header + payload)
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    
    return encoded_jwt


def verify_token(token: str) -> dict | None:
    """
    Verify and decode a JWT token.
    
    This checks:
    1. Signature is valid (token hasn't been tampered with)
    2. Token hasn't expired
    3. Token was issued by us (encoded with our SECRET_KEY)
    
    Args:
        token: JWT string to verify
        
    Returns:
        Decoded payload dictionary if valid, None if invalid/expired
        
    Example:
        payload = verify_token(token)
        if payload:
            email = payload.get("sub")
            # User is authenticated
        else:
            # Token is invalid or expired
    """
    try:
        # Decode and verify the token
        # This will raise JWTError if:
        # - Signature is invalid
        # - Token is expired
        # - Token is malformed
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.JWTError:
        # Token verification failed
        # Don't expose the specific error to prevent information leakage
        return None
