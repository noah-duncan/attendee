# Realtime Audio Input and Output

Attendee supports bidirectional realtime audio streaming through websockets. You can receive audio from meetings and have your bot output audio into meetings in real-time.

## Setup

To enable realtime audio streaming, configure the `websocket_settings.audio_url` parameter when creating a bot:

```json
{
  "meeting_url": "https://meet.google.com/abc-def-ghi",
  "bot_name": "Audio Bot",
  "websocket_settings": {
    "audio_url": "wss://your-server.com/attendee-websocket"
  }
}
```

## Audio Format Specifications

### Outgoing Audio (Attendee → Your Websocket Server)

Your WebSocket server will receive messages in this format, which follows the format for webhooks.

```json
{
  "bot_id": "bot_12345abcdef",
  "trigger": "realtime_audio.mixed",
  "data": {
    "chunk": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAABACAAAGRLVEE...",
    "timestamp_ms": 1703123456789
  }
}
```

The `chunk` field is a base64-encoded 16-bit PCM audio data (16 kHz, mono).

### Incoming Audio (Your Websocket Server → Attendee)

When you want the bot to speak audio in the meeting, send a message in this format.

```json
{
  "trigger": "realtime_audio.bot_output",
  "data": {
    "chunk": "UklGRiQAAABXQVZFZm10IBAAAAABAAEAgD4AAAB9AAABACAAAGRLVEE...",
    "sample_rate": 16000
  }
}
```

The `chunk` field is a chunk of audio data in the format of 16-bit PCM audio data (16 kHz, mono). For now the only supported sample rate is 16 kHz.

## Integration with Voice Agent APIs

The realtime audio streaming can be easily integrated with voice agent APIs and services:

### Deepgram Voice Agent API
Connect directly to Deepgram's voice agent WebSocket API by forwarding audio chunks. The 16 kHz PCM format is compatible with Deepgram's real-time streaming requirements.

### OpenAI Realtime API
Connect directly to OpenAI's realtime API by forwarding audio chunks. The 16 kHz PCM format is compatible with OpenAI's real-time streaming requirements.


## Retries on Websocket Connections

Attendee will automatically retry to connect to your websocket server if the connection is lost or the initial connection attempt fails. We will retry up to 30 times with a 2 second delay between retries.



