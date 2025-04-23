import logging

from celery import shared_task
from django.db import DatabaseError

logger = logging.getLogger(__name__)

from bots.models import Credentials, RecordingManager, Utterance


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
    logger.info(f"Processing utterance {utterance_id}")

    recording = utterance.recording
    RecordingManager.set_recording_transcription_in_progress(recording)

    if utterance.transcription is None:
        payload: FileSource = {
            "buffer": utterance.audio_blob.tobytes(),
        }

        # nova-3 does not have multilingual support yet, so we need to use nova-2 if we're transcribing with a non-default language
        if (recording.bot.deepgram_language() != "en" and recording.bot.deepgram_language()) or recording.bot.deepgram_detect_language():
            deepgram_model = "nova-2"
        else:
            deepgram_model = "nova-3"

        options = PrerecordedOptions(
            model=deepgram_model,
            smart_format=True,
            language=recording.bot.deepgram_language(),
            detect_language=recording.bot.deepgram_detect_language(),
            encoding="linear16",  # for 16-bit PCM
            sample_rate=utterance.sample_rate,
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
        utterance.audio_blob = b""  # set the binary field to empty byte string
        utterance.save()

        logger.info(f"Transcription complete for utterance {utterance_id} with model {deepgram_model}")

    # If the recording is in a terminal state and there are no more utterances to transcribe, set the recording's transcription state to complete
    if RecordingManager.is_terminal_state(utterance.recording.state) and Utterance.objects.filter(recording=utterance.recording, transcription__isnull=True).count() == 0:
        RecordingManager.set_recording_transcription_complete(utterance.recording)
