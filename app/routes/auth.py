from fastapi import APIRouter, Depends, HTTPException, status, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from app.database import get_db
from app.models import User
from app.services.auth import create_access_token, verify_token
from app.services.email import send_magic_link
from app.utils.validators import is_institutional_email
from app.config import settings
from pydantic import EmailStr

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login")
async def login(
    request: Request,
    email: EmailStr = Form(...),
    conference_code: str = Form(...),
    agree_terms: bool = Form(...),
    db: AsyncSession = Depends(get_db)
):
    if conference_code != settings.CONFERENCE_SECRET:
        raise HTTPException(status_code=400, detail="Invalid conference code")
    
    if not agree_terms:
        raise HTTPException(status_code=400, detail="You must agree to the terms")

    if not is_institutional_email(email):
        raise HTTPException(status_code=400, detail="Please use your institutional or company email")

    # Check if user exists, create if not
    result = await db.execute(select(User).filter(User.email == email))
    user = result.scalars().first()
    
    if not user:
        user = User(email=email)
        db.add(user)
        await db.commit()
        await db.refresh(user)

    # Generate Magic Link
    token = create_access_token({"sub": user.email})
    link = f"{request.base_url}auth/verify?token={token}"
    
    send_magic_link(email, link)
    
    return {"message": "Magic link sent to your email"}

@router.get("/verify")
async def verify(token: str):
    payload = verify_token(token)
    if not payload:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    
    email = payload.get("sub")
    if not email:
        raise HTTPException(status_code=400, detail="Invalid token")
        
    # In a real app, we would set a session cookie here
    # For now, we just return a success message or redirect
    return {"message": "Login successful", "email": email}
