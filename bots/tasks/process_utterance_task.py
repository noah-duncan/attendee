from celery import shared_task
from django.db import DatabaseError

from bots.models import Credentials, RecordingManager, Utterance


def convert_utterance_audio_blob_to_mp3(utterance):
    from bots.utils import pcm_to_mp3

    if utterance.audio_format == Utterance.AudioFormat.PCM:
        mp3_data = pcm_to_mp3(utterance.audio_blob)
        utterance.audio_blob = mp3_data
        utterance.audio_format = Utterance.AudioFormat.MP3
        utterance.save()
        utterance.refresh_from_db()  # because of the .tobytes() issue


@shared_task(
    bind=True,
    soft_time_limit=3600,
    autoretry_for=(DatabaseError,),
    retry_backoff=True,  # Enable exponential backoff
    max_retries=5,
)
def process_utterance(self, utterance_id):
    import json

    from deepgram import (
        DeepgramClient,
        FileSource,
        PrerecordedOptions,
    )

    utterance = Utterance.objects.get(id=utterance_id)
    print(f"Processing utterance {utterance_id}")

    recording = utterance.recording
    RecordingManager.set_recording_transcription_in_progress(recording)

    # if utterance file format is pcm, convert to mp3
    convert_utterance_audio_blob_to_mp3(utterance)

    if utterance.transcription is None:
        payload: FileSource = {
            "buffer": utterance.audio_blob.tobytes(),
        }

        options = PrerecordedOptions(
            model="nova-3",
            smart_format=True,
            language=recording.bot.deepgram_language(),
            detect_language=recording.bot.deepgram_detect_language(),
        )

        deepgram_credentials_record = recording.bot.project.credentials.filter(credential_type=Credentials.CredentialTypes.DEEPGRAM).first()
        if not deepgram_credentials_record:
            raise Exception("Deepgram credentials record not found")

        deepgram_credentials = deepgram_credentials_record.get_credentials()
        if not deepgram_credentials:
            raise Exception("Deepgram credentials not found")

        deepgram = DeepgramClient(deepgram_credentials["api_key"])

        response = deepgram.listen.rest.v("1").transcribe_file(payload, options)
        utterance.transcription = json.loads(response.results.channels[0].alternatives[0].to_json())
        utterance.save()

    # If the recording is in a terminal state and there are no more utterances to transcribe, set the recording's transcription state to complete
    if RecordingManager.is_terminal_state(utterance.recording.state) and Utterance.objects.filter(recording=utterance.recording, transcription__isnull=True).count() == 0:
        RecordingManager.set_recording_transcription_complete(utterance.recording)
