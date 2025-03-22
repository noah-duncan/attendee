# How To Guides for Attendee

This document provides step-by-step guides for common operations with the Attendee application.

## Table of Contents

1. [How to Get a Bot to Join a Meeting](#how-to-get-a-bot-to-join-a-meeting)
2. [How to Make a Bot Speak in a Meeting](#how-to-make-a-bot-speak-in-a-meeting)
3. [How to Retrieve Meeting Transcripts](#how-to-retrieve-meeting-transcripts)
4. [How to Monitor Bot Status](#how-to-monitor-bot-status)
5. [How to Make a Bot Leave a Meeting](#how-to-make-a-bot-leave-a-meeting)
6. [How to Set Up Your Development Environment](#how-to-set-up-your-development-environment)
7. [How to Obtain Required API Keys](#how-to-obtain-required-api-keys)
8. [How to Self-Host the Attendee Application](#how-to-self-host-the-attendee-application)
9. [How to Troubleshoot Common Issues](#how-to-troubleshoot-common-issues)

## How to Get a Bot to Join a Meeting

To add a bot to a Zoom or Google Meet meeting:

1. Ensure you have your API key ready (found in the Attendee UI under 'API Keys')
2. Make a POST request to the `/bots` endpoint:

```bash
curl -X POST https://app.attendee.dev/api/v1/bots \
-H 'Authorization: Token YOUR_API_KEY_HERE' \
-H 'Content-Type: application/json' \
-d '{
  "meeting_url": "https://us05web.zoom.us/j/84315220467?pwd=9M1SQg2Pu2l0cB078uz6AHeWelSK19.1", 
  "bot_name": "My Bot"
}'
```

3. Save the bot ID from the response for future reference:

```json
{
  "id": "bot_3hfP0PXEsNinIZmh",
  "meeting_url": "https://us05web.zoom.us/j/84315220467?pwd=9M1SQg2Pu2l0cB078uz6AHeWelSK19.1",
  "state": "joining",
  "transcription_state": "not_started"
}
```

## How to Make a Bot Speak in a Meeting

To make your bot speak during an active meeting:

1. Use the bot ID from when you created the bot
2. Send a POST request to the `/bots/{id}/speech` endpoint:

```bash
curl -X POST https://app.attendee.dev/api/v1/bots/bot_3hfP0PXEsNinIZmh/speech \
-H 'Authorization: Token YOUR_API_KEY_HERE' \
-H 'Content-Type: application/json' \
-d '{
  "text": "Hello everyone, I am a meeting bot.",
  "text_to_speech_settings": {
    "google": {
      "voice_language_code": "en-US",
      "voice_name": "en-US-Casual-K"
    }
  }
}'
```

3. The bot will speak the provided text in the meeting using the specified voice settings

## How to Retrieve Meeting Transcripts

To get transcripts of a meeting:

1. Check that the meeting has ended and transcription is complete:

```bash
curl -X GET https://app.attendee.dev/api/v1/bots/bot_3hfP0PXEsNinIZmh \
-H 'Authorization: Token YOUR_API_KEY_HERE' \
-H 'Content-Type: application/json'
```

Look for:
```json
{
  "state": "ended",
  "transcription_state": "complete"
}
```

2. Retrieve the full transcript:

```bash
curl -X GET https://app.attendee.dev/api/v1/bots/bot_3hfP0PXEsNinIZmh/transcript \
-H 'Authorization: Token YOUR_API_KEY_HERE' \
-H 'Content-Type: application/json'
```

3. You can also retrieve partial transcripts while the meeting is still in progress using the same endpoint

## How to Monitor Bot Status

To check the current status of your bot:

1. Use the GET endpoint with your bot's ID:

```bash
curl -X GET https://app.attendee.dev/api/v1/bots/bot_3hfP0PXEsNinIZmh \
-H 'Authorization: Token YOUR_API_KEY_HERE' \
-H 'Content-Type: application/json'
```

2. The response will include:
   - `state`: The bot's current state in the meeting (joining, joined_recording, ended, etc.)
   - `transcription_state`: The current state of transcription (not_started, in_progress, complete)

3. Common bot states:
   - `joining`: Bot is attempting to join the meeting
   - `joined`: Bot has successfully joined the meeting
   - `joined_recording`: Bot is in the meeting and recording
   - `errored`: Bot encountered an error
   - `ended`: Bot has left the meeting or the meeting has ended

## How to Make a Bot Leave a Meeting

To make your bot leave a meeting:

1. Use the bot ID and send a POST request to the leave endpoint:

```bash
curl -X POST https://app.attendee.dev/api/v1/bots/bot_3hfP0PXEsNinIZmh/leave \
-H 'Authorization: Token YOUR_API_KEY_HERE' \
-H 'Content-Type: application/json'
```

2. The bot will disconnect from the meeting
3. You can verify the bot has left by checking its status to confirm `state` is `ended`

## How to Set Up Your Development Environment

To set up a local development environment:

1. Clone the repository:
```bash
git clone https://github.com/your-username/attendee.git
cd attendee
```

2. Build the Docker image:
```bash
docker compose -f dev.docker-compose.yaml build
```

3. Create local environment variables:
```bash
docker compose -f dev.docker-compose.yaml run --rm attendee-app-local python init_env.py > .env
```

4. Edit the `.env` file and enter your AWS information

5. Start all services:
```bash
docker compose -f dev.docker-compose.yaml up
```

6. In a separate terminal tab, run migrations:
```bash
docker compose -f dev.docker-compose.yaml exec attendee-app-local python manage.py migrate
```

7. Navigate to `localhost:8000` in your browser and create an account

8. Find the confirmation link in the terminal logs (looks like `http://localhost:8000/accounts/confirm-email/<key>/`) and open it in your browser

9. Log in and obtain your API key from the 'API Keys' section

## How to Obtain Required API Keys

### Zoom OAuth Credentials

1. Navigate to [Zoom Marketplace](https://marketplace.zoom.us/) and log in
2. Click "Develop" at the top-right, then "Build App" and choose "General App"
3. Copy the Client ID and Client Secret from the 'App Credentials' section
4. Go to the Embed tab on the left navigation bar under Features
5. Select the Meeting SDK toggle to enable it
6. Enter these credentials in the Attendee UI 'Settings' section

### Deepgram API Key

1. Sign up for a free account at [Deepgram](https://console.deepgram.com/signup)
2. Navigate to the API Keys section in the Deepgram console
3. Create a new API key with appropriate permissions
4. Copy the API key and enter it in the Attendee UI 'Settings' section

## How to Self-Host the Attendee Application

To self-host Attendee in a production environment:

1. Make sure you have Docker installed on your server

2. Clone the repository:
```bash
git clone https://github.com/your-username/attendee.git
cd attendee
```

3. Follow the development setup steps, but modify the `.env` file with production values

4. For production, consider using:
   - A reverse proxy like Nginx for SSL termination
   - Persistent storage for database volumes
   - A proper database backup strategy
   - Monitoring and logging solutions

5. Set up proper security measures, including:
   - Firewall rules
   - Regular updates
   - Restricted access to the server

## How to Troubleshoot Common Issues

### Bot Can't Join the Meeting

1. Verify your Zoom OAuth credentials are correct and properly configured
2. Check that the meeting URL is valid and the meeting is active
3. Check the server logs for specific error messages

### Transcription Issues

1. Verify your Deepgram API key is valid and properly configured
2. Ensure the bot has successfully joined the meeting and is in the `joined_recording` state
3. Check network connectivity between your Attendee instance and Deepgram
4. Review the transcription logs for specific error messages

### Docker Development Environment Issues

1. Ensure Docker and Docker Compose are installed and up to date
2. Check container logs for specific error messages:
```bash
docker compose -f dev.docker-compose.yaml logs
```
4. Try rebuilding the containers if persistent issues occur:
```bash
docker compose -f dev.docker-compose.yaml down
docker compose -f dev.docker-compose.yaml build --no-cache
docker compose -f dev.docker-compose.yaml up
```
