import logging
import os
import subprocess

logger = logging.getLogger(__name__)


class ScreenAndAudioRecorder:
    def __init__(self, file_location, recording_dimensions):
        self.file_location = file_location
        self.ffmpeg_proc = None
        # Keeping recording_dimensions parameter for interface compatibility
        # but it won't be used for audio-only recording
        self.recording_dimensions = recording_dimensions

    def start_recording(self, display_var):
        # display_var parameter kept for interface compatibility but not used
        logger.info(f"Starting audio recorder with file location {self.file_location}")
        
        # FFmpeg command for audio-only recording to MP3
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",  # Overwrite output file without asking
            "-thread_queue_size", "4096",
            "-f", "alsa",  # Audio input format for Linux
            "-i", "default",  # Default audio input device
            "-c:a", "libmp3lame",  # MP3 codec
            "-b:a", "192k",  # Audio bitrate (192 kbps for good quality)
            "-ar", "44100",  # Sample rate
            "-ac", "2",  # Stereo
            self.file_location
        ]

        logger.info(f"Starting FFmpeg command: {' '.join(ffmpeg_cmd)}")
        self.ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    def stop_recording(self):
        if not self.ffmpeg_proc:
            return
        self.ffmpeg_proc.terminate()
        self.ffmpeg_proc.wait()
        self.ffmpeg_proc = None
        logger.info(f"Stopped audio recorder with file location {self.file_location}")

    def get_seekable_path(self, path):
        """
        Transform a file path to include '.seekable' before the extension.
        Example: /tmp/file.mp3 -> /tmp/file.seekable.mp3
        """
        base, ext = os.path.splitext(path)
        return f"{base}.seekable{ext}"

    def cleanup(self):
        input_path = self.file_location

        # Check if input file exists
        if not os.path.exists(input_path):
            logger.info(f"Input file does not exist at {input_path}, creating empty file")
            with open(input_path, "wb"):
                pass  # Create empty file
            return

        # MP3 files don't typically need seekability fixes like video files do
        # The moov atom issue is specific to MP4/MOV containers
        # So we can skip the seekability process for MP3 files
        logger.info(f"Audio file cleanup complete for {input_path}")

    def make_file_seekable(self, input_path, tempfile_path):
        """
        MP3 files are inherently seekable, so this method is kept for interface compatibility
        but doesn't need to do anything for MP3 files.
        """
        logger.info(f"MP3 files are already seekable, skipping: {input_path}")
        # No processing needed for MP3 files