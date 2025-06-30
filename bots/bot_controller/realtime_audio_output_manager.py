import logging
import queue
import threading
import time

import numpy as np

logger = logging.getLogger(__name__)


class RealtimeAudioOutputManager:
    def __init__(self, play_raw_audio_callback, sleep_time_between_chunks_seconds, output_sample_rate):
        self.play_raw_audio_callback = play_raw_audio_callback
        self.sleep_time_between_chunks_seconds = sleep_time_between_chunks_seconds

        self.audio_queue = queue.Queue()
        self.audio_thread = None
        self.stop_audio_thread = False
        self.last_chunk_time = None
        self.thread_lock = threading.Lock()

        self.output_sample_rate = output_sample_rate
        self.bytes_per_sample = 2
        self.chunk_length_seconds = 0.1
        self.inner_chunk_buffer = b""
        self.last_chunk_time = time.time()

    def add_chunk(self, chunk, sample_rate):
        # If it's been a while since we had a chunk, there's probably some "residue" in the buffer. Clear it.
        if time.time() - self.last_chunk_time > 0.15:
            self.inner_chunk_buffer = b""
        self.last_chunk_time = time.time()

        self.inner_chunk_buffer += chunk
        chunk_size_bytes = int(self.bytes_per_sample * self.chunk_length_seconds * sample_rate)
        while len(self.inner_chunk_buffer) >= chunk_size_bytes:
            self.add_chunk_inner(self.inner_chunk_buffer[:chunk_size_bytes], sample_rate)
            self.inner_chunk_buffer = self.inner_chunk_buffer[chunk_size_bytes:]

    def add_chunk_inner(self, chunk, sample_rate):
        """Add a single chunk of PCM audio to the stream buffer."""
        self.audio_queue.put((chunk, sample_rate))
        self.last_chunk_time = time.time()

        # If thread is alive, we don't need to mess with the lock
        if not (self.audio_thread is None or not self.audio_thread.is_alive()):
            return

        # Start audio thread if not already running
        with self.thread_lock:
            if self.audio_thread is None or not self.audio_thread.is_alive():
                self._start_audio_thread()
                logger.info("RealtimeAudioOutputManager: Audio thread started")

    def _start_audio_thread(self):
        """Start the audio output thread."""
        self.stop_audio_thread = False
        self.audio_thread = threading.Thread(target=self._process_audio_queue, daemon=True)
        self.audio_thread.start()

    def _process_audio_queue(self):
        """Process audio chunks from the queue until timeout or stop signal."""
        timeout_seconds = 10

        while not self.stop_audio_thread:
            try:
                # Wait for audio chunk with timeout
                chunk, sample_rate = self.audio_queue.get(timeout=1.0)

                # Upsample the chunk to the output sample rate
                chunk_upsampled, chunk_upsampled_sample_rate = self.upsample_chunk_to_output_sample_rate(chunk, sample_rate)

                # Play the chunk
                self.play_raw_audio_callback(bytes=chunk_upsampled, sample_rate=chunk_upsampled_sample_rate)

                # Sleep between chunks
                time.sleep(self.sleep_time_between_chunks_seconds * self.chunk_length_seconds)

            except queue.Empty:
                # Check if we should timeout due to no new chunks
                if self.last_chunk_time and time.time() - self.last_chunk_time > timeout_seconds:
                    break
                continue

        logger.info("RealtimeAudioOutputManager: Audio thread exited")

    def upsample_chunk_to_output_sample_rate(self, chunk, sample_rate):
        # If sample rates are the same, no upsampling needed
        if sample_rate == self.output_sample_rate:
            return chunk, sample_rate

        # Calculate upsampling ratio
        ratio = self.output_sample_rate // sample_rate

        # We can't upsample if the ratio is not an integer
        if self.output_sample_rate % sample_rate != 0 or ratio <= 1:
            return chunk, sample_rate

        # Convert bytes to 16-bit samples (assuming 16-bit PCM)
        samples = np.frombuffer(chunk, dtype=np.int16)

        # Repeat each sample 'ratio' times (e.g., [1,2,3] -> [111,222,333])
        upsampled_samples = np.repeat(samples, ratio)

        # Convert back to bytes
        return upsampled_samples.tobytes(), self.output_sample_rate

    def cleanup(self):
        """Stop the audio output thread and clear the queue."""
        self.stop_audio_thread = True

        # Clear the queue
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except queue.Empty:
                break

        # Wait for thread to finish
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join()
