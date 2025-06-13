import uuid
from unittest import mock

from django.test import TransactionTestCase

from bots.models import (
    Bot,
    Organization,
    Participant,
    Project,
    Recording,
    RecordingStates,
    RecordingTranscriptionStates,
    TranscriptionFailureReasons,
    Utterance,
)
from bots.tasks.process_utterance_task import process_utterance


class ProcessUtteranceTaskTest(TransactionTestCase):
    """Unit‑tests for bots.tasks.process_utterance_task.process_utterance"""

    def setUp(self):
        # Minimal object graph ------------------------------------------------------------------
        self.organization = Organization.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Proj", organization=self.organization)
        self.bot = Bot.objects.create(project=self.project, meeting_url="https://zoom.us/j/xyz")

        # Recording already finished (so it is a terminal state) and waiting on transcription
        self.recording = Recording.objects.create(
            bot=self.bot,
            recording_type=1,
            transcription_type=1,
            state=RecordingStates.COMPLETE,
            transcription_state=RecordingTranscriptionStates.IN_PROGRESS,
            transcription_provider=1,  # value irrelevant – we stub the provider call
        )

        self.participant = Participant.objects.create(bot=self.bot, uuid=str(uuid.uuid4()))
        self.utterance = Utterance.objects.create(
            recording=self.recording,
            participant=self.participant,
            audio_blob=b"rawpcmbytes",
            timestamp_ms=0,
            duration_ms=500,
            sample_rate=16_000,
        )
        self.utterance.refresh_from_db()

        # Make Celery run synchronously inside tests
        from django.conf import settings

        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = True

    # ------------------------------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------------------------------
    def _run_task(self):
        """Invoke the Celery task with the test utterance id (synchronously)."""
        process_utterance.apply(args=[self.utterance.id])

    # ------------------------------------------------------------------------------------------
    # Test cases
    # ------------------------------------------------------------------------------------------
    @mock.patch("bots.tasks.process_utterance_task.RecordingManager.set_recording_transcription_complete")
    @mock.patch("bots.tasks.process_utterance_task.get_transcription")
    def test_successful_transcription_marks_complete_and_clears_blob(self, mock_get_transcription, mock_set_complete):
        """Happy‑path: transcription returned → audio blob cleared, transcript saved, recording closed."""
        mock_get_transcription.return_value = ({"transcript": "hello world"}, None)

        self._run_task()
        self.utterance.refresh_from_db()

        # Utterance updated
        self.assertEqual(self.utterance.transcription["transcript"], "hello world")
        self.assertEqual(self.utterance.audio_blob, b"")
        self.assertIsNone(self.utterance.failure_data)
        self.assertEqual(self.utterance.transcription_attempt_count, 1)

        # Recording manager called because this was the last outstanding utterance
        mock_set_complete.assert_called_once_with(self.recording)

    # ------------------------------------------------------------------

    @mock.patch("bots.tasks.process_utterance_task.is_retryable_failure", return_value=True)
    @mock.patch("bots.tasks.process_utterance_task.get_transcription")
    def test_retryable_failure_raises_and_increments_counter(self, mock_get_transcription, mock_is_retryable):
        """Retryable failure → task raises for Celery to retry and attempt counter grows."""
        failure = {"reason": TranscriptionFailureReasons.RATE_LIMIT_EXCEEDED}
        mock_get_transcription.return_value = (None, failure)

        with self.assertRaises(Exception):
            self._run_task()

        self.utterance.refresh_from_db()
        self.assertEqual(self.utterance.transcription_attempt_count, 1)
        self.assertIsNone(self.utterance.failure_data)

    # ------------------------------------------------------------------

    @mock.patch("bots.tasks.process_utterance_task.is_retryable_failure", return_value=False)
    @mock.patch("bots.tasks.process_utterance_task.get_transcription")
    def test_non_retryable_failure_sets_failure_data(self, mock_get_transcription, mock_is_retryable):
        """Non‑retryable failure → no exception, failure_data stored."""
        failure = {"reason": TranscriptionFailureReasons.CREDENTIALS_INVALID}
        mock_get_transcription.return_value = (None, failure)

        # Should NOT raise
        self._run_task()
        self.utterance.refresh_from_db()

        self.assertEqual(self.utterance.transcription_attempt_count, 1)
        self.assertEqual(self.utterance.failure_data, failure)

    # ------------------------------------------------------------------

    @mock.patch("bots.tasks.process_utterance_task.get_transcription")
    def test_existing_failure_data_short_circuits_task(self, mock_get_transcription):
        """If utterance already failed, task should exit early and not call provider."""
        self.utterance.failure_data = {"reason": TranscriptionFailureReasons.INTERNAL_ERROR}
        self.utterance.save(update_fields=["failure_data"])

        self._run_task()

        # Provider function never invoked
        mock_get_transcription.assert_not_called()


