# Basics of Bots

## What is a bot?
In the Attendee platform, a bot is an automated participant that can join virtual meetings across different platforms (Zoom, Google Meet, Microsoft Teams) to perform various tasks such as recording and transcription.

## Bot Capabilities

1. Meeting Participation: Bots can join meetings as virtual participants
2. Recording: Bots can record audio and video from meetings
3. Transcription: Bots can transcribe meeting conversations in real-time or after the meeting ends
4. RTMP Streaming: Bots can stream meeting content to RTMP destinations

## Bot States
Bots go through these lifecycle states:

1. Ready: Initial state when bot is created
2. Joining: Bot is attempting to join meeting
3. Joined - Not Recording: Bot has joined but isn't recording
4. Joined - Recording: Bot has joined and is recording
5. Leaving: Bot is leaving the meeting
6. Post Processing: Bot is processing recordings
7. Fatal Error: Bot encountered an unrecoverable error
8. Waiting Room: Bot is in meeting's waiting room
9. Ended: Bot has completed all tasks and recordings are available for download

## Recording States
- not_started: Recording hasn't begun
- in_progress: Currently recording
- complete: Recording finished and processed
- failed: Recording failed

## Transcription States
- not_started: Transcription hasn't begun
- in_progress: Currently transcribing
- complete: Transcription finished
- failed: Transcription failed

## Transcription Features
1. Non-realtime and realtime transcription (via Deepgram)
2. Multiple language support
3. Automatic language detection
4. Speaker identification with UUID tracking
5. Precise timestamps for each utterance

## Configuration Options
Bots can be configured with:

1. Transcription Settings
   - Language selection
   - Automatic language detection
   - Deepgram-specific options

2. Recording Settings
   - Recording type (Audio and Video / Audio Only)
   - Recording view (Speaker View / Gallery View)
3. RTMP Streaming Settings
   - Destination URL (must start with rtmp:// or rtmps://)
   - Stream key

## Platform Support
Currently supported platforms:
1. Zoom
2. Google Meet
3. Microsoft Teams

## Valid Pipeline Configurations
Bots support these specific configurations:

1. Basic meeting bot:
   - Record audio
   - Record video
   - Transcribe audio

2. RTMP streaming bot:
   - Stream audio
   - Stream video
   - Transcribe audio

3. Voice agent:
   - Transcribe audio only

## Best Practices
1. Always check bot state before requesting operations
2. Monitor transcription and recording states separately
3. Wait for the bots to have and "ended" status before accessing recordings