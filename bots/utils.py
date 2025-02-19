import io

import cv2
import numpy as np
from pydub import AudioSegment

from .models import RecordingStates


def pcm_to_mp3(
    pcm_data: bytes,
    sample_rate: int = 32000,
    channels: int = 1,
    sample_width: int = 2,
    bitrate: str = "128k",
) -> bytes:
    """
    Convert PCM audio data to MP3 format.

    Args:
        pcm_data (bytes): Raw PCM audio data
        sample_rate (int): Sample rate in Hz (default: 32000)
        channels (int): Number of audio channels (default: 1)
        sample_width (int): Sample width in bytes (default: 2)
        bitrate (str): MP3 encoding bitrate (default: "128k")

    Returns:
        bytes: MP3 encoded audio data
    """
    # Create AudioSegment from raw PCM data
    audio_segment = AudioSegment(
        data=pcm_data,
        sample_width=sample_width,
        frame_rate=sample_rate,
        channels=channels,
    )

    # Create a bytes buffer to store the MP3 data
    buffer = io.BytesIO()

    # Export the audio segment as MP3 to the buffer with specified bitrate
    audio_segment.export(buffer, format="mp3", parameters=["-b:a", bitrate])

    # Get the MP3 data as bytes
    mp3_data = buffer.getvalue()
    buffer.close()

    return mp3_data


def mp3_to_pcm(mp3_data: bytes, sample_rate: int = 32000, channels: int = 1, sample_width: int = 2) -> bytes:
    """
    Convert MP3 audio data to PCM format.

    Args:
        mp3_data (bytes): MP3 audio data
        sample_rate (int): Desired sample rate in Hz (default: 32000)
        channels (int): Desired number of audio channels (default: 1)
        sample_width (int): Desired sample width in bytes (default: 2)

    Returns:
        bytes: Raw PCM audio data
    """
    # Create a bytes buffer from the MP3 data
    buffer = io.BytesIO(mp3_data)

    # Load the MP3 data into an AudioSegment
    audio_segment = AudioSegment.from_mp3(buffer)

    # Convert to the desired format
    audio_segment = audio_segment.set_frame_rate(sample_rate)
    audio_segment = audio_segment.set_channels(channels)
    audio_segment = audio_segment.set_sample_width(sample_width)

    # Get the raw PCM data
    pcm_data = audio_segment.raw_data
    buffer.close()

    return pcm_data


def calculate_audio_duration_ms(audio_data: bytes, content_type: str) -> int:
    """
    Calculate the duration of audio data in milliseconds.

    Args:
        audio_data (bytes): Audio data in either PCM or MP3 format
        content_type (str): Content type of the audio data (e.g., 'audio/mp3')

    Returns:
        int: Duration in milliseconds
    """
    buffer = io.BytesIO(audio_data)

    if content_type == "audio/mp3":
        audio = AudioSegment.from_mp3(buffer)
    else:
        raise ValueError(f"Unsupported content type for duration calculation: {content_type}")

    buffer.close()
    # len(audio) returns duration in milliseconds for pydub AudioSegment objects
    duration_ms = len(audio)
    return duration_ms


def png_to_yuv420_frame(png_bytes: bytes, width: int = 640, height: int = 360) -> bytes:
    """
    Convert PNG image bytes to YUV420 (I420) format and resize to specified dimensions.

    Args:
        png_bytes (bytes): Input PNG image as bytes
        width (int): Desired width of output frame (default: 640)
        height (int): Desired height of output frame (default: 360)

    Returns:
        bytes: YUV420 formatted frame data
    """
    # Convert PNG bytes to numpy array
    png_array = np.frombuffer(png_bytes, np.uint8)
    bgr_frame = cv2.imdecode(png_array, cv2.IMREAD_COLOR)

    # Resize the frame to desired dimensions
    bgr_frame = cv2.resize(bgr_frame, (width, height), interpolation=cv2.INTER_AREA)

    # Convert BGR to YUV420 (I420)
    yuv_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2YUV_I420)

    # Return as bytes
    return yuv_frame.tobytes()


def utterance_words(utterance, offset=0.0):
    if "words" in utterance.transcription:
        return utterance.transcription["words"]

    return [
        {
            "start": offset,
            "end": offset + utterance.duration_ms / 1000.0,
            "punctuated_word": utterance.transcription["transcript"],
            "word": utterance.transcription["transcript"],
        }
    ]


