from pydantic import BaseModel
from datetime import datetime
from typing import Optional

class ScreenshotModel(BaseModel):
    image: str
    timestamp: Optional[datetime] = None
    source: str = "YouTube Studio"
    type: str = "screenshot"
    user_id: Optional[str] = None

class ScreenshotResponse(BaseModel):
    success: bool
    id: str

class AnalysisRequest(BaseModel):
    image_id: str
    analysis_type: Optional[str] = "general"  # general, youtube_analytics, thumbnail_analysis, etc.

class AnalysisResponse(BaseModel):
    image_id: str
    analysis_type: str
    insights: str
    success: bool 