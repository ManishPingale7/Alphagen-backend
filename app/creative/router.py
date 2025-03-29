from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
import shutil
import os
from typing import List
import uuid
import multiprocessing
from multiprocessing import Process, Manager
import pickle
from .BeatSyncVideoGenerator import BeatSyncVideoGenerator

router = APIRouter(prefix="/creative", tags=["Creative task APIs"])

TEMP_DIR = "temp_uploads"
OUTPUT_DIR = "temp_outputs"
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

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
