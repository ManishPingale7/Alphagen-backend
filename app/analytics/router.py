from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import FileResponse
from typing import List, Optional
import base64
from io import BytesIO
import requests
import google.generativeai as genai
from PIL import Image
import os
import re
from dotenv import load_dotenv
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image as RLImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER, TA_LEFT
from reportlab.lib import colors
import uuid
import markdown
from datetime import datetime
from .schemas import ScreenshotModel, ScreenshotResponse, BatchAnalysisRequest, SimpleAnalysisResponse
from .crud import add_screenshot, retrieve_screenshots

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
TEMP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp")
os.makedirs(TEMP_DIR, exist_ok=True)

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

@router.post("/analyze-comprehensive", response_model=SimpleAnalysisResponse)
async def analyze_all_images(analysis_request: BatchAnalysisRequest = Body(...)):
    """
    Analyze ALL screenshots in the database together using Gemini API
    and provide a comprehensive insightful report
    """
    try:
        # Validate API key
        if not GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
        
        # Get all screenshots from database instead of just recent ones
        all_screenshots = await retrieve_screenshots(limit=10)  # Set high limit to get all images
        
        if not all_screenshots:
            raise HTTPException(status_code=404, detail="No screenshots found")
        
        # Process images for Gemini
        processed_images = []
        image_metadata = []
        
        for screenshot in all_screenshots:
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
        
        # Get a comprehensive analysis from Gemini
        insights = analyze_all_images_comprehensive(
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

@router.post("/chatbot-query", response_model=dict)
async def chatbot_query(query: str = Body(..., embed=True), analysis_type: Optional[str] = Body("youtube_analytics")):
    """
    RAG-based chatbot that uses the analyzed YouTube data to answer user queries
    """
    try:
        # Validate API key
        if not GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
        
        # Get all screenshots
        all_screenshots = await retrieve_screenshots(limit=100)  # Limit to last 100 for performance
        
        if not all_screenshots:
            raise HTTPException(status_code=404, detail="No screenshots found to use as context")
        
        # Process images
        processed_images = []
        image_metadata = []
        
        for screenshot in all_screenshots:
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
            raise HTTPException(status_code=400, detail="No images available to process for context")
        
        # Use the RAG approach to answer the query
        response = rag_chatbot_response(
            query,
            processed_images,
            image_metadata,
            analysis_type,
            GEMINI_API_KEY
        )
        
        return {
            "query": query,
            "response": response,
            "context_images": len(processed_images),
            "success": True
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing chatbot query: {str(e)}")

@router.get("/generate-report", response_class=FileResponse)
async def generate_pdf_report(analysis_type: str = "youtube_analytics"):
    """
    Generate a clean one-page PDF report from all screenshots without requiring any parameters
    """
    try:
        # Validate API key
        if not GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
        
        # Get screenshots from database (limit to 30 for better performance and concise analysis)
        all_screenshots = await retrieve_screenshots(limit=30)
        
        if not all_screenshots:
            raise HTTPException(status_code=404, detail="No screenshots found")
        
        # Process images for Gemini
        processed_images = []
        image_metadata = []
        
        for screenshot in all_screenshots:
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
        
        # Get a concise one-page analysis from Gemini
        insights = analyze_images_one_page(
            processed_images,
            image_metadata,
            analysis_type,
            GEMINI_API_KEY
        )
        
        # Generate clean PDF from insights
        pdf_path = create_clean_pdf_report(
            insights, 
            analysis_type,
            len(processed_images)
        )
        
        # Create a readable filename for the report
        report_type_name = analysis_type.replace("_", "-")
        readable_date = datetime.now().strftime('%b-%d-%Y')
        download_filename = f"YT-{report_type_name}-report-{readable_date}.pdf"
        
        # Return the PDF file for download
        return FileResponse(
            path=pdf_path,
            filename=download_filename,
            media_type="application/pdf"
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error generating report: {str(e)}")

@router.post("/rag-chat", response_model=dict)
async def rag_chat(query: str = Body(...), analysis_type: Optional[str] = Query("youtube_analytics")):
    """
    RAG-based chatbot that uses YouTube analytics screenshots as knowledge base
    """
    try:
        # Validate API key
        if not GEMINI_API_KEY:
            raise HTTPException(status_code=500, detail="GEMINI_API_KEY not configured")
        
        # Get a reasonable number of screenshots
        all_screenshots = await retrieve_screenshots(limit=50)
        
        if not all_screenshots:
            raise HTTPException(status_code=404, detail="No screenshots found to use as context")
        
        # Process images
        processed_images = []
        image_metadata = []
        
        for screenshot in all_screenshots:
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
            raise HTTPException(status_code=400, detail="No images available to process for context")
        
        # Use the RAG approach to answer the query
        response = rag_chatbot_response(
            query,
            processed_images,
            image_metadata,
            analysis_type,
            GEMINI_API_KEY
        )
        
        return {
            "query": query,
            "response": response,
            "context_images": len(processed_images),
            "success": True
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing chatbot query: {str(e)}")

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

def analyze_all_images_comprehensive(images, metadata, analysis_type, api_key):
    """Send all images to Gemini API for a comprehensive structured analysis report"""
    # Configure the API
    genai.configure(api_key=api_key)

    # Create a model instance
    model = genai.GenerativeModel('gemini-2.0-flash')

    # Enhanced comprehensive prompt templates
    comprehensive_prompt_templates = {
        "youtube_analytics": """I'm showing you {count} YouTube analytics screenshots from my channel's history. Create a COMPREHENSIVE REPORT analyzing these screenshots together. 

The report should include:
1. EXECUTIVE SUMMARY: Brief overview of channel performance and key insights
2. KEY METRICS ANALYSIS: Detailed breakdown of views, watch time, subscribers, revenue (if available)
3. TREND IDENTIFICATION: Identify clear patterns in performance over time
4. CONTENT PERFORMANCE: Which videos/types perform best and worst
5. AUDIENCE INSIGHTS: Demographics, watch behaviors, and engagement patterns
6. GROWTH OPPORTUNITIES: Specific areas showing potential for channel expansion
7. PROBLEM AREAS: Metrics that need improvement and potential causes
8. ACTIONABLE RECOMMENDATIONS: Prioritized list of specific actions to improve channel performance
9. FORECAST & TARGETS: Projected performance based on current trends

Format your response in clear sections with bullet points for key insights and bold text for critical findings. Provide specific, data-backed recommendations I can implement immediately.""",
        
        "thumbnail_analysis": """I'm analyzing {count} YouTube thumbnails from my channel. Create a COMPREHENSIVE THUMBNAIL ANALYSIS REPORT.

Include:
1. VISUAL CONSISTENCY: Evaluate brand consistency across thumbnails
2. DESIGN EFFECTIVENESS: Analyze color schemes, text readability, image quality
3. CLICK-THROUGH POTENTIAL: Assess how compelling each thumbnail is
4. THUMBNAIL vs. PERFORMANCE: Correlate thumbnail design with video performance (if metrics available)
5. COMPETITIVE ANALYSIS: How my thumbnails compare to successful channels
6. THUMBNAILS BY CATEGORY: Group and evaluate thumbnails by video type/theme
7. TOP PERFORMERS: Identify the most effective thumbnails and why they work
8. IMPROVEMENT OPPORTUNITIES: Specific design elements needing change
9. A/B TESTING RECOMMENDATIONS: Suggestions for thumbnail variants to test

Format as a structured report with visual design principles highlighted. Include specific, actionable recommendations for immediate improvement.""",
        
        "content_strategy": """I'm showing you {count} screenshots from YouTube Studio related to my content strategy. Create a COMPREHENSIVE CONTENT STRATEGY ANALYSIS.

Include:
1. CONTENT PORTFOLIO ASSESSMENT: Evaluate the mix and balance of content types
2. PERFORMANCE BY CATEGORY: Analyze how different content themes/formats perform
3. PUBLISHING PATTERNS: Assess upload frequency, timing, and consistency
4. AUDIENCE RETENTION ANALYSIS: Identify when and why viewers engage or drop off
5. KEYWORD & SEO EFFECTIVENESS: Evaluate title/description optimization patterns
6. COMPETITIVE POSITIONING: How my content compares in my niche
7. CONTENT GAPS & OPPORTUNITIES: Underserved topics with growth potential
8. OPTIMIZATION PRIORITIES: Specific content elements needing improvement
9. STRATEGIC CONTENT CALENDAR: Recommended content mix for future uploads

Format as a structured strategic analysis with specific action items highlighted. Provide data-backed rationale for all recommendations."""
    }
    
    default_comprehensive_prompt = """I'm showing you {count} YouTube Studio screenshots spanning my channel's history. Create a COMPREHENSIVE CHANNEL ANALYSIS REPORT.

Include:
1. EXECUTIVE SUMMARY: Overview of channel performance and key findings
2. PERFORMANCE METRICS: Detailed analysis of views, engagement, subscribers, and revenue trends
3. CONTENT EVALUATION: Assessment of video types, formats, and their respective performance
4. AUDIENCE ANALYSIS: Viewer demographics, behavior patterns, and engagement levels
5. COMPETITIVE POSITIONING: How the channel compares within its niche
6. GROWTH OPPORTUNITIES: Specific areas with potential for expansion
7. CHALLENGE AREAS: Metrics or elements needing improvement
8. STRATEGIC RECOMMENDATIONS: Prioritized action items for channel growth
9. FUTURE OUTLOOK: Projected performance based on identified trends

Format as a structured report with clear sections, bullet points for key insights, and bold text for critical findings. Provide specific, actionable recommendations based on the data shown."""
    
    # Select and format the prompt template
    prompt_template = comprehensive_prompt_templates.get(analysis_type, default_comprehensive_prompt)
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
                date_range = f"These screenshots span from {oldest.strftime('%Y-%m-%d')} to {newest.strftime('%Y-%m-%d')}, representing {len(images)} data points. "
        
        prompt += f"\n\n{date_range}Please structure your analysis as a professional report with clear sections and actionable insights. Focus on identifying patterns across all the data shown."
    
    # Create request with prompt and all images
    request_parts = [prompt] + images
    
    # Generate content
    response = model.generate_content(request_parts)
    
    return response.text

def analyze_images_one_page(images, metadata, analysis_type, api_key):
    """Send images to Gemini API for a full one-page analysis with highly personalized recommendations"""
    # Configure the API
    genai.configure(api_key=api_key)

    # Create a model instance
    model = genai.GenerativeModel('gemini-2.0-flash')

    # Detailed one-page prompt templates with emphasis on highly specific recommendations
    one_page_prompt_templates = {
        "youtube_analytics": """I'm showing you {count} YouTube analytics screenshots. Create a DETAILED one-page report with HIGHLY SPECIFIC insights based ONLY on the actual data visible in these screenshots.

Include these key areas (aim for a total of about 600-700 words):
1. Performance summary: Cite specific metrics visible in the screenshots (views, watch time, etc.)
2. Top trends: Identify exact patterns visible in the data (name specific videos, topics, or timeframes)
3. Content insights: Name specific videos or video types that are performing well/poorly
4. Audience analysis: Detail exact demographics and behaviors visible in the analytics
5. Strategic recommendations: Provide 5-7 HIGHLY SPECIFIC action items that directly relate to the data

EXTREMELY IMPORTANT:
- NEVER provide generic advice like "create engaging content" or "post consistently"
- ALWAYS tie recommendations to specific data points visible in the screenshots
- CITE actual numbers, percentages, and metrics from the screenshots
- NAME specific videos, topics, or content types that appear in the data
- SPECIFY exact timeframes, demographics, or trends visible in the analytics

Use markdown formatting with proper spacing:
- Use **bold text** for important metrics and key findings (ensure both opening and closing **)
- Use *italic text* for emphasis and secondary points (ensure proper opening/closing *)
- Use hyphens or asterisks with a space after (- or *) for bullet points
- Use section headers with ## followed by a space for each main section

Format the content to fill ONE FULL PAGE when rendered as a PDF. The recommendations must be data-driven and specific to THIS channel.""",
        
        "thumbnail_analysis": """I'm analyzing {count} YouTube thumbnails. Create a DETAILED one-page thumbnail analysis with HIGHLY SPECIFIC recommendations based ONLY on the actual thumbnails visible in these screenshots.

Include these areas (aim for about 600-700 words total):
1. Design assessment: Evaluate specific design elements visible in THESE thumbnails
2. Branding analysis: Comment on exact colors, fonts, and visual elements used
3. Strengths: Identify 4-6 specific effective elements in THESE thumbnails
4. Weaknesses: Point out 4-6 specific issues with THESE thumbnails
5. Best practices: Provide 5-7 HIGHLY SPECIFIC recommendations tailored to THESE thumbnails

EXTREMELY IMPORTANT:
- NEVER provide generic advice like "use bright colors" or "include faces"
- ALWAYS reference specific thumbnails visible in the screenshots
- DESCRIBE actual design elements, text placement, and imagery used
- COMPARE different thumbnails in the set to show what works/doesn't work
- SUGGEST specific changes to specific thumbnails

Use markdown formatting with proper spacing:
- Use **bold text** for important findings (ensure both opening and closing **)
- Use *italic text* for emphasis (ensure proper opening/closing *)
- Use hyphens or asterisks with a space after (- or *) for bullet points
- Use section headers with ## followed by a space for each main section

Format the content to fill ONE FULL PAGE when rendered as a PDF. The recommendations must be specific to THESE thumbnails."""
    }
    
    default_one_page_prompt = """I'm showing you {count} YouTube screenshots. Create a DETAILED one-page channel analysis with HIGHLY SPECIFIC insights based ONLY on the actual data visible in these screenshots.

Include these key areas (aim for about 600-700 words total):
1. Channel summary: Cite specific metrics visible in the screenshots
2. Key metrics: Provide exact numbers for views, watch time, subscribers, etc.
3. Content performance: Name specific videos or content types that are performing well/poorly
4. Key strengths: Detail exactly what's working well based on the visible data
5. Improvement areas: Identify specific issues that need addressing based on the visible metrics
6. Strategic action plan: Provide 5-7 HIGHLY SPECIFIC recommendations tied directly to the data

EXTREMELY IMPORTANT:
- NEVER provide generic advice like "improve SEO" or "engage with your audience"
- ALWAYS tie recommendations to specific data points visible in the screenshots
- CITE actual numbers, percentages, and metrics from the screenshots
- NAME specific videos, topics, or content types that appear in the data
- SPECIFY exact timeframes, demographics, or trends visible in the analytics

Use markdown formatting with proper spacing:
- Use **bold text** for important metrics and key findings (ensure both opening and closing **)
- Use *italic text* for emphasis and secondary points (ensure proper opening/closing *)
- Use hyphens or asterisks with a space after (- or *) for bullet points
- Use section headers with ## followed by a space for each main section

Format the content to fill ONE FULL PAGE when rendered as a PDF. The recommendations must be data-driven and specific to THIS channel."""
    
    # Select and format the prompt template
    prompt_template = one_page_prompt_templates.get(analysis_type, default_one_page_prompt)
    prompt = prompt_template.format(count=len(images))
    
    # Add minimal metadata context
    if metadata and len(metadata) > 0:
        date_range = ""
        if len(metadata) > 1 and all(meta.get("timestamp") for meta in metadata):
            # Sort by timestamp
            sorted_meta = sorted(metadata, key=lambda x: x.get("timestamp"))
            oldest = sorted_meta[0].get("timestamp")
            newest = sorted_meta[-1].get("timestamp")
            if oldest and newest:
                date_range = f"Data spans {oldest.strftime('%b %d')} to {newest.strftime('%b %d, %Y')}. "
        
        prompt += f"\n\n{date_range}Remember: Include enough detail to fill a full page with HIGHLY SPECIFIC insights and recommendations based ONLY on what is clearly visible in the screenshots."
    
    # Create request with prompt and all images
    request_parts = [prompt] + images
    
    # Generate content
    response = model.generate_content(request_parts)
    
    return response.text

def process_markdown_formatting(text):
    """
    Comprehensive function to process markdown formatting for PDFs
    """
    # First, standardize line endings and clean any existing HTML
    text = text.replace('\r\n', '\n')
    text = re.sub(r'<[^>]+>', '', text)
    
    # Create a dictionary to store parsed sections with their formatting
    parsed_sections = []
    
    # Process headers first (important to do this before other formatting)
    lines = text.split('\n')
    current_paragraph = []
    
    for line in lines:
        line = line.rstrip()
        
        # Skip empty lines but add them as paragraph separators
        if not line.strip():
            if current_paragraph:
                parsed_sections.append({
                    'type': 'paragraph',
                    'content': ' '.join(current_paragraph),
                    'format': 'normal'
                })
                current_paragraph = []
            continue
            
        # Check for headers
        header_match = re.match(r'^(#{1,6})\s+(.+)$', line)
        if header_match:
            # Add any current paragraph first
            if current_paragraph:
                parsed_sections.append({
                    'type': 'paragraph',
                    'content': ' '.join(current_paragraph),
                    'format': 'normal'
                })
                current_paragraph = []
                
            # Add the header
            level = len(header_match.group(1))
            parsed_sections.append({
                'type': 'header',
                'content': header_match.group(2),
                'level': level
            })
            continue
            
        # Check for bullet points
        bullet_match = re.match(r'^([\*\-])\s+(.+)$', line)
        if bullet_match:
            # Add any current paragraph first
            if current_paragraph:
                parsed_sections.append({
                    'type': 'paragraph',
                    'content': ' '.join(current_paragraph),
                    'format': 'normal'
                })
                current_paragraph = []
                
            # Add the bullet point
            parsed_sections.append({
                'type': 'bullet',
                'content': bullet_match.group(2)
            })
            continue
            
        # Regular paragraph content
        current_paragraph.append(line)
    
    # Add any remaining paragraph
    if current_paragraph:
        parsed_sections.append({
            'type': 'paragraph',
            'content': ' '.join(current_paragraph),
            'format': 'normal'
        })
    
    # Process inline formatting for all sections
    for section in parsed_sections:
        content = section['content']
        
        # Process bold text
        content = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', content)
        
        # Process italic text - handling both *text* and _text_ formats
        content = re.sub(r'(?<!\*)\*([^\*]+)\*(?!\*)', r'<i>\1</i>', content)
        content = re.sub(r'_([^_]+)_', r'<i>\1</i>', content)
        
        section['content'] = content
    
    return parsed_sections

def create_clean_pdf_report(content, analysis_type, image_count):
    """
    Create a cleaner, single-page PDF report with improved formatting
    """
    # Create a unique filename
    report_id = uuid.uuid4()
    filename = f"youtube_report_{report_id}.pdf"
    filepath = os.path.join(TEMP_DIR, filename)
    
    # Create PDF document with minimal margins
    doc = SimpleDocTemplate(
        filepath,
        pagesize=letter,
        rightMargin=30,
        leftMargin=30,
        topMargin=30,
        bottomMargin=30
    )
    
    # Styles
    styles = getSampleStyleSheet()
    
    # Create custom styles optimized for a single page
    styles.add(ParagraphStyle(
        name='CompactTitle',
        parent=styles['Heading1'],
        fontSize=14,
        alignment=TA_CENTER,
        spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        name='CompactSubtitle',
        parent=styles['Heading2'],
        fontSize=8,
        alignment=TA_CENTER,
        textColor=colors.darkblue,
        spaceAfter=6
    ))
    styles.add(ParagraphStyle(
        name='Header1',
        parent=styles['Heading1'],
        fontSize=12,
        textColor=colors.darkblue,
        spaceBefore=6,
        spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        name='Header2',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=colors.darkblue,
        spaceBefore=6,
        spaceAfter=2
    ))
    styles.add(ParagraphStyle(
        name='Header3',
        parent=styles['Heading3'],
        fontSize=10,
        textColor=colors.darkblue,
        spaceBefore=4,
        spaceAfter=1
    ))
    styles.add(ParagraphStyle(
        name='CompactParagraph',
        parent=styles['Normal'],
        fontSize=9,
        spaceBefore=0,
        spaceAfter=3,
        leading=11
    ))
    styles.add(ParagraphStyle(
        name='CompactBullet',
        parent=styles['Normal'],
        fontSize=9,
        leftIndent=10,
        firstLineIndent=0,
        spaceBefore=0,
        spaceAfter=1,
        leading=11,
        bulletIndent=5
    ))
    
    # Content elements
    elements = []
    
    # Title
    title_mapping = {
        "youtube_analytics": "YouTube Analytics Insights",
        "thumbnail_analysis": "Thumbnail Analysis",
        "content_strategy": "Content Strategy Insights",
        "audience_engagement": "Audience Engagement Analysis",
        "monetization": "Monetization Insights"
    }
    title = title_mapping.get(analysis_type, "YouTube Channel Analysis")
    
    # Add title and metadata
    elements.append(Paragraph(title, styles['CompactTitle']))
    elements.append(Paragraph(f"Generated: {datetime.now().strftime('%b %d, %Y')} | {image_count} screenshots analyzed", 
                             styles['CompactSubtitle']))
    
    # Process the content with improved formatting
    try:
        # Parse markdown into structured sections
        parsed_sections = process_markdown_formatting(content)
        
        # Add each section to the PDF with proper formatting
        for section in parsed_sections:
            if section['type'] == 'header':
                # Map header level to appropriate style
                if section['level'] == 1:
                    elements.append(Paragraph(section['content'], styles['Header1']))
                elif section['level'] == 2:
                    elements.append(Paragraph(section['content'], styles['Header2']))
                else:
                    elements.append(Paragraph(section['content'], styles['Header3']))
            
            elif section['type'] == 'bullet':
                elements.append(Paragraph("• " + section['content'], styles['CompactBullet']))
            
            elif section['type'] == 'paragraph':
                elements.append(Paragraph(section['content'], styles['CompactParagraph']))
        
        # If no sections were processed, fall back to simple formatting
        if len(elements) <= 2:  # Only title and subtitle
            fallback_content = content.replace('**', '<b>').replace('**', '</b>')
            fallback_content = fallback_content.replace('*', '<i>').replace('*', '</i>')
            elements.append(Paragraph(fallback_content, styles['CompactParagraph']))
    
    except Exception as e:
        # Fallback to simple text if there's an error in processing
        print(f"Error processing content: {str(e)}")
        print("Using fallback formatting")
        
        # Strip all HTML/markdown and use plain text
        plain_text = re.sub(r'<[^>]+>', '', content)
        plain_text = re.sub(r'[*#_]+', '', plain_text)
        
        # Split into paragraphs
        paragraphs = plain_text.split('\n\n')
        for para in paragraphs:
            if para.strip():
                elements.append(Paragraph(para.strip(), styles['CompactParagraph']))
    
    # Build the PDF
    doc.build(elements)
    
    return filepath

def rag_chatbot_response(query, images, metadata, analysis_type, api_key):
    """
    Implement RAG approach to answer queries based on YouTube analytics images
    """
    # Configure the API
    genai.configure(api_key=api_key)

    # Create a model instance
    model = genai.GenerativeModel('gemini-2.0-flash')
    
    # Safely format dates from metadata
    start_date = "various dates"
    end_date = "present"
    
    if metadata and len(metadata) > 0:
        if metadata[0].get('timestamp'):
            timestamp = metadata[0].get('timestamp')
            # Handle timestamp whether it's a datetime object or string
            if hasattr(timestamp, 'strftime'):
                start_date = timestamp.strftime('%Y-%m-%d')
            else:
                start_date = str(timestamp)
                
        if metadata[-1].get('timestamp'):
            timestamp = metadata[-1].get('timestamp')
            # Handle timestamp whether it's a datetime object or string
            if hasattr(timestamp, 'strftime'):
                end_date = timestamp.strftime('%Y-%m-%d')
            else:
                end_date = str(timestamp)
    
    # Create context-aware RAG prompt with modified response style
    rag_prompt = f"""You are a YouTube Analytics Expert Assistant trained to analyze YouTube analytics data from screenshots.

I'm showing you {len(images)} YouTube analytics screenshots from my channel as your knowledge base.

USER QUERY: "{query}"

RESPONSE STYLE: Begin your response with "Based on data..." and then directly provide insights. Do NOT use phrases like "Based on the screenshot provided" or similar introductions.

Based EXCLUSIVELY on the data visible in these screenshots, provide a detailed, accurate answer to my query.
If the screenshots don't contain sufficient information to answer fully, explain:
1. What relevant information IS visible in the screenshots
2. What specific additional data would be needed for a complete answer

Guidelines:
• Only reference metrics, trends, and patterns that are actually visible in the screenshots
• Cite specific numbers and data points you can see
• Be precise about which screenshots contain relevant information
• Format your response with headers, bullet points, and emphasis for key insights
• Provide actionable recommendations when appropriate
• Be honest about limitations of the available data

If the data spans a time period, note that the screenshots cover from {start_date} to {end_date}.
"""
    
    # Create request with prompt and all images
    request_parts = [rag_prompt] + images + [query]
    
    # Generate content
    response = model.generate_content(request_parts)
    
    return response.text 