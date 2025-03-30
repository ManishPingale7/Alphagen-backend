from fastapi import FastAPI
from app.edu.router import router as edu_router
from app.creative.router import router as creative_router
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.analytics.router import router as analytics_router
from app.auth.router import router as auth_router
from app.analytics.youtube_dashboard import router as youtube_router

app = FastAPI(title="AlphaGen")

# Configure CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static directory to serve files - IMPORTANT for image serving
app.mount("/static", StaticFiles(directory="static"), name="static")

app.include_router(edu_router)
app.include_router(creative_router)
app.include_router(analytics_router)
app.include_router(auth_router)
app.include_router(youtube_router)


@app.get("/")
def root():
    return {"message": "Welcome to the AlphaGen!"}
