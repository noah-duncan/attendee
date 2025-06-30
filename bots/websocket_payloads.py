import logging
import time
from base64 import b64encode

from bots.models import RealtimeBotEventTypes

logger = logging.getLogger(__name__)


import audioop
import logging

logger = logging.getLogger(__name__)

TARGET_SR = 16_000
SAMPLE_WIDTH = 2  # 16-bit PCM
CHANNELS = 1  # mono


def _downsample(chunk: bytes, src_rate: int) -> bytes:
    """
    Fast, band-limited 48 k, 32 k → 16 k converter.
    Falls back to passthrough if src_rate already 16 k.
    """
    if src_rate == TARGET_SR:
        return chunk  # nothing to do
    if src_rate % TARGET_SR:
        raise ValueError(f"Unsupported rate {src_rate}")

    # state None ⇒ filter state kept inside audioop (per-call ok for small chunks)
    converted, _ = audioop.ratecv(
        chunk,  # fragment
        SAMPLE_WIDTH,  # width
        CHANNELS,  # nchannels
        src_rate,  # inrate
        TARGET_SR,  # outrate
        None,  # state
    )
    return converted


def mixed_audio_websocket_payload(chunk: bytes, sample_rate: int, bot_object_id: str) -> dict:
    """
    Down-sample (if needed) and package for websocket.
    """
    chunk_16k = _downsample(chunk, sample_rate)

    return {
        "event_type": RealtimeBotEventTypes.type_to_api_code(RealtimeBotEventTypes.MIXED_AUDIO_CHUNK),
        "bot_id": bot_object_id,
        "event_data": {
            "chunk": b64encode(chunk_16k).decode("ascii"),
            "timestamp_ms": int(time.time() * 1000),
        },
    }
