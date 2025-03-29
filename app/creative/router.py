from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Body, Request
from fastapi.responses import FileResponse
import shutil
import os
from typing import List, Optional
import uuid
import multiprocessing
from multiprocessing import Process, Manager
import pickle 
from pydantic import BaseModel
from .BeatSyncVideoGenerator import BeatSyncVideoGenerator
from groq import Groq
from dotenv import load_dotenv
import json
import re
import random
from datetime import datetime, timedelta
from gradio_client import Client
import requests
from fastapi.staticfiles import StaticFiles

# Add imports for MusicGen
from audiocraft.models import musicgen
import time

load_dotenv()

router = APIRouter(prefix="/creative", tags=["Creative task APIs"])
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

TEMP_DIR = "temp_uploads"
OUTPUT_DIR = "temp_outputs"
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Create directory for storing generated images
os.makedirs("static/thumbnails", exist_ok=True)

# Using a simple file-based storage for job status
# This avoids multiprocessing Manager issues on Windows
class JobStorage:
    @staticmethod
    def _get_job_path(job_id):
        return os.path.join(TEMP_DIR, f"{job_id}_status.pkl")
        
    @staticmethod
    def save_job(job_id, job_data):
        with open(JobStorage._get_job_path(job_id), 'wb') as f:
            pickle.dump(job_data, f)
            
    @staticmethod
    def load_job(job_id):
        try:
            with open(JobStorage._get_job_path(job_id), 'rb') as f:
                return pickle.load(f)
        except FileNotFoundError:
            return None
            
    @staticmethod
    def delete_job(job_id):
        try:
            os.remove(JobStorage._get_job_path(job_id))
        except FileNotFoundError:
            pass

class VideoJob:
    def __init__(self, job_id: str):
        self.job_id = job_id
        self.status = "processing"
        self.progress = 0
        self.output_path = None
        self.error = None
        self.progress_messages = []