import json
import types
from unittest import mock

from django.test import TransactionTestCase

from bots.models import (
    Credentials,
)
from bots.tasks.process_utterance_task import get_transcription_via_deepgram


def _build_fake_deepgram(success=True, err_code=None):
    """
    Return a fake 'deepgram' module and (optionally) the
    expected transcript text for the success case.
    """
    fake = types.ModuleType("deepgram")

    # ------------------------------------------------------------------ #
    # 1. DeepgramApiError
    class FakeDGError(Exception):
        def __init__(self, original_error):
            super().__init__("DG error")
            self.original_error = original_error

    fake.DeepgramApiError = FakeDGError

    # ------------------------------------------------------------------ #
    # 2. DeepgramClient mock & its chained method calls
    client_instance = mock.Mock(name="DeepgramClientInstance")

    if success:
        alt = mock.Mock()
        alt.to_json.return_value = json.dumps({"transcript": "hello"})
        channel = mock.Mock(alternatives=[alt])
        response = mock.Mock(results=mock.Mock(channels=[channel]))
        (client_instance.listen.rest.v.return_value.transcribe_file).return_value = response
    else:
        (client_instance.listen.rest.v.return_value.transcribe_file).side_effect = FakeDGError(json.dumps({"err_code": err_code}))

    fake.DeepgramClient = mock.Mock(return_value=client_instance)

    # ------------------------------------------------------------------ #
    # 3. Other names used in the provider
    fake.FileSource = dict
    fake.PrerecordedOptions = mock.Mock()
    return fake


class DeepgramProviderTest(TransactionTestCase):
    """Direct tests for get_transcription_via_deepgram using mock.patch."""

    def setUp(self):
        # ────────────────────────────────────────────────────────────────
        self.org = Organization.objects.create(name="Org")
        self.project = Project.objects.create(name="P", organization=self.org)
        self.bot = self.project.bots.create(meeting_url="https://zoom.us/j/123")

        self.recording = Recording.objects.create(
            bot=self.bot,
            recording_type=1,
            transcription_type=1,
            state=RecordingStates.COMPLETE,
        )
        self.participant = Participant.objects.create(bot=self.bot, uuid=str(uuid.uuid4()))
        self.utterance = Utterance.objects.create(
            recording=self.recording,
            participant=self.participant,
            audio_blob=b"\x01\x02",
            timestamp_ms=0,
            duration_ms=500,
            sample_rate=16_000,
        )
        self.utterance.refresh_from_db()
        # Minimal Deepgram creds
        Credentials.objects.create(project=self.project, credential_type=Credentials.CredentialTypes.DEEPGRAM)
        mock.patch.object(Credentials, "get_credentials", return_value={"api_key": "dg_key"}).start()
        self.addCleanup(mock.patch.stopall)

    # ────────────────────────────────────────────────────────────────────
    def _call_with_fake_module(self, fake_module):
        """
        Helper that patches builtins.__import__ so that only imports of
        'deepgram' get our fake module, everything else behaves normally.
        """
        real_import = __import__

        def _import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "deepgram":
                return fake_module
            return real_import(name, globals, locals, fromlist, level)

        with mock.patch("builtins.__import__", side_effect=_import):
            return get_transcription_via_deepgram(self.utterance)

    # ------------------------------------------------------------------ #
    def test_deepgram_success(self):
        fake = _build_fake_deepgram(success=True)
        transcription, failure = self._call_with_fake_module(fake)

        self.assertIsNone(failure)
        self.assertEqual(transcription, {"transcript": "hello"})

    # ------------------------------------------------------------------ #
    def test_deepgram_invalid_auth(self):
        fake = _build_fake_deepgram(success=False, err_code="INVALID_AUTH")
        transcription, failure = self._call_with_fake_module(fake)

        self.assertIsNone(transcription)
        self.assertEqual(
            failure,
            {"reason": TranscriptionFailureReasons.CREDENTIALS_INVALID},
        )

    # ------------------------------------------------------------------ #
    def test_deepgram_other_error(self):
        fake = _build_fake_deepgram(success=False, err_code="SOME_OTHER")
        transcription, failure = self._call_with_fake_module(fake)

        self.assertIsNone(transcription)
        self.assertEqual(
            failure,
            {
                "reason": TranscriptionFailureReasons.TRANSCRIPTION_REQUEST_FAILED,
                "error_code": "SOME_OTHER",
                "error_json": {"err_code": "SOME_OTHER"},
            },
        )


