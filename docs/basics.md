# What is a bot?

In the Attendee platform, a bot is an automated participant that can join virtual meetings across different platforms (Zoom, Google Meet, Microsoft Teams) to perform various tasks such as recording and transcription.


# Bot Capabilities

1. Meeting Participation: Bots can join meetings as virtual participants.
2. Recording: Bots can record audio and video from meetings.
3. Transcription: Bots can transcribe meeting conversations in real-time or after the meeting ends.
4. Auto-leave Functionality: Bots can automatically leave meetings when it is done.


# Bot Lifecycle
Bots go through a defined lifecycle with distinct states:

1. Ready: Initial state when a bot is created but hasn't joined a meeting. 
2. Joining: Bot is in the process of joining a meeting.
3. Joined - Not Recording: Bot has joined the meeting but is not recording.
4. Joined - Recording: Bot has joined the meeting and is recording.
5. Leaving: Bot is in the process of leaving the meeting.
6. Post Processing: Bot has left the meeting and is processing recordings.
7. Fatal Error: Bot encountered an error that prevented it from functioning properly. 
8. Waiting Room: Bot is placed in a meeting's waiting room. 
9. Ended: Bot has completed all tasks and terminated.

# Platform Support
Bots are designed to work with multiple virtual meeting platforms:

1. Zoom
2. Google Meet
3. Microsoft Teams