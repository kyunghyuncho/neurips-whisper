"""
Authentication Dependencies for FastAPI Routes

This module provides dependency injection functions for authentication.
These can be used in route handlers to require or optionally check for
authenticated users.

FastAPI's dependency injection system makes these reusable across routes
while keeping authentication logic centralized.
"""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import User
from app.services.auth import verify_token


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User:
    """
    Dependency that requires an authenticated user.
    
    This function:
    1. Extracts the JWT token from the request cookie
    2. Verifies the token signature and expiration
    3. Looks up the user in the database
    4. Returns the User object or raises HTTP 401
    
    Usage in routes:
        @app.post("/protected")
        async def protected_route(user: User = Depends(get_current_user)):
            # user is guaranteed to be authenticated here
            return {"email": user.email}
    
    Raises:
        HTTPException: 401 if authentication fails at any step
    """
    # Extract token from cookie (set during login)
    # Cookie name "access_token" is standard for OAuth/JWT
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    try:
        # Token is stored as "Bearer <jwt_token>" format (OAuth 2.0 standard)
        # We need to extract just the JWT part
        scheme, _, param = token.partition(" ")
        if scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token scheme"
            )
        
        # Verify JWT signature and decode payload
        # This checks: signature, expiration, and issuer
        payload = verify_token(param)
        if not payload:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token"
            )
        
        # Extract email from JWT "sub" (subject) claim
        # "sub" is standard JWT claim for the subject identifier
        email = payload.get("sub")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload"
            )
        
        # Look up user in database
        # Token is valid, but user might have been deleted
        result = await db.execute(select(User).filter(User.email == email))
        user = result.scalars().first()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User not found"
            )
        
        # Check if user is a superuser
        # SUPER_USERS is a comma-separated string of emails
        from app.config import settings
        super_users = [e.strip() for e in settings.SUPER_USERS.split(",") if e.strip()]
        user.is_superuser = user.email in super_users
        
        return user
        
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Catch any other errors (e.g., database errors, token decode errors)
        # Don't expose internal error details to client for security
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication failed"
        )


async def get_optional_user(
    request: Request,
    db: AsyncSession = Depends(get_db)
) -> User | None:
    """
    Dependency that optionally returns an authenticated user.
    
    Unlike get_current_user, this doesn't raise an exception if
    the user is not authenticated - it simply returns None.
    
    This is useful for pages that work for both authenticated
    and anonymous users, but show different content/features
    based on authentication status.
    
    Usage in routes:
        @app.get("/")
        async def homepage(user: User | None = Depends(get_optional_user)):
            if user:
                return {"message": f"Welcome back, {user.email}!"}
            else:
                return {"message": "Welcome, guest!"}
    
    Returns:
        User object if authenticated, None otherwise
    """
    try:
        return await get_current_user(request, db)
    except HTTPException:
        # Authentication failed, but that's okay for optional auth
        return None
