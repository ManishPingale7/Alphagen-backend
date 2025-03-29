import librosa
import numpy as np
from moviepy import *
from pydub import AudioSegment
from typing import List, Tuple, Dict


class BeatSyncVideoGenerator:
    def __init__(self, music_path: str, video_clips_paths: List[str], output_path: str, progress_callback=None):

        self.music_path = music_path
        self.video_clips_paths = video_clips_paths
        self.output_path = output_path
        self.beat_times = []
        self.hooks = []
        self.clips = []
        self.music_duration = 0
        self.progress_callback = progress_callback

    def analyze_music(self, hook_sensitivity: float = 0.5) -> List[float]:
        print(f"Analyzing music: {self.music_path}")

        audio = AudioSegment.from_file(self.music_path)
        self.music_duration = len(audio) / 1000.0  # Convert to seconds
        print(f"Music duration: {self.music_duration:.2f} seconds")

        y, sr = librosa.load(self.music_path)

        tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr)

        beat_times = librosa.frames_to_time(beat_frames, sr=sr)

        onset_env = librosa.onset.onset_strength(y=y, sr=sr)

        onset_env_norm = (onset_env - onset_env.min()) / \
            (onset_env.max() - onset_env.min())

        hook_threshold = hook_sensitivity * onset_env_norm.mean()
        hooks = []

        for i, beat_time in enumerate(beat_times):
            frame = beat_frames[i]
            if frame < len(onset_env_norm) and onset_env_norm[frame] > hook_threshold:
                hooks.append((beat_time, onset_env_norm[frame]))

        hooks.sort(key=lambda x: x[1], reverse=True)
        hooks = [h[0] for h in hooks]

        print(
            f"Detected {len(beat_times)} beats at tempo {float(tempo):.1f} BPM")

        print(f"Identified {len(hooks)} potential hooks/significant beats")

        self.beat_times = beat_times
        self.hooks = hooks
        return beat_times

    def load_video_clips(self) -> List[VideoFileClip]:
        clips = []
        for path in self.video_clips_paths:
            try:
                clip = VideoFileClip(path, audio=False)
                if clip.duration > 0:
                    clips.append(clip)
                    print(
                        f"Loaded clip: {path} (duration: {clip.duration:.2f}s)")
                else:
                    print(f"Skipping clip with zero duration: {path}")
            except Exception as e:
                print(f"Error loading clip {path}: {e}")

        if not clips:
            raise ValueError("No valid video clips were loaded")

        self.clips = clips
        return clips

    def validate_clips_and_music(self):
        if not self.music_duration:
            self.analyze_music()

        if not self.clips:
            self.load_video_clips()

        total_clips_duration = sum(clip.duration for clip in self.clips)

        if total_clips_duration < self.music_duration:
            raise ValueError(
                f"All video clips combined ({total_clips_duration:.2f}s) are shorter than the music ({self.music_duration:.2f}s). "
                f"Please provide longer or more video clips."
            )

        print(
            f"Total clips duration: {total_clips_duration:.2f}s, Music duration: {self.music_duration:.2f}s")
        print("Video clips are sufficient for the music duration.")

    def create_beat_synchronized_video(self) -> VideoFileClip:
        if not self.beat_times:
            if self.progress_callback:
                self.progress_callback("Analyzing music...", 15)
            self.analyze_music()

        if not self.clips:
            if self.progress_callback:
                self.progress_callback("Loading videos...", 25)
            self.load_video_clips()

        try:
            if self.progress_callback:
                self.progress_callback("Validating clips...", 35)
            self.validate_clips_and_music()
        except ValueError as e:
            print(f"Error: {e}")
            raise

        num_clips = len(self.clips)

        transition_points = []

        if len(self.hooks) >= num_clips:
            temp_hooks = self.hooks[:num_clips]
            sorted_hooks = sorted(temp_hooks)
            if 0 not in sorted_hooks and sorted_hooks[0] > 0:
                sorted_hooks.insert(0, 0)
            if self.music_duration not in sorted_hooks:
                sorted_hooks.append(self.music_duration)
            transition_points = sorted_hooks
        else:
            transition_points = [0]
            segment_duration = self.music_duration / num_clips
            for i in range(1, num_clips):
                transition_points.append(i * segment_duration)
            transition_points.append(self.music_duration)

        final_clips = []

        num_segments = len(transition_points) - 1
        clips_to_use = min(num_segments, len(self.clips))

        for i in range(clips_to_use):
            start_time = transition_points[i]
            end_time = transition_points[i+1]
            segment_duration = end_time - start_time

            if segment_duration <= 0:
                print(
                    f"Skipping segment with non-positive duration: {segment_duration}")
                continue

            selected_clip = self.clips[i % len(self.clips)]

            clip_copy = selected_clip.copy()

            target_resolution = (1280, 720)  # HD resolution
            clip_copy = clip_copy.resized(target_resolution)

            if clip_copy.duration > segment_duration:
                middle_point = clip_copy.duration / 2
                clip_start = max(0, middle_point - segment_duration / 2)

                try:
                    clip_segment = clip_copy.subclipped(
                        clip_start, clip_start + segment_duration)
                except Exception as e:
                    print(f"Error subclipping: {e}, trying fallback method")
                    clip_segment = clip_copy.subclipped(
                        clip_start, clip_start + segment_duration)
            else:
                repeats_needed = int(
                    np.ceil(segment_duration / clip_copy.duration))
                repeated_clips = [clip_copy] * repeats_needed

                try:
                    if self.progress_callback:
                        self.progress_callback("Rendering videos...", 50)
                    clip_segment = concatenate_videoclips(
                        repeated_clips, method='compose')
                    clip_segment = clip_segment.subclipped(0, segment_duration)
                except Exception as e:
                    print(f"Error concatenating clips: {e}")
                    clip_segment = clip_copy.set_duration(segment_duration)

            final_clips.append(clip_segment)

        if not final_clips:
            raise ValueError("No valid video segments were created")

        try:
            final_video = concatenate_videoclips(final_clips, method='compose')
        except Exception as e:
            print(
                f"Error in primary concatenation method: {e}, trying fallback")
            final_video = concatenate_videoclips(final_clips)

        if abs(final_video.duration - self.music_duration) > 0.1:  # Allow small tolerance
            print(
                f"Adjusting final video duration from {final_video.duration:.2f}s to match music: {self.music_duration:.2f}s")
            final_video = final_video.subclipped(0, self.music_duration)

        final_video = final_video.with_audio(AudioFileClip(self.music_path))

        return final_video

    def generate(self, save: bool = True) -> VideoFileClip:
        if self.progress_callback:
            self.progress_callback("Preprocessing", 10)
        final_video = self.create_beat_synchronized_video()

        if save:
            print(f"Writing output video to {self.output_path}")
            try:
                if self.progress_callback:
                    self.progress_callback("Storing video...", 60)
                final_video.write_videofile(self.output_path, codec='libx264',
                                            audio_codec='aac', fps=60)
                print(f"Successfully wrote video to {self.output_path}")
            except Exception as e:
                print(f"Error writing video file: {e}")
                # Try with different parameters
                print("Trying with different parameters...")
                final_video.write_videofile(self.output_path, codec='libx264',
                                            audio_codec='aac', fps=24, threads=1)

        final_video.close()

        for clip in self.clips:
            clip.close()

        return final_video
