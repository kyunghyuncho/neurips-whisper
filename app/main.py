from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.templating import Jinja2Templates
from app.config import settings
from app.routes import auth, feed
from app.database import engine
from app.models import Base

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(title="NeurIPS Whisper", lifespan=lifespan)
templates = Jinja2Templates(directory="app/templates")

app.include_router(auth.router)
app.include_router(feed.router)

@app.get("/")
async def root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})
