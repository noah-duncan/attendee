import json

from google.cloud import texttospeech

from bots.models import Credentials


def generate_audio_from_text(bot, text, settings, sample_rate):
    """
    Generate audio from text using text-to-speech settings.

    Args:
        bot (Bot): The bot instance
        text (str): The text to convert to speech
        settings (dict): Text-to-speech configuration settings containing:
            google:
                voice_language_code (str): Language code (e.g., "en-US")
                voice_name (str): Name of the voice to use
        sample_rate (int): The sample rate in Hz
    Returns:
        tuple: (bytes, int) containing:
            - Audio data in LINEAR16 format
            - Duration in milliseconds
    """

    # Additional providers will be added, for now we only support Google TTS
    google_tts_credentials = bot.project.credentials.filter(credential_type=Credentials.CredentialTypes.GOOGLE_TTS).first()

    if not google_tts_credentials:
        raise ValueError("Could not find Google Text-to-Speech credentials.")

    try:
        # Create client with credentials
        client = texttospeech.TextToSpeechClient.from_service_account_info(json.loads(google_tts_credentials.get_credentials().get("service_account_json", {})))
    except (ValueError, json.JSONDecodeError) as e:
        raise ValueError("Invalid Google Text-to-Speech credentials format: " + str(e)) from e
    except Exception as e:
        raise ValueError("Failed to initialize Google Text-to-Speech client: " + str(e)) from e

    # Set up text input
    synthesis_input = texttospeech.SynthesisInput(text=text)

    # Get Google settings
    google_settings = settings.get("google", {})
    language_code = google_settings.get("voice_language_code")
    voice_name = google_settings.get("voice_name")

    # Build voice parameters
    voice = texttospeech.VoiceSelectionParams(language_code=language_code, name=voice_name)

    # Configure audio output as PCM (LINEAR16)
    audio_config = texttospeech.AudioConfig(
        audio_encoding=texttospeech.AudioEncoding.LINEAR16,
        sample_rate_hertz=sample_rate,  # Using 8kHz sample rate
    )

    # Perform the text-to-speech request
    response = client.synthesize_speech(input=synthesis_input, voice=voice, audio_config=audio_config)

    # Skip the WAV header (first 44 bytes) to get raw PCM data
    audio_content = response.audio_content[44:]

    # Calculate duration in milliseconds
    # For LINEAR16: 2 bytes per sample, sample_rate samples per second
    bytes_per_sample = 2
    duration_ms = int((len(audio_content) / bytes_per_sample / sample_rate) * 1000)

    # Return both audio content and duration
    return audio_content, duration_ms