from unittest import mock

from django.test import TransactionTestCase

from bots.models import (
    Credentials as CredModel,
)
from bots.tasks.process_utterance_task import get_transcription_via_gladia


class GladiaProviderTest(TransactionTestCase):
    """Unit‑tests for bots.tasks.process_utterance_task.get_transcription_via_gladia"""

    def setUp(self):
        # Minimal DB fixtures ---------------------------------------------------------------
        self.org = Organization.objects.create(name="Org")
        self.project = Project.objects.create(name="Proj", organization=self.org)
        self.bot = Bot.objects.create(project=self.project, meeting_url="https://zoom.us/j/999")

        self.recording = Recording.objects.create(
            bot=self.bot,
            recording_type=1,
            transcription_type=1,
            state=RecordingStates.COMPLETE,  # finished recording
            transcription_provider=3,  # GLADIA
        )

        self.participant = Participant.objects.create(bot=self.bot, uuid="p1")
        self.utterance = Utterance.objects.create(
            recording=self.recording,
            participant=self.participant,
            audio_blob=b"pcm-bytes",
            timestamp_ms=0,
            duration_ms=600,
            sample_rate=16_000,
        )
        self.utterance.refresh_from_db()
        # "Real" credential row – we'll monkey‑patch get_credentials() later
        self.cred = Credentials.objects.create(
            project=self.project,
            credential_type=CredModel.CredentialTypes.GLADIA,
        )

    # ------------------------------------------------------------------ helpers

    def _patch_creds(self):
        """Always return a fake API key."""
        return mock.patch.object(CredModel, "get_credentials", return_value={"api_key": "fake‑key"})

    # ------------------------------------------------------------------ SUCCESS PATH

    def test_happy_path(self):
        """Upload → transcribe → poll → delete succeeds and returns formatted transcript."""
        with (
            self._patch_creds(),
            mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3"),
            mock.patch("bots.tasks.process_utterance_task.requests.request") as m_request,
            mock.patch("bots.tasks.process_utterance_task.requests.get") as m_get,
        ):
            # ---- requests.request calls: upload, transcribe, delete -----------------------
            def _request_side_effect(method, url, **_):
                if url.endswith("/upload"):
                    resp = mock.Mock(status_code=201)
                    resp.json.return_value = {"audio_url": "https://api.gladia.io/audio/123"}
                    return resp

                if url.endswith("/pre-recorded"):
                    resp = mock.Mock(status_code=201)
                    resp.json.return_value = {"result_url": "https://api.gladia.io/result/abc"}
                    return resp

                if url.startswith("https://api.gladia.io/result/abc") and method == "DELETE":
                    return mock.Mock(status_code=202)

                raise AssertionError(f"unexpected {method} {url}")

            m_request.side_effect = _request_side_effect

            # ---- requests.get (polling) returns "done" once --------------------------------
            done_resp = mock.Mock(status_code=200)
            done_resp.json.return_value = {
                "status": "done",
                "result": {
                    "transcription": {
                        "full_transcript": "hello world",
                        "utterances": [{"speaker": 0, "words": [{"word": "hello"}, {"word": "world"}]}],
                    }
                },
            }
            m_get.return_value = done_resp

            transcript, failure = get_transcription_via_gladia(self.utterance)

            # Assertions --------------------------------------------------------------------
            self.assertIsNone(failure)
            self.assertEqual(transcript["transcript"], "hello world")
            self.assertEqual([w["word"] for w in transcript["words"]], ["hello", "world"])

            # upload + transcribe + delete = 3 calls
            self.assertEqual(m_request.call_count, 3)
            m_get.assert_called_once_with("https://api.gladia.io/result/abc", headers=mock.ANY)

    # ------------------------------------------------------------------ INVALID CREDENTIALS

    def test_upload_401_returns_credentials_invalid(self):
        """Gladia 401 on upload → CREDENTIALS_INVALID."""
        with (
            self._patch_creds(),
            mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3"),
            mock.patch("bots.tasks.process_utterance_task.requests.request") as m_request,
        ):
            resp401 = mock.Mock(status_code=401)
            m_request.return_value = resp401

            transcript, failure = get_transcription_via_gladia(self.utterance)

            self.assertIsNone(transcript)
            self.assertEqual(failure["reason"], TranscriptionFailureReasons.CREDENTIALS_INVALID)

    # ------------------------------------------------------------------ NO CREDENTIAL ROW

    def test_missing_credentials_row(self):
        """No Credentials row → CREDENTIALS_NOT_FOUND."""
        # Remove the credential row created in setUp
        self.cred.delete()

        transcript, failure = get_transcription_via_gladia(self.utterance)

        self.assertIsNone(transcript)
        self.assertEqual(failure["reason"], TranscriptionFailureReasons.CREDENTIALS_NOT_FOUND)