class AggregatedUtterance:
    def __init__(self, utterance):
        self.participant = utterance.participant
        self.transcription = utterance.transcription.copy()
        self.timestamp_ms = utterance.timestamp_ms
        self.duration_ms = utterance.duration_ms
        self.id = utterance.id
        self.transcription["words"] = utterance_words(utterance)

    def aggregate(self, utterance):
        self.transcription["words"].extend(utterance_words(utterance, offset=(utterance.timestamp_ms - self.timestamp_ms) / 1000.0))
        self.transcription["transcript"] += " " + utterance.transcription["transcript"]
        self.duration_ms += utterance.duration_ms


def generate_aggregated_utterances(recording):
    utterances_sorted = recording.utterances.all().order_by("timestamp_ms")

    aggregated_utterances = []
    current_aggregated_utterance = None
    for utterance in utterances_sorted:
        if not utterance.transcription:
            continue
        if not utterance.transcription.get("transcript"):
            continue

        if current_aggregated_utterance is None:
            current_aggregated_utterance = AggregatedUtterance(utterance)
        else:
            if utterance.transcription.get("words") is None and utterance.participant.id == current_aggregated_utterance.participant.id and utterance.timestamp_ms - (current_aggregated_utterance.timestamp_ms + current_aggregated_utterance.duration_ms) < 3000:
                current_aggregated_utterance.aggregate(utterance)
            else:
                aggregated_utterances.append(current_aggregated_utterance)
                current_aggregated_utterance = AggregatedUtterance(utterance)

    if current_aggregated_utterance:
        aggregated_utterances.append(current_aggregated_utterance)
    return aggregated_utterances


def generate_utterance_json_for_bot_detail_view(recording):
    utterances_data = []
    recording_first_buffer_timestamp_ms = recording.first_buffer_timestamp_ms

    aggregated_utterances = generate_aggregated_utterances(recording)
    for utterance in aggregated_utterances:
        if not utterance.transcription:
            continue
        if not utterance.transcription.get("transcript"):
            continue

        if recording_first_buffer_timestamp_ms:
            if utterance.transcription.get("words"):
                first_word_start_relative_ms = int(utterance.transcription.get("words")[0].get("start") * 1000)
            else:
                first_word_start_relative_ms = 0

            relative_timestamp_ms = utterance.timestamp_ms - recording_first_buffer_timestamp_ms + first_word_start_relative_ms
        else:
            # If we don't have a first buffer timestamp, we use the absolute timestamp
            relative_timestamp_ms = utterance.timestamp_ms

        relative_words_data = []
        if utterance.transcription.get("words"):
            if recording_first_buffer_timestamp_ms:
                utterance_start_relative_ms = utterance.timestamp_ms - recording_first_buffer_timestamp_ms
            else:
                # If we don't have a first buffer timestamp, we use the absolute timestamp
                utterance_start_relative_ms = utterance.timestamp_ms

            for word in utterance.transcription["words"]:
                relative_word = word.copy()
                relative_word["start"] = utterance_start_relative_ms + int(word["start"] * 1000)
                relative_word["end"] = utterance_start_relative_ms + int(word["end"] * 1000)
                relative_words_data.append(relative_word)

        relative_words_data_with_spaces = []
        for i, word in enumerate(relative_words_data):
            relative_words_data_with_spaces.append(
                {
                    "word": word["punctuated_word"],
                    "start": word["start"],
                    "end": word["end"],
                    "utterance_id": utterance.id,
                }
            )
            # Add space between words
            if i < len(relative_words_data) - 1:
                next_word = relative_words_data[i + 1]
                relative_words_data_with_spaces.append(
                    {
                        "word": " ",
                        "start": next_word["start"],
                        "end": next_word["start"],
                        "utterance_id": utterance.id,
                        "is_space": True,
                    }
                )

        timestamp_ms = relative_timestamp_ms if recording_first_buffer_timestamp_ms is not None else utterance.timestamp_ms
        seconds = timestamp_ms // 1000
        timestamp_display = f"{seconds // 60}:{seconds % 60:02d}"

        utterance_data = {
            "id": utterance.id,
            "participant": utterance.participant,
            "relative_timestamp_ms": relative_timestamp_ms,
            "words": relative_words_data_with_spaces,
            "transcript": utterance.transcription.get("transcript"),
            "timestamp_display": timestamp_display,
        }
        utterances_data.append(utterance_data)

    return utterances_data


def generate_recordings_json_for_bot_detail_view(bot):
    # Process recordings and utterances
    recordings_data = []
    for recording in bot.recordings.all():
        if recording.state != RecordingStates.COMPLETE:
            continue
        recordings_data.append(
            {
                "state": recording.state,
                "url": recording.url,
                "utterances": generate_utterance_json_for_bot_detail_view(recording),
            }
        )

    return recordings_data
