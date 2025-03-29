from fastapi import APIRouter, Body, HTTPException, Query
from typing import List, Optional
import base64
from io import BytesIO
import requests
import google.generativeai as genai
from PIL import Image
import os
from dotenv import load_dotenv
from .schemas import ScreenshotModel, ScreenshotResponse, AnalysisRequest, AnalysisResponse
from .crud import add_screenshot, retrieve_screenshots, get_screenshot_by_id

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

router = APIRouter(prefix="/analytics", tags=["Analytics APIs"])

@router.post("/screenshots", response_model=ScreenshotResponse)
async def save_screenshot(screenshot: ScreenshotModel = Body(...)):
    """Save a screenshot to MongoDB"""
    try:
        result = await add_screenshot(screenshot)
        return {"success": True, "id": result["id"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error saving screenshot: {str(e)}")

@router.get("/screenshots", response_model=List[dict])
async def get_screenshots(limit: int = 10):
    """Get most recent screenshots"""
    try:
        return await retrieve_screenshots(limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving screenshots: {str(e)}")

@router.post("/analyze-image", response_model=AnalysisResponse)
async def analyze_image(analysis_request: AnalysisRequest = Body(...)):
    """
    Analyze a screenshot using Gemini API
    """
    try:
        # Validate API key
        if not GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
        
        # Get the screenshot from database
        screenshot = await get_screenshot_by_id(analysis_request.image_id)
        if not screenshot:
            raise HTTPException(status_code=404, detail=f"Screenshot with ID {analysis_request.image_id} not found")
        
        # Get image data
        image_data = screenshot.get("image")
        if not image_data:
            raise HTTPException(status_code=400, detail="No image data found in the screenshot")
        
        # Check if image is base64 encoded
        if image_data.startswith('data:image'):
            # Extract the base64 part
            image_data = image_data.split(',')[1]
        
        # Convert base64 to bytes
        try:
            image_bytes = BytesIO(base64.b64decode(image_data))
        except Exception as e:
            # If not base64, try to get image from URL
            try:
                response = requests.get(image_data)
                response.raise_for_status()
                image_bytes = BytesIO(response.content)
            except Exception as url_error:
                raise HTTPException(status_code=400, 
                    detail=f"Could not process image data: {str(e)}. URL fetch failed: {str(url_error)}")
        
        # Get insights from Gemini
        insights = get_gemini_insights(
            image_bytes, 
            analysis_request.analysis_type, 
            GEMINI_API_KEY
        )
        
        # Format the response
        return {
            "image_id": analysis_request.image_id,
            "analysis_type": analysis_request.analysis_type,
            "insights": insights,
            "success": True
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing image: {str(e)}")

def get_gemini_insights(image_bytes, analysis_type, api_key):
    """Send an image to Gemini API and get insights"""
    # Configure the API
    genai.configure(api_key=api_key)

    # Open the image with PIL
    image = Image.open(image_bytes)

    # Create a model instance
    model = genai.GenerativeModel('gemini-pro-vision')

    # Prepare the prompt based on analysis type
    prompt_map = {
        "youtube_analytics": "Analyze this YouTube analytics screenshot. Identify key metrics, trends, and performance indicators. What's working well and what needs improvement?",
        "thumbnail_analysis": "Analyze this YouTube thumbnail. Evaluate its design, appeal, clickability, and how well it represents the content. Suggest improvements.",
        "content_strategy": "Analyze this screenshot from YouTube Studio. What does it indicate about content strategy? What's working and what could be improved?",
        "audience_engagement": "Analyze this audience engagement screenshot from YouTube. What patterns do you see in viewer behavior? How can engagement be improved?",
        "monetization": "Analyze this YouTube monetization data. What revenue patterns do you see? How could revenue be optimized?",
        "competitor_analysis": "Analyze this competitor's YouTube channel screenshot. What strategies are they using? What can be learned from them?"
    }

    prompt = prompt_map.get(
        analysis_type, "Analyze this YouTube Studio screenshot. Provide detailed insights on what's working well and what needs improvement. Include specific actionable recommendations.")

    # Generate content
    response = model.generate_content([prompt, image])

    return response.text 