from unittest import mock

from django.test import TransactionTestCase

from bots.tasks.process_utterance_task import get_transcription_via_openai


class OpenAIProviderTest(TransactionTestCase):
    """Unit‑tests for get_transcription_via_openai"""

    def setUp(self):
        # ── minimal model graph ───────────────────────────────────────────────────────
        self.org = Organization.objects.create(name="Org")
        self.project = Project.objects.create(name="Proj", organization=self.org)
        self.bot = Bot.objects.create(project=self.project, meeting_url="https://example.com/meet")

        # Finished recording waiting on transcription
        self.rec = Recording.objects.create(
            bot=self.bot,
            recording_type=1,
            transcription_type=1,
            state=RecordingStates.COMPLETE,
            transcription_state=RecordingTranscriptionStates.IN_PROGRESS,
            transcription_provider=4,  # TranscriptionProviders.OPENAI
        )

        self.participant = Participant.objects.create(bot=self.bot, uuid="p‑1")
        self.utt = Utterance.objects.create(
            recording=self.rec,
            participant=self.participant,
            audio_blob=b"pcm",
            timestamp_ms=0,
            duration_ms=100,
            sample_rate=16_000,
        )
        self.utt.refresh_from_db()
        # Real credentials row (the crypto doesn't matter – we patch .get_credentials)
        self.creds = Credentials.objects.create(project=self.project, credential_type=Credentials.CredentialTypes.OPENAI)

    # ────────────────────────────────────────────────────────────────────────────────
    @mock.patch("bots.tasks.process_utterance_task.requests.post")
    @mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3")
    def test_success_path(self, mock_pcm, mock_post):
        mock_post.return_value.status_code = 200
        mock_post.return_value.json.return_value = {"text": "hello!"}
        with mock.patch.object(self.creds.__class__, "get_credentials", return_value={"api_key": "sk‑XYZ"}):
            tx, failure = get_transcription_via_openai(self.utt)

        self.assertIsNone(failure)
        self.assertEqual(tx, {"transcript": "hello!"})
        mock_pcm.assert_called_once_with(b"pcm", sample_rate=16_000)
        mock_post.assert_called_once()  # ensure request made

    # ────────────────────────────────────────────────────────────────────────────────
    @mock.patch("bots.tasks.process_utterance_task.requests.post")
    @mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3")
    def test_invalid_credentials(self, mock_pcm, mock_post):
        mock_post.return_value.status_code = 401
        with mock.patch.object(self.creds.__class__, "get_credentials", return_value={"api_key": "bad"}):
            tx, failure = get_transcription_via_openai(self.utt)

        self.assertIsNone(tx)
        self.assertEqual(
            failure,
            {"reason": TranscriptionFailureReasons.CREDENTIALS_INVALID},
        )

    # ────────────────────────────────────────────────────────────────────────────────
    @mock.patch("bots.tasks.process_utterance_task.requests.post")
    @mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3")
    def test_request_failure(self, mock_pcm, mock_post):
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "boom"
        with mock.patch.object(self.creds.__class__, "get_credentials", return_value={"api_key": "sk"}):
            tx, failure = get_transcription_via_openai(self.utt)

        self.assertIsNone(tx)
        self.assertEqual(
            failure,
            {
                "reason": TranscriptionFailureReasons.TRANSCRIPTION_REQUEST_FAILED,
                "status_code": 500,
                "response_text": "boom",
            },
        )

    # ────────────────────────────────────────────────────────────────────────────────
    def test_no_credentials(self):
        # Remove the credentials row
        self.creds.delete()
        tx, failure = get_transcription_via_openai(self.utt)

        self.assertIsNone(tx)
        self.assertEqual(failure, {"reason": TranscriptionFailureReasons.CREDENTIALS_NOT_FOUND})


from unittest import mock

from django.test import TransactionTestCase

from bots.tasks.process_utterance_task import get_transcription_via_assemblyai


class AssemblyAIProviderTest(TransactionTestCase):
    """Unit‑tests for bots.tasks.process_utterance_task.get_transcription_via_assemblyai"""

    def setUp(self):
        # Minimal DB fixtures
        self.org = Organization.objects.create(name="Org")
        self.project = Project.objects.create(name="Proj", organization=self.org)
        self.bot = Bot.objects.create(project=self.project, meeting_url="https://zoom.us/j/999")

        self.recording = Recording.objects.create(
            bot=self.bot,
            recording_type=1,
            transcription_type=1,
            state=RecordingStates.COMPLETE,
            transcription_provider=5,  # ASSEMBLY_AI
        )

        self.participant = Participant.objects.create(bot=self.bot, uuid="p1")
        self.utterance = Utterance.objects.create(
            recording=self.recording,
            participant=self.participant,
            audio_blob=b"pcm-bytes",
            timestamp_ms=0,
            duration_ms=600,
            sample_rate=16_000,
        )
        self.utterance.refresh_from_db()
        self.cred = CredModel.objects.create(
            project=self.project,
            credential_type=CredModel.CredentialTypes.ASSEMBLY_AI,
        )

    def _patch_creds(self):
        """Always return a fake API key."""
        return mock.patch.object(CredModel, "get_credentials", return_value={"api_key": "fake-assembly-key"})

    def test_happy_path(self):
        """Upload → transcribe → poll succeeds and returns formatted transcript."""
        with (
            self._patch_creds(),
            mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3"),
            mock.patch("bots.tasks.process_utterance_task.requests.post") as m_post,
            mock.patch("bots.tasks.process_utterance_task.requests.get") as m_get,
            mock.patch("bots.tasks.process_utterance_task.requests.delete") as m_delete,
        ):
            # 1. Mock upload response
            upload_response = mock.Mock(status_code=200)
            upload_response.json.return_value = {"upload_url": "https://cdn.assemblyai.com/upload/123"}

            # 2. Mock transcript creation response
            transcript_response = mock.Mock(status_code=200)
            transcript_response.json.return_value = {"id": "transcript-abc"}

            m_post.side_effect = [upload_response, transcript_response]

            # 3. Mock polling responses
            processing_response = mock.Mock(status_code=200)
            processing_response.json.return_value = {"status": "processing"}

            done_response = mock.Mock(status_code=200)
            done_response.json.return_value = {
                "status": "completed",
                "text": "hello assembly",
                "words": [
                    {"text": "hello", "start": 100, "end": 200, "confidence": 0.9},
                    {"text": "assembly", "start": 300, "end": 500, "confidence": 0.95},
                ],
            }
            m_get.side_effect = [processing_response, done_response]

            # 4. Mock delete response
            delete_response = mock.Mock(status_code=200)
            m_delete.return_value = delete_response

            transcript, failure = get_transcription_via_assemblyai(self.utterance)

            # Assertions
            self.assertIsNone(failure)
            self.assertEqual(transcript["transcript"], "hello assembly")
            self.assertEqual(len(transcript["words"]), 2)
            self.assertEqual(transcript["words"][0]["word"], "hello")

            self.assertEqual(m_post.call_count, 2)
            self.assertEqual(m_get.call_count, 2)
            m_delete.assert_called_once_with("https://api.assemblyai.com/v2/transcript/transcript-abc", headers=mock.ANY)

    def test_upload_401_returns_credentials_invalid(self):
        """AssemblyAI 401 on upload → CREDENTIALS_INVALID."""
        with (
            self._patch_creds(),
            mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3"),
            mock.patch("bots.tasks.process_utterance_task.requests.post") as m_post,
        ):
            resp401 = mock.Mock(status_code=401)
            m_post.return_value = resp401

            transcript, failure = get_transcription_via_assemblyai(self.utterance)

            self.assertIsNone(transcript)
            self.assertEqual(failure["reason"], TranscriptionFailureReasons.CREDENTIALS_INVALID)
            m_post.assert_called_once()

    def test_missing_credentials_row(self):
        """No Credentials row → CREDENTIALS_NOT_FOUND."""
        self.cred.delete()
        transcript, failure = get_transcription_via_assemblyai(self.utterance)
        self.assertIsNone(transcript)
        self.assertEqual(failure["reason"], TranscriptionFailureReasons.CREDENTIALS_NOT_FOUND)

    def test_transcription_request_failed(self):
        """A non-200 response when creating the transcript job is handled."""
        with (
            self._patch_creds(),
            mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3"),
            mock.patch("bots.tasks.process_utterance_task.requests.post") as m_post,
        ):
            upload_response = mock.Mock(status_code=200)
            upload_response.json.return_value = {"upload_url": "https://cdn.assemblyai.com/upload/123"}

            transcript_response = mock.Mock(status_code=400, text="Bad Request")

            m_post.side_effect = [upload_response, transcript_response]

            transcript, failure = get_transcription_via_assemblyai(self.utterance)

            self.assertIsNone(transcript)
            self.assertEqual(failure["reason"], TranscriptionFailureReasons.TRANSCRIPTION_REQUEST_FAILED)
            self.assertEqual(failure["status_code"], 400)

    def test_polling_error(self):
        """An 'error' status during polling is handled."""
        with (
            self._patch_creds(),
            mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3"),
            mock.patch("bots.tasks.process_utterance_task.requests.post") as m_post,
            mock.patch("bots.tasks.process_utterance_task.requests.get") as m_get,
        ):
            upload_response = mock.Mock(status_code=200)
            upload_response.json.return_value = {"upload_url": "https://cdn.assemblyai.com/upload/123"}
            transcript_response = mock.Mock(status_code=200)
            transcript_response.json.return_value = {"id": "transcript-abc"}
            m_post.side_effect = [upload_response, transcript_response]

            error_response = mock.Mock(status_code=200)
            error_response.json.return_value = {"status": "error", "error": "Something went wrong"}
            m_get.return_value = error_response

            transcript, failure = get_transcription_via_assemblyai(self.utterance)

            self.assertIsNone(transcript)
            self.assertEqual(failure["reason"], TranscriptionFailureReasons.TRANSCRIPTION_REQUEST_FAILED)
            self.assertEqual(failure["error"], "Something went wrong")
            m_get.assert_called_once()

    def test_polling_timeout(self):
        """Polling that never completes results in a TIMED_OUT failure."""
        with (
            self._patch_creds(),
            mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3"),
            mock.patch("bots.tasks.process_utterance_task.requests.post") as m_post,
            mock.patch("bots.tasks.process_utterance_task.requests.get") as m_get,
            mock.patch("bots.tasks.process_utterance_task.time.sleep"),  # speed up test
        ):
            upload_response = mock.Mock(status_code=200)
            upload_response.json.return_value = {"upload_url": "https://cdn.assemblyai.com/upload/123"}
            transcript_response = mock.Mock(status_code=200)
            transcript_response.json.return_value = {"id": "transcript-abc"}
            m_post.side_effect = [upload_response, transcript_response]

            processing_response = mock.Mock(status_code=200)
            processing_response.json.return_value = {"status": "processing"}
            m_get.return_value = processing_response

            transcript, failure = get_transcription_via_assemblyai(self.utterance)

            self.assertIsNone(transcript)
            self.assertEqual(failure["reason"], TranscriptionFailureReasons.TIMED_OUT)
            # The code has max_retries = 120
            self.assertEqual(m_get.call_count, 120)

    def test_word_boost_and_boost_param_included(self):
        """Test that word_boost and boost_param are included in the AssemblyAI request if set in settings."""
        self.bot.settings = {
            "transcription_settings": {
                "assembly_ai": {
                    "word_boost": ["aws", "azure", "google cloud"],
                    "boost_param": "high",
                }
            }
        }
        self.bot.save()
        with (
            self._patch_creds(),
            mock.patch("bots.tasks.process_utterance_task.pcm_to_mp3", return_value=b"mp3"),
            mock.patch("bots.tasks.process_utterance_task.requests.post") as m_post,
            mock.patch("bots.tasks.process_utterance_task.requests.get") as m_get,
            mock.patch("bots.tasks.process_utterance_task.requests.delete") as m_delete,
        ):
            # 1. Mock upload response
            upload_response = mock.Mock(status_code=200)
            upload_response.json.return_value = {"upload_url": "https://cdn.assemblyai.com/upload/123"}

            # 2. Mock transcript creation response
            transcript_response = mock.Mock(status_code=200)
            transcript_response.json.return_value = {"id": "transcript-abc"}

            m_post.side_effect = [upload_response, transcript_response]

            # 3. Mock polling responses
            done_response = mock.Mock(status_code=200)
            done_response.json.return_value = {
                "status": "completed",
                "text": "hello assembly",
                "words": [],
            }
            m_get.return_value = done_response

            # 4. Mock delete response
            delete_response = mock.Mock(status_code=200)
            m_delete.return_value = delete_response

            transcript, failure = get_transcription_via_assemblyai(self.utterance)

            self.assertIsNone(failure)
            self.assertEqual(transcript["transcript"], "hello assembly")

            # Check that the transcript creation request included word_boost and boost_param
            # The second call to requests.post is the transcript creation
            transcript_call = m_post.call_args_list[1]
            _, kwargs = transcript_call
            data = kwargs["json"]
            self.assertIn("word_boost", data)
            self.assertEqual(data["word_boost"], ["aws", "azure", "google cloud"])
            self.assertIn("boost_param", data)
            self.assertEqual(data["boost_param"], "high")
