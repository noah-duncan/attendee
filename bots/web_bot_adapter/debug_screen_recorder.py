import logging
import subprocess

logger = logging.getLogger(__name__)


class DebugScreenRecorder:
    def __init__(self, display_var, screen_dimensions, output_file_path):
        self.display_var = display_var
        self.screen_dimensions = screen_dimensions
        self.output_file_path = output_file_path
        self.ffmpeg_proc = None

    def start(self):
        logger.info(f"Starting debug screen recorder for display {self.display_var} with dimensions {self.screen_dimensions} and output file path {self.output_file_path}")
        ffmpeg_cmd = [
            "ffmpeg",
            "-y",
            "-thread_queue_size", "2048", # For x11grab input
            "-f", "x11grab",
            "-video_size", f"{self.screen_dimensions[0]}x{self.screen_dimensions[1]}",
            "-i", self.display_var,
            "-thread_queue_size", "1024", # For pulse input
            "-f", "pulse",
            "-i", "default",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            # Consider adding -pix_fmt yuv420p for compatibility if needed
            # "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            # You might explicitly set audio quality/bitrate if default is too high
            # "-b:a", "128k",
            self.output_file_path
        ]
        logger.info(f"Starting FFmpeg command: {' '.join(ffmpeg_cmd)}")
        self.ffmpeg_proc = subprocess.Popen(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

    def stop(self):
        if not self.ffmpeg_proc:
            return
        self.ffmpeg_proc.terminate()
        self.ffmpeg_proc.wait()
        logger.info(f"Stopped debug screen recorder for display {self.display_var} with dimensions {self.screen_dimensions} and output file path {self.output_file_path}")
