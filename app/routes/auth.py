"""
Authentication Routes

This module implements passwordless authentication using magic links.
The flow:
1. User enters email and conference code
2. System sends email with one-time login link
3. User clicks link to verify and get logged in
4. JWT token is stored in HTTP-only cookie

This approach is more secure than passwords for temporary events:
- No password to forget or leak
- Links expire after single use or timeout
- Conference code gates access to authorized attendees only
"""

from fastapi import APIRouter, Depends, HTTPException, status, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import User
from app.services.auth import create_access_token, verify_token
from app.services.email import send_magic_link
from app.utils.validators import is_institutional_email
from app.config import settings
from app.templating import templates
from pydantic import EmailStr


# Create router with /auth prefix
# All routes defined here will be accessible at /auth/...
router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login")
async def login(
    request: Request,
    email: EmailStr = Form(...),  # EmailStr validates email format
    conference_code: str = Form(...),
    agree_terms: bool = Form(...),
    db: AsyncSession = Depends(get_db)
):
    """
    Step 1 of authentication: Validate user info and send magic link.
    
    This endpoint:
    1. Validates conference code to ensure user is authorized
    2. Checks terms of service agreement
    3. Validates institutional email address
    4. Creates user account if first time
    5. Generates magic link with JWT token
    6. Sends email with the link
    
    Args:
        request: FastAPI request (for base URL)
        email: User's email address (validated)
        conference_code: Secret code for conference access
        agree_terms: Whether user agreed to terms
        db: Database session
        
    Returns:
        HTML partial showing "check your email" message
        
    Raises:
        HTTPException: If validation fails
    """
    # Validate conference code to gate access
    # This prevents random people from using the app
    if conference_code != settings.CONFERENCE_SECRET:
        raise HTTPException(
            status_code=400, 
            detail="Invalid conference code"
        )
    
    # Require terms of service agreement
    # This is important for legal/policy compliance
    if not agree_terms:
        raise HTTPException(
            status_code=400, 
            detail="You must agree to the terms"
        )

    # Only allow institutional emails (not gmail, yahoo, etc.)
    # This helps ensure users are actual conference attendees
    if not is_institutional_email(email):
        raise HTTPException(
            status_code=400, 
            detail="Please use your institutional or company email"
        )

    # Check if user exists, create if not
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()
    
    if not user:
        # First-time user - create account
        user = User(email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)  # Refresh to get auto-generated ID

    # Generate magic link with JWT token
    # Token contains user email in the "sub" (subject) claim
    token = create_access_token({"sub": user.email})
    
    # Build verification URL with token as query parameter
    # When user clicks this link, they'll hit the /auth/verify endpoint
    link = f"{request.base_url}auth/verify?token={token}"
    
    # Send email with magic link
    # This is async but we don't await - email sending happens in background
    send_magic_link(email, link)
    
    # Return HTML partial to show in the page
    # This uses HTMX to update the UI without full page reload
    return templates.TemplateResponse(
        "partials/magic_link_sent.html", 
        {"request": request, "email": email}
    )


@router.get("/verify")
async def verify(token: str):
    """
    Step 2 of authentication: Verify magic link token and log user in.
    
    This endpoint is called when user clicks the magic link in their email.
    It verifies the JWT token and sets an authentication cookie.
    
    Args:
        token: JWT token from magic link URL
        
    Returns:
        Redirect to homepage with authentication cookie set
        
    Raises:
        HTTPException: If token is invalid or expired
    """
    # Verify JWT token signature and expiration
    payload = verify_token(token)
    if not payload:
        raise HTTPException(
            status_code=400, 
            detail="Invalid or expired token"
        )
    
    # Extract email from token
    email = payload.get("sub")
    if not email:
        raise HTTPException(
            status_code=400, 
            detail="Invalid token"
        )
    
    # Redirect to homepage
    # Status code 303 ensures the browser makes a GET request (not POST)
    response = RedirectResponse(url="/", status_code=303)
    
    # Set authentication cookie
    # This is how the browser remembers the user is logged in
    response.set_cookie(
        key="access_token",
        value=f"Bearer {token}",  # OAuth 2.0 standard format
        httponly=True,  # JavaScript can't access (prevents XSS attacks)
        max_age=1800,  # 30 minutes in seconds
        samesite="lax",  # CSRF protection
        secure=False  # Set to True in production with HTTPS
    )
    
    return response


@router.get("/logout")
async def logout():
    """
    Log user out by deleting the authentication cookie.
    
    Returns:
        Redirect to homepage with cookie deleted
    """
    response = RedirectResponse(url="/", status_code=303)
    # Delete the authentication cookie to log user out
    response.delete_cookie("access_token")
    return response
