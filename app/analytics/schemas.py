from pydantic import BaseModel
from datetime import datetime
from typing import Optional, List

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

class BatchAnalysisRequest(BaseModel):
    count: int = 5  # Number of recent images to analyze
    analysis_type: Optional[str] = "youtube_analytics"  # youtube_analytics, thumbnail_analysis, etc.

class SimpleAnalysisResponse(BaseModel):
    image_count: int
    analysis_type: str
    insights: str
    image_ids: List[str]
    success: bool