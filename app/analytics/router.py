from fastapi import APIRouter, Body, HTTPException, Query
from typing import List, Optional
import base64
from io import BytesIO
import requests
import google.generativeai as genai
from PIL import Image
import os
from dotenv import load_dotenv
from .schemas import ScreenshotModel, ScreenshotResponse, BatchAnalysisRequest, SimpleAnalysisResponse
from .crud import add_screenshot, retrieve_screenshots

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

@router.post("/analyze-recent", response_model=SimpleAnalysisResponse)
async def analyze_recent_images(analysis_request: BatchAnalysisRequest = Body(...)):
    """
    Analyze multiple recent screenshots together using Gemini API
    and provide a single comprehensive analysis
    """
    try:
        # Validate API key
        if not GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
        
        # Get the most recent screenshots
        count = min(analysis_request.count, 10)  # Limit to 10 to prevent abuse
        recent_screenshots = await retrieve_screenshots(count)
        
        if not recent_screenshots:
            raise HTTPException(status_code=404, detail="No screenshots found")
        
        # Process images for Gemini
        processed_images = []
        image_metadata = []
        
        for screenshot in recent_screenshots:
            try:
                # Get image data
                image_data = screenshot.get("image")
                if not image_data:
                    continue
                
                # Check if image is base64 encoded
                if isinstance(image_data, str) and image_data.startswith('data:image'):
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
                        continue
                
                # Add image to processed images
                processed_images.append(Image.open(image_bytes))
                
                # Add metadata
                image_metadata.append({
                    "id": screenshot.get("id"),
                    "timestamp": screenshot.get("timestamp"),
                    "source": screenshot.get("source", "YouTube Studio")
                })
                
            except Exception as img_error:
                print(f"Error processing image {screenshot.get('id')}: {str(img_error)}")
                continue
        
        if not processed_images:
            raise HTTPException(status_code=400, detail="None of the screenshots could be processed")
        
        # Get a single comprehensive analysis from Gemini
        insights = analyze_multiple_images(
            processed_images,
            image_metadata,
            analysis_request.analysis_type,
            GEMINI_API_KEY
        )
        
        # Format the response
        return {
            "image_count": len(processed_images),
            "analysis_type": analysis_request.analysis_type,
            "insights": insights,
            "image_ids": [meta["id"] for meta in image_metadata],
            "success": True
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing images: {str(e)}")

def analyze_multiple_images(images, metadata, analysis_type, api_key):
    """Send multiple images to Gemini API for a single comprehensive analysis"""
    # Configure the API
    genai.configure(api_key=api_key)

    # Create a model instance
    model = genai.GenerativeModel('gemini-2.0-flash')

    # Prepare the prompt based on analysis type
    prompt_templates = {
        "youtube_analytics": "I'm showing you {count} YouTube analytics screenshots from my channel. Analyze these screenshots together to provide a comprehensive understanding of my channel performance. Identify key metrics, trends, opportunities, and what's working vs. what needs improvement. Give me actionable insights to improve my channel.",
        
        "thumbnail_analysis": "I'm showing you {count} YouTube thumbnails from my channel. Analyze these thumbnails together to evaluate their design consistency, appeal, clickability, and effectiveness. Identify strengths, weaknesses, and provide specific suggestions to improve my thumbnail strategy.",
        
        "content_strategy": "I'm showing you {count} screenshots from YouTube Studio related to my content strategy. Analyze these images collectively to provide insights on what's working well in my content approach and what could be improved. Give me specific recommendations to optimize my content strategy.",
        
        "audience_engagement": "I'm showing you {count} audience engagement screenshots from YouTube. Analyze these collectively to identify patterns in viewer behavior, engagement trends, and opportunities for improvement. Provide actionable advice to increase my audience engagement.",
        
        "monetization": "I'm showing you {count} YouTube monetization data screenshots. Analyze these together to identify revenue patterns, opportunities, and strategies for optimization. What's working well and what could be improved to maximize my revenue?",
        
        "competitor_analysis": "I'm showing you {count} screenshots from competitor YouTube channels. Analyze these collectively to identify their strategies, strengths, and weaknesses. What can I learn from them to improve my own channel?"
    }
    
    default_prompt = "I'm showing you {count} YouTube Studio screenshots. Analyze these images collectively to provide a comprehensive understanding of my channel performance. What's working well? What needs improvement? Give me specific, actionable recommendations to optimize my YouTube strategy."
    
    # Select and format the prompt template
    prompt_template = prompt_templates.get(analysis_type, default_prompt)
    prompt = prompt_template.format(count=len(images))
    
    # Add metadata context to the prompt if available
    if metadata and len(metadata) > 0:
        date_range = ""
        if len(metadata) > 1 and all(meta.get("timestamp") for meta in metadata):
            # Sort by timestamp
            sorted_meta = sorted(metadata, key=lambda x: x.get("timestamp"))
            oldest = sorted_meta[0].get("timestamp")
            newest = sorted_meta[-1].get("timestamp")
            if oldest and newest:
                date_range = f"These screenshots span from {oldest.strftime('%Y-%m-%d')} to {newest.strftime('%Y-%m-%d')}. "
        
        prompt += f"\n\n{date_range}Please provide a detailed analysis with specific insights and recommendations."
    
    # Create request with prompt and all images
    request_parts = [prompt] + images
    
    # Generate content
    response = model.generate_content(request_parts)
    
    return response.text 