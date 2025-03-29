from pydantic import BaseModel
from typing import Optional

class ThumbnailRequest(BaseModel):
    video_title: str
    video_description: Optional[str] = ""
    style: Optional[str] = "Modern, Professional"

class ThumbnailResponse(BaseModel):
    image_url: str
    title_text: str
    subtitle_text: Optional[str] = ""
    download_url: Optional[str] = ""  # URL to download the image
    file_id: Optional[str] = ""       # File ID for reference 