async def save_upload_file(upload_file: UploadFile, destination: str):
    try:
        with open(destination, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
    finally:
        upload_file.file.close()


def process_videos_worker(job_id: str, music_file: str, video_files: List[str]):
    """Separate process function for video processing"""
    try:
        # Load job from storage
        job = JobStorage.load_job(job_id)
        job.status = "processing"
        output_path = os.path.join(OUTPUT_DIR, f"{job_id}.mp4")
        
        # Save initial state
        JobStorage.save_job(job_id, job)

        def progress_callback(stage: str, progress: float):
            # Load current job state
            job = JobStorage.load_job(job_id)
            job.progress = progress
            job.progress_messages.append(f"{stage}: {progress}%")
            # Save updated state
            JobStorage.save_job(job_id, job)

        # Create BeatSyncVideoGenerator instance
        generator = BeatSyncVideoGenerator(
            music_path=music_file,
            video_clips_paths=video_files,
            output_path=output_path,
            progress_callback=progress_callback
        )

        # Generate the video
        generator.generate()

        # Update job status
        job = JobStorage.load_job(job_id)
        job.status = "completed"
        job.progress = 100
        job.output_path = output_path
        job.progress_messages.append("Video generation completed")
        JobStorage.save_job(job_id, job)

    except Exception as e:
        # Update job with error
        job = JobStorage.load_job(job_id)
        job.status = "failed"
        job.error = str(e)
        job.progress = 0
        JobStorage.save_job(job_id, job)
        
        # Clean up files
        for file in video_files + [music_file]:
            if os.path.exists(file):
                os.remove(file)


@router.post("/sync-videos")
async def create_sync_video(music: UploadFile = File(...), videos: List[UploadFile] = File(...)):
    # Generate unique job ID
    job_id = str(uuid.uuid4())

    try:
        # Create job directory
        job_dir = os.path.join(TEMP_DIR, job_id)
        os.makedirs(job_dir, exist_ok=True)

        # Save music file
        music_path = os.path.join(job_dir, "music.mp3")
        await save_upload_file(music, music_path)

        # Save video files
        video_paths = []
        for i, video in enumerate(videos):
            video_path = os.path.join(job_dir, f"video_{i}.mp4")
            await save_upload_file(video, video_path)
            video_paths.append(video_path)

        # Create job tracking object
        job = VideoJob(job_id)
        JobStorage.save_job(job_id, job)

        # Start processing in a completely separate process
        p = Process(
            target=process_videos_worker,
            args=(job_id, music_path, video_paths)
        )
        p.daemon = True  # Daemonize the process
        p.start()

        return {"job_id": job_id, "message": "Processing started"}

    except Exception as e:
        # Clean up on error
        if os.path.exists(job_dir):
            shutil.rmtree(job_dir)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{job_id}")
async def get_job_status(job_id: str):
    job = JobStorage.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    return {
        "status": job.status,
        "progress": job.progress,
        "progress_messages": job.progress_messages,
        "error": job.error
    }


@router.get("/download/{job_id}")
async def download_video(job_id: str):
    job = JobStorage.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Video not ready")

    if not job.output_path or not os.path.exists(job.output_path):
        raise HTTPException(status_code=404, detail="Output file not found")

    return FileResponse(
        job.output_path,
        media_type="video/mp4",
        filename=f"synced_video_{job_id}.mp4"
    )


@router.delete("/cleanup/{job_id}")
async def cleanup_job(job_id: str):
    job = JobStorage.load_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Clean up temporary files
    job_dir = os.path.join(TEMP_DIR, job_id)
    if os.path.exists(job_dir):
        shutil.rmtree(job_dir)

    if job.output_path and os.path.exists(job.output_path):
        os.remove(job.output_path)

    JobStorage.delete_job(job_id)
    return {"message": "Cleanup completed"}


# Define request and response models
class ThumbnailRequest(BaseModel):
    video_title: str
    video_description: Optional[str] = ""
    style: Optional[str] = "Modern, Professional"

class ThumbnailResponse(BaseModel):
    image_url: str
    title_text: str
    subtitle_text: Optional[str] = ""
    download_url: str

def get_ist_time():
    utc_time = datetime.utcnow()
    ist_time = utc_time + timedelta(hours=5, minutes=30)
    return ist_time.strftime("%d-%m-%Y %H:%M:%S IST")

def clean_json(json_str: str) -> str:
    """Clean JSON string to fix common formatting issues."""
    cleaned = re.sub(r',\s*([\]}])', r'\1', json_str)
    return cleaned

@router.post("/thumbnail")
async def generate_thumbnail(request: ThumbnailRequest, req: Request):
    """
    Generate a thumbnail based on video title, description and style.
    """
    try:
        temperature = round(random.uniform(0.4, 0.8), 2)
        print(f"Temperature: {temperature}")
        
        prompt = (
            f"Act as a professional YouTube thumbnail designer. Create a compelling, high-quality thumbnail "
            f"for a video with the following details:\n\n"
            f"Video Title: {request.video_title}\n"
            f"Video Description: {request.video_description}\n"
            f"Style: {request.style}\n\n"
            f"Remember that Stable Diffusion cannot render text natively, so focus on creating a visually "
            f"striking scene description. Return the thumbnail details in the following JSON format:\n\n"
            "{\n"
            '  "imagePrompt": "detailed visual description for the thumbnail image without text",\n'
            '  "titleText": "catchy title text for the thumbnail (keep it short, 3-5 words)",\n'
            '  "subtitleText": "optional subtitle or tagline (if needed)"\n'
            "}\n\n"
            "Strictly reply with ONLY the JSON, no additional text."
        )
        
        completion = client.chat.completions.create(
            model="deepseek-r1-distill-llama-70b",
            messages=[
                {"role": "system", "content": "You are a professional thumbnail designer who creates eye-catching, high-quality thumbnails for YouTube videos."},
                {"role": "user", "content": prompt}
            ],
            temperature=temperature,
            max_completion_tokens=1000,
            top_p=0.95,
            stream=False,
            reasoning_format="raw"
        )
        
        response_text = completion.choices[0].message.content
        
        # Try to extract JSON from triple-backticks
        match = re.search(r'```(?:json)?\s*([\s\S]*?)\s*```', response_text, re.DOTALL)
        if match:
            json_str = match.group(1).strip()
        else:
            # Fallback: extract the substring starting at the first '{' and ending at the last '}'
            json_start = response_text.find('{')
            json_end = response_text.rfind('}')
            if json_start != -1 and json_end != -1:
                json_str = response_text[json_start:json_end+1]
            else:
                raise HTTPException(status_code=500, detail="Failed to find JSON structure in the LLM response")
        
        cleaned_json_str = clean_json(json_str)
        
        try:
            thumbnail_data = json.loads(cleaned_json_str)
        except json.JSONDecodeError as e:
            # More advanced cleaning attempt for difficult JSON cases
            try:
                # Try to fix common JSON formatting issues
                fixed_json_str = re.sub(r',\s*}', '}', cleaned_json_str)
                fixed_json_str = re.sub(r',\s*]', ']', fixed_json_str)
                thumbnail_data = json.loads(fixed_json_str)
            except json.JSONDecodeError:
                raise HTTPException(status_code=500, detail=f"JSON parsing error: {str(e)}")
        
        print("Thumbnail Generated for:", request.video_title)
        print("Generated on:", get_ist_time())
        print("Image Prompt:", thumbnail_data['imagePrompt'])
        print("Title Text:", thumbnail_data['titleText'])
        print("Subtitle Text:", thumbnail_data.get('subtitleText', ''))
        
        # Generate a unique filename for the thumbnail
        file_id = str(uuid.uuid4())
        output_path = f"static/thumbnails/{file_id}.webp"
        
        # Use Stable Cascade for image generation
        stable_cascade_client = Client("multimodalart/stable-cascade")
        
        # Enhance the prompt for better thumbnail quality
        enhanced_prompt = f"High quality YouTube thumbnail, professional photography, {thumbnail_data['imagePrompt']}, high resolution, detailed, vibrant colors, eye-catching, 4K"
        
        # Generate the image
        result = stable_cascade_client.predict(
            prompt=enhanced_prompt,
            negative_prompt="text, watermark, logo, blurry, low quality, amateur, distorted faces",
            seed=random.randint(1, 999999),
            width=1536,
            height=864,  # 16:9 aspect ratio
            prior_num_inference_steps=20,
            prior_guidance_scale=4,
            decoder_num_inference_steps=10,
            decoder_guidance_scale=0,
            num_images_per_prompt=1,
            api_name="/run"
        )
        
        # Debug the result
        print(f"Stable Cascade result: {result}")
        
        # Handle the result from Stable Cascade correctly - both single string and list formats
        if result:
            # If result is a string (direct file path)
            if isinstance(result, str):
                temp_file_path = result
            # If result is a list of strings (multiple file paths)
            elif isinstance(result, list) and len(result) > 0:
                temp_file_path = result[0]
            else:
                raise HTTPException(status_code=500, detail=f"Unexpected result format: {type(result)}")
            
            print(f"Temporary file path: {temp_file_path}")
            
            # Check if the file exists at the temporary location
            if os.path.exists(temp_file_path):
                # Copy the file to our static directory
                shutil.copy2(temp_file_path, output_path)
                print(f"Image copied from {temp_file_path} to {output_path}")
            else:
                raise HTTPException(status_code=500, detail=f"Generated file not found at {temp_file_path}")
        else:
            raise HTTPException(status_code=500, detail="No result returned from image generation")
        
        # Get base URL from request
        base_url = str(req.base_url).rstrip('/')
        
        # Create URLs for viewing and downloading
        view_url = f"{base_url}/static/thumbnails/{file_id}.webp"
        download_url = f"{base_url}/creative/download/{file_id}"
        
        return {
            "title_text": thumbnail_data['titleText'],
            "subtitle_text": thumbnail_data.get('subtitleText', ''),
            "image_url": view_url,
            "download_url": download_url,
            "file_id": file_id
        }
        
    except Exception as e:
        print(f"Error generating thumbnail: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error generating thumbnail: {str(e)}")

@router.get("/download/{file_id}")
async def download_thumbnail(file_id: str):
    """
    Download a generated thumbnail by file ID.
    """
    # Validate the file ID to prevent directory traversal attacks
    if not re.match(r'^[0-9a-f-]+$', file_id):
        raise HTTPException(status_code=400, detail="Invalid file ID format")
    
    file_path = f"static/thumbnails/{file_id}.webp"
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Image not found")
    
    return FileResponse(
        path=file_path, 
        media_type="image/webp",
        filename=f"thumbnail-{file_id}.webp",
        headers={"Content-Disposition": f"attachment; filename=thumbnail-{file_id}.webp"}
    )

