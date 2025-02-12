from unittest.mock import patch, MagicMock, call
from bots.models import *
import os
import threading
import time
from django.db import connection
from bots.bot_controller import BotController
from django.test.testcases import TransactionTestCase
from bots.bot_controller.streaming_uploader import StreamingUploader
from bots.bots_api_views import send_sync_command
import base64
from bots.utils import mp3_to_pcm, png_to_yuv420_frame
import json
from bots.bot_controller.gstreamer_pipeline import GstreamerPipeline

def create_mock_streaming_uploader():
    mock_streaming_uploader = MagicMock(spec=StreamingUploader)
    mock_streaming_uploader.upload_part.return_value = None
    mock_streaming_uploader.complete_upload.return_value = None
    mock_streaming_uploader.start_upload.return_value = None
    mock_streaming_uploader.key = 'test-recording-key'  # Simple string attribute
    return mock_streaming_uploader

def create_mock_zoom_sdk():
    # Create mock zoom_meeting_sdk module with proper callback handling
    base_mock = MagicMock()

    class MeetingFailCode:
        MEETING_FAIL_BLOCKED_BY_ACCOUNT_ADMIN = '100'
        MEETING_FAIL_UNABLE_TO_JOIN_EXTERNAL_MEETING = '101'
    base_mock.MeetingFailCode = MeetingFailCode

    # Create a custom ZoomSDKRendererDelegateCallbacks class that actually stores the callback
    class MockZoomSDKRendererDelegateCallbacks:
        def __init__(self, onRawDataFrameReceivedCallback, onRendererBeDestroyedCallback, onRawDataStatusChangedCallback):
            self.stored_callback = onRawDataFrameReceivedCallback
            self.stored_renderer_destroyed_callback = onRendererBeDestroyedCallback
            self.stored_raw_data_status_changed_callback = onRawDataStatusChangedCallback

        def onRawDataFrameReceivedCallback(self, data):
            return self.stored_callback(data)
        
        def onRendererBeDestroyedCallback(self):
            return self.stored_renderer_destroyed_callback()
        
        def onRawDataStatusChangedCallback(self, status):
            return self.stored_raw_data_status_changed_callback(status)
    base_mock.ZoomSDKRendererDelegateCallbacks = MockZoomSDKRendererDelegateCallbacks

    # Create a custom MeetingRecordingCtrlEventCallbacks class that actually stores the callback
    class MockMeetingRecordingCtrlEventCallbacks:
        def __init__(self, onRecordPrivilegeChangedCallback):
            self.stored_callback = onRecordPrivilegeChangedCallback

        def onRecordPrivilegeChangedCallback(self, can_record):
            return self.stored_callback(can_record)
    base_mock.MeetingRecordingCtrlEventCallbacks = MockMeetingRecordingCtrlEventCallbacks
    
    # Create a custom AuthServiceEventCallbacks class that actually stores the callback
    class MockAuthServiceEventCallbacks:
        def __init__(self, onAuthenticationReturnCallback):
            self.stored_callback = onAuthenticationReturnCallback

        def onAuthenticationReturnCallback(self, result):
            return self.stored_callback(result)

    # Replace the mock's AuthServiceEventCallbacks with our custom version
    base_mock.AuthServiceEventCallbacks = MockAuthServiceEventCallbacks

    # Create a custom MeetingServiceEventCallbacks class that actually stores the callback
    class MockMeetingServiceEventCallbacks:
        def __init__(self, onMeetingStatusChangedCallback):
            self.stored_callback = onMeetingStatusChangedCallback

        def onMeetingStatusChangedCallback(self, status, result):
            return self.stored_callback(status, result)

    # Replace the mock's MeetingServiceEventCallbacks with our custom version
    base_mock.MeetingServiceEventCallbacks = MockMeetingServiceEventCallbacks
    
    # Set up constants
    base_mock.SDKERR_SUCCESS = 0
    base_mock.AUTHRET_SUCCESS = 1
    base_mock.MEETING_STATUS_IDLE = 2
    base_mock.MEETING_STATUS_CONNECTING = 3
    base_mock.MEETING_STATUS_INMEETING = 4
    base_mock.MEETING_STATUS_ENDED = 5
    base_mock.LEAVE_MEETING = 6
    base_mock.AUTHRET_JWTTOKENWRONG = 7
    
    # Mock SDK_LANGUAGE_ID
    base_mock.SDK_LANGUAGE_ID = MagicMock()
    base_mock.SDK_LANGUAGE_ID.LANGUAGE_English = 0

    # Mock SDKAudioChannel
    base_mock.ZoomSDKAudioChannel_Mono = 0
    
    # Mock SDKUserType
    base_mock.SDKUserType = MagicMock()
    base_mock.SDKUserType.SDK_UT_WITHOUT_LOGIN = 1

    # Create mock services
    mock_meeting_service = MagicMock()
    mock_auth_service = MagicMock()
    mock_setting_service = MagicMock()
    mock_zoom_sdk_renderer = MagicMock()
    
    # Configure mock services
    mock_meeting_service.SetEvent.return_value = base_mock.SDKERR_SUCCESS
    mock_meeting_service.Join.return_value = base_mock.SDKERR_SUCCESS
    mock_meeting_service.GetMeetingStatus.return_value = base_mock.MEETING_STATUS_IDLE
    mock_meeting_service.Leave.return_value = base_mock.SDKERR_SUCCESS

    # Add mock recording controller
    mock_recording_controller = MagicMock()
    mock_recording_controller.CanStartRawRecording.return_value = base_mock.SDKERR_SUCCESS
    mock_recording_controller.StartRawRecording.return_value = base_mock.SDKERR_SUCCESS
    mock_meeting_service.GetMeetingRecordingController.return_value = mock_recording_controller
    
    mock_auth_service.SetEvent.return_value = base_mock.SDKERR_SUCCESS
    mock_auth_service.SDKAuth.return_value = base_mock.SDKERR_SUCCESS
    
    # Configure service creation functions
    base_mock.CreateMeetingService.return_value = mock_meeting_service
    base_mock.CreateAuthService.return_value = mock_auth_service
    base_mock.CreateSettingService.return_value = mock_setting_service
    base_mock.CreateRenderer.return_value = mock_zoom_sdk_renderer
    
    # Configure InitSDK
    base_mock.InitSDK.return_value = base_mock.SDKERR_SUCCESS

    # Add SDKError class mock with SDKERR_SUCCESS
    base_mock.SDKError = MagicMock()
    base_mock.SDKError.SDKERR_SUCCESS = 0  # Use the same value as SDKERR_SUCCESS
    base_mock.SDKError.SDKERR_INTERNAL_ERROR = 1

    # Create a mock PerformanceData class
    class MockPerformanceData:
        def __init__(self):
            self.totalProcessingTimeMicroseconds = 1000
            self.numCalls = 100
            self.maxProcessingTimeMicroseconds = 20
            self.minProcessingTimeMicroseconds = 5
            self.processingTimeBinMin = 0
            self.processingTimeBinMax = 100
            self.processingTimeBinCounts = [10, 20, 30, 20, 10, 5, 3, 2]  # Example distribution

    # Create a custom ZoomSDKAudioRawDataDelegateCallbacks class that actually stores the callback
    class MockZoomSDKAudioRawDataDelegateCallbacks:
        def __init__(self, onOneWayAudioRawDataReceivedCallback, onMixedAudioRawDataReceivedCallback, collectPerformanceData=False):
            self.stored_one_way_callback = onOneWayAudioRawDataReceivedCallback
            self.stored_mixed_callback = onMixedAudioRawDataReceivedCallback
            self.collect_performance_data = collectPerformanceData

        def onOneWayAudioRawDataReceivedCallback(self, data, node_id):
            return self.stored_one_way_callback(data, node_id)

        def onMixedAudioRawDataReceivedCallback(self, data):
            return self.stored_mixed_callback(data)

        def getPerformanceData(self):
            return MockPerformanceData()

    base_mock.ZoomSDKAudioRawDataDelegateCallbacks = MockZoomSDKAudioRawDataDelegateCallbacks
    
    class MockZoomSDKVirtualAudioMicEventCallbacks:
        def __init__(self, onMicInitializeCallback, onMicStartSendCallback):
            self.stored_initialize_callback = onMicInitializeCallback
            self.stored_start_send_callback = onMicStartSendCallback

        def onMicInitializeCallback(self, sender):
            return self.stored_initialize_callback(sender)

        def onMicStartSendCallback(self):
            return self.stored_start_send_callback()

    base_mock.ZoomSDKVirtualAudioMicEventCallbacks = MockZoomSDKVirtualAudioMicEventCallbacks

    class MockZoomSDKVideoSourceCallbacks:
        def __init__(self, onInitializeCallback, onStartSendCallback):
            self.stored_initialize_callback = onInitializeCallback
            self.stored_start_send_callback = onStartSendCallback

        def onInitializeCallback(self, sender, support_cap_list, suggest_cap):
            return self.stored_initialize_callback(sender, support_cap_list, suggest_cap)

        def onStartSendCallback(self):
            return self.stored_start_send_callback()
        
    base_mock.ZoomSDKVideoSourceCallbacks = MockZoomSDKVideoSourceCallbacks

    # Create a mock participant class
    class MockParticipant:
        def __init__(self, user_id, user_name, persistent_id):
            self._user_id = user_id
            self._user_name = user_name
            self._persistent_id = persistent_id

        def GetUserID(self):
            return self._user_id

        def GetUserName(self):
            return self._user_name

        def GetPersistentId(self):
            return self._persistent_id

    # Create a mock participants controller class
    class MockParticipant:
        def __init__(self, user_id, user_name, persistent_id):
            self._user_id = user_id
            self._user_name = user_name
            self._persistent_id = persistent_id

        def GetUserID(self):
            return self._user_id

        def GetUserName(self):
            return self._user_name

        def GetPersistentId(self):
            return self._persistent_id

    # Create a mock participants controller
    mock_participants_controller = MagicMock()
    mock_participants_controller.GetParticipantsList.return_value = [2]  # Return test user ID
    mock_participants_controller.GetUserByUserID.return_value = MockParticipant(2, "Test User", "test_persistent_id_123")
    mock_participants_controller.GetMySelfUser.return_value = MockParticipant(1, "Bot User", "bot_persistent_id")

    # Add participants controller to meeting service
    mock_meeting_service.GetMeetingParticipantsController.return_value = mock_participants_controller

    return base_mock

def create_mock_deepgram():
    # Create mock objects
    mock_deepgram = MagicMock()
    mock_response = MagicMock()
    mock_results = MagicMock()
    mock_channel = MagicMock()
    mock_alternative = MagicMock()
    
    # Set up the mock response structure
    mock_alternative.to_json.return_value = json.dumps({
        "transcript": "This is a test transcript",
        "confidence": 0.95,
        "words": [
            {"word": "This", "start": 0.0, "end": 0.2, "confidence": 0.98},
            {"word": "is", "start": 0.2, "end": 0.4, "confidence": 0.97},
            {"word": "a", "start": 0.4, "end": 0.5, "confidence": 0.99},
            {"word": "test", "start": 0.5, "end": 0.8, "confidence": 0.96},
            {"word": "transcript", "start": 0.8, "end": 1.2, "confidence": 0.94}
        ]
    })
    mock_channel.alternatives = [mock_alternative]
    mock_results.channels = [mock_channel]
    mock_response.results = mock_results
    
    # Set up the mock client
    mock_deepgram.listen.rest.v.return_value.transcribe_file.return_value = mock_response
    return mock_deepgram

class MockVideoFrame:
    def __init__(self):
        width = 640
        height = 360
        
        # Create separate Y, U, and V planes
        self.y_buffer = b'\x00' * (width * height)        # Y plane (black)
        self.u_buffer = b'\x80' * (width * height // 4)   # U plane (128 for black)
        self.v_buffer = b'\x80' * (width * height // 4)   # V plane (128 for black)
        
        self.size = len(self.y_buffer) + len(self.u_buffer) + len(self.v_buffer)
        self.timestamp = int(time.time() * 1000)  # Current time in milliseconds

    def GetBuffer(self):
        return self.y_buffer + self.u_buffer + self.v_buffer

    def GetYBuffer(self):
        return self.y_buffer

    def GetUBuffer(self):
        return self.u_buffer

    def GetVBuffer(self):
        return self.v_buffer

    def GetStreamWidth(self):
        return 640

    def GetStreamHeight(self):
        return 360

class MockAudioFrame:
    def __init__(self):
        # Create 10ms of a 440Hz sine wave at 32000Hz mono
        # 32000 samples/sec * 0.01 sec = 320 samples
        # Each sample is 2 bytes (unsigned 16-bit)
        import math
        samples = []
        for i in range(320):  # 10ms worth of samples at 32kHz
            # Generate sine wave with frequency 440Hz
            t = i / 32000.0  # time in seconds
            # Generate value between 0 and 65535 (unsigned 16-bit)
            # Center at 32768, use amplitude of 16384 to avoid clipping
            value = int(32768 + 16384 * math.sin(2 * math.pi * 440 * t))
            # Ensure value stays within valid range
            value = max(0, min(65535, value))
            # Convert to two bytes (little-endian)
            samples.extend([value & 0xFF, (value >> 8) & 0xFF])
        self.buffer = bytes(samples)

    def GetBuffer(self):
        return self.buffer

class TestBotJoinMeeting(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        
        # Set required environment variables
        os.environ['AWS_RECORDING_STORAGE_BUCKET_NAME'] = 'test-bucket'

    def setUp(self):
        # Recreate organization and project for each test
        self.organization = Organization.objects.create(name="Test Org")
        self.project = Project.objects.create(
            name="Test Project",
            organization=self.organization
        )
        
        # Recreate credentials
        self.credentials = Credentials.objects.create(
            project=self.project,
            credential_type=Credentials.CredentialTypes.ZOOM_OAUTH
        )
        self.credentials.set_credentials({
            'client_id': 'test_client_id',
            'client_secret': 'test_client_secret'
        })
        self.deepgram_credentials = Credentials.objects.create(
            project=self.project,
            credential_type=Credentials.CredentialTypes.DEEPGRAM
        )
        self.deepgram_credentials.set_credentials({
            'api_key': 'test_api_key'
        })
        self.google_credentials = Credentials.objects.create(
            project=self.project,
            credential_type=Credentials.CredentialTypes.GOOGLE_TTS
        )
        self.google_credentials.set_credentials({
            'service_account_json': '{"type": "service_account", "project_id": "test-project", "private_key_id": "test-private-key-id", "private_key": "test-private-key", "client_email": "test-client-email", "client_id": "test-client-id", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token", "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs", "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/test-client-email"}'
        })

        # Create a bot for each test
        self.bot = Bot.objects.create(
            project=self.project,
            name="Test Bot",
            meeting_url="https://zoom.us/j/123456789?pwd=password123"
        )
        
        # Create default recording
        self.recording = Recording.objects.create(
            bot=self.bot,
            recording_type=RecordingTypes.AUDIO_AND_VIDEO,
            transcription_type=TranscriptionTypes.NON_REALTIME,
            transcription_provider=TranscriptionProviders.DEEPGRAM,
            is_default_recording=True
        )

        # Try to transition the state from READY to JOINING
        BotEventManager.create_event(self.bot, BotEventTypes.JOIN_REQUESTED)

        self.test_mp3_bytes = base64.b64decode('SUQzBAAAAAAAI1RTU0UAAAAPAAADTGF2ZjU2LjM2LjEwMAAAAAAAAAAAAAAA//OEAAAAAAAAAAAAAAAAAAAAAAAASW5mbwAAAA8AAAAEAAABIADAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDV1dXV1dXV1dXV1dXV1dXV1dXV1dXV1dXV6urq6urq6urq6urq6urq6urq6urq6urq6v////////////////////////////////8AAAAATGF2YzU2LjQxAAAAAAAAAAAAAAAAJAAAAAAAAAAAASDs90hvAAAAAAAAAAAAAAAAAAAA//MUZAAAAAGkAAAAAAAAA0gAAAAATEFN//MUZAMAAAGkAAAAAAAAA0gAAAAARTMu//MUZAYAAAGkAAAAAAAAA0gAAAAAOTku//MUZAkAAAGkAAAAAAAAA0gAAAAANVVV')
        self.test_png_bytes = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')

        self.audio_blob = MediaBlob.get_or_create_from_blob(
            project=self.bot.project,
            blob=self.test_mp3_bytes,
            content_type='audio/mp3'
        )

        self.image_blob = MediaBlob.get_or_create_from_blob(
            project=self.bot.project,
            blob=self.test_png_bytes,
            content_type='image/png'
        )

        # Configure Celery to run tasks eagerly (synchronously)
        from django.conf import settings
        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = True

    @patch('bots.zoom_bot_adapter.video_input_manager.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    @patch('deepgram.DeepgramClient')
    @patch('google.cloud.texttospeech.TextToSpeechClient')
    def test_bot_can_join_meeting_and_record_audio_and_video(self, MockTextToSpeechClient, MockDeepgramClient, MockStreamingUploader, mock_jwt, mock_zoom_sdk_adapter, mock_zoom_sdk_video):
        # Set up Google TTS mock
        mock_tts_client = MagicMock()
        mock_tts_response = MagicMock()
        
        # Create fake PCM audio data (1 second of 44.1kHz audio)
        # WAV header (44 bytes) + PCM data
        wav_header = (
            b'RIFF'              # ChunkID (4 bytes)
            b'\x24\x00\x00\x00'  # ChunkSize (4 bytes)
            b'WAVE'              # Format (4 bytes)
            b'fmt '              # Subchunk1ID (4 bytes)
            b'\x10\x00\x00\x00'  # Subchunk1Size (4 bytes)
            b'\x01\x00'          # AudioFormat (2 bytes)
            b'\x01\x00'          # NumChannels (2 bytes)
            b'\x44\xac\x00\x00'  # SampleRate (4 bytes)
            b'\x88\x58\x01\x00'  # ByteRate (4 bytes)
            b'\x02\x00'          # BlockAlign (2 bytes)
            b'\x10\x00'          # BitsPerSample (2 bytes)
            b'data'              # Subchunk2ID (4 bytes)
            b'\x50\x00\x00\x00'  # Subchunk2Size (4 bytes) - size of audio data
        )
        pcm_speech_data = b'\x00\x00' * (40)  # small period of silence at 44.1kHz
        mock_tts_response.audio_content = wav_header + pcm_speech_data
        
        # Configure the mock client to return our mock response
        mock_tts_client.synthesize_speech.return_value = mock_tts_response
        MockTextToSpeechClient.from_service_account_info.return_value = mock_tts_client

        # Set up Deepgram mock
        MockDeepgramClient.return_value = create_mock_deepgram()
        
        # Store uploaded data for verification
        uploaded_data = bytearray()
        
        # Configure the mock uploader to capture uploaded data
        mock_uploader = create_mock_streaming_uploader()
        def capture_upload_part(data):
            uploaded_data.extend(data)
        mock_uploader.upload_part.side_effect = capture_upload_part
        MockStreamingUploader.return_value = mock_uploader
        
        # Mock the JWT token generation
        mock_jwt.encode.return_value = "fake_jwt_token"
        
        # Create bot controller
        controller = BotController(self.bot.id)
        
        # Run the bot in a separate thread since it has an event loop
        bot_thread = threading.Thread(target=controller.run)
        bot_thread.daemon = True
        bot_thread.start()

        audio_request = None
        image_request = None
        speech_request = None
        
        def simulate_join_flow():
            nonlocal audio_request, image_request, speech_request

            adapter = controller.adapter
            # Simulate successful auth            
            adapter.auth_event.onAuthenticationReturnCallback(mock_zoom_sdk_adapter.AUTHRET_SUCCESS)

            # Simulate connecting
            adapter.meeting_service_event.onMeetingStatusChangedCallback(
                mock_zoom_sdk_adapter.MEETING_STATUS_CONNECTING, 
                mock_zoom_sdk_adapter.SDKERR_SUCCESS
            )
            
            # Simulate successful join
            adapter.meeting_service_event.onMeetingStatusChangedCallback(
                mock_zoom_sdk_adapter.MEETING_STATUS_INMEETING, 
                mock_zoom_sdk_adapter.SDKERR_SUCCESS
            )

            # Wait for the video input manager to be set up
            time.sleep(2)

            # Simulate video frame received
            adapter.video_input_manager.input_streams[0].renderer_delegate.onRawDataFrameReceivedCallback(
                MockVideoFrame()
            )

            # Simulate audio frame received
            adapter.audio_source.onOneWayAudioRawDataReceivedCallback(
                MockAudioFrame(),
                2  # Simulated participant ID that's not the bot
            )
            adapter.audio_source.onMixedAudioRawDataReceivedCallback(MockAudioFrame())

            # simulate audio mic initialized
            adapter.virtual_audio_mic_event_passthrough.onMicInitializeCallback(MagicMock())

            # simulate audio mic started
            adapter.virtual_audio_mic_event_passthrough.onMicStartSendCallback()

            # simulate video source initialized
            adapter.virtual_camera_video_source.onInitializeCallback(MagicMock(), None, None)

            # simulate video source started
            adapter.virtual_camera_video_source.onStartSendCallback()

            # simulate sending audio and image
            # Create media requests
            audio_request = BotMediaRequest.objects.create(
                bot=self.bot,
                media_blob=self.audio_blob,
                media_type=BotMediaRequestMediaTypes.AUDIO
            )

            image_request = BotMediaRequest.objects.create(
                bot=self.bot,
                media_blob=self.image_blob,
                media_type=BotMediaRequestMediaTypes.IMAGE
            )

            send_sync_command(self.bot, 'sync_media_requests')

            # Sleep to give audio output manager time to play the audio
            time.sleep(2.0)

            # Create text-to-speech request
            speech_request = BotMediaRequest.objects.create(
                bot=self.bot,
                text_to_speak="Hello, this is a test speech",
                text_to_speech_settings={
                    'google': {
                        'voice_language_code': 'en-US',
                        'voice_name': 'en-US-Standard-A'
                    }
                },
                media_type=BotMediaRequestMediaTypes.AUDIO
            )

            send_sync_command(self.bot, 'sync_media_requests')

            # Sleep to give audio output manager time to play the speech audio
            time.sleep(2.0)

            # Simulate meeting ended
            adapter.meeting_service_event.onMeetingStatusChangedCallback(
                mock_zoom_sdk_adapter.MEETING_STATUS_ENDED, 
                mock_zoom_sdk_adapter.SDKERR_SUCCESS
            )
            
            connection.close()
        
        # Run join flow simulation after a short delay
        threading.Timer(3, simulate_join_flow).start()
        
        # Give the bot some time to process
        bot_thread.join(timeout=10)
        
        # Verify that we received some data
        self.assertGreater(len(uploaded_data), 100, "Uploaded data length is not correct")
        
        # Check for MP4 file signature (starts with 'ftyp')
        mp4_signature_found = b'ftyp' in uploaded_data[:1000]
        self.assertTrue(mp4_signature_found, "MP4 file signature not found in uploaded data")
        
        # Additional verification for StreamingUploader
        mock_uploader.start_upload.assert_called_once()
        self.assertGreater(mock_uploader.upload_part.call_count, 0, "upload_part was never called")
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()

        # Assert that the bot is in the ENDED state
        self.assertEqual(self.bot.state, BotStates.ENDED)
        
        # Verify all bot events in sequence
        bot_events = self.bot.bot_events.all()
        self.assertEqual(len(bot_events), 4)  # We expect 4 events in total

        # Verify join_requested_event (Event 1)
        join_requested_event = bot_events[0]
        self.assertEqual(join_requested_event.event_type, BotEventTypes.JOIN_REQUESTED)
        self.assertEqual(join_requested_event.old_state, BotStates.READY)
        self.assertEqual(join_requested_event.new_state, BotStates.JOINING)
        self.assertIsNone(join_requested_event.event_sub_type)
        self.assertEqual(join_requested_event.metadata, {})
        self.assertIsNotNone(join_requested_event.requested_bot_action_taken_at)

        # Verify bot_joined_meeting_event (Event 2)
        bot_joined_meeting_event = bot_events[1]
        self.assertEqual(bot_joined_meeting_event.event_type, BotEventTypes.BOT_JOINED_MEETING)
        self.assertEqual(bot_joined_meeting_event.old_state, BotStates.JOINING)
        self.assertEqual(bot_joined_meeting_event.new_state, BotStates.JOINED_NOT_RECORDING)
        self.assertIsNone(bot_joined_meeting_event.event_sub_type)
        self.assertEqual(bot_joined_meeting_event.metadata, {})
        self.assertIsNone(bot_joined_meeting_event.requested_bot_action_taken_at)

        # Verify recording_permission_granted_event (Event 3)
        recording_permission_granted_event = bot_events[2]
        self.assertEqual(recording_permission_granted_event.event_type, BotEventTypes.BOT_RECORDING_PERMISSION_GRANTED)
        self.assertEqual(recording_permission_granted_event.old_state, BotStates.JOINED_NOT_RECORDING)
        self.assertEqual(recording_permission_granted_event.new_state, BotStates.JOINED_RECORDING)
        self.assertIsNone(recording_permission_granted_event.event_sub_type)
        self.assertEqual(recording_permission_granted_event.metadata, {})
        self.assertIsNone(recording_permission_granted_event.requested_bot_action_taken_at)
        print("bot_events = ", bot_events)
        # Verify meeting_ended_event (Event 4)
        meeting_ended_event = bot_events[3]
        self.assertEqual(meeting_ended_event.event_type, BotEventTypes.MEETING_ENDED)
        self.assertEqual(meeting_ended_event.old_state, BotStates.JOINED_RECORDING)
        self.assertEqual(meeting_ended_event.new_state, BotStates.ENDED)
        self.assertIsNone(meeting_ended_event.event_sub_type)
        self.assertEqual(meeting_ended_event.metadata, {})
        self.assertIsNone(meeting_ended_event.requested_bot_action_taken_at)
            
        # Verify expected SDK calls
        mock_zoom_sdk_adapter.InitSDK.assert_called_once()
        mock_zoom_sdk_adapter.CreateMeetingService.assert_called_once()
        mock_zoom_sdk_adapter.CreateAuthService.assert_called_once()
        controller.adapter.meeting_service.Join.assert_called_once()
        
        # Verify audio request was processed
        audio_request.refresh_from_db()
        self.assertEqual(audio_request.state, BotMediaRequestStates.FINISHED)

        # Verify speech request was processed
        speech_request.refresh_from_db()
        self.assertEqual(speech_request.state, BotMediaRequestStates.FINISHED)

        # Verify image request was processed
        image_request.refresh_from_db() 
        self.assertEqual(image_request.state, BotMediaRequestStates.FINISHED)

        # Verify that the recording was finished
        self.recording.refresh_from_db()
        self.assertEqual(self.recording.state, RecordingStates.COMPLETE)
        self.assertEqual(self.recording.transcription_state, RecordingTranscriptionStates.COMPLETE)

        # Verify that the recording has an utterance
        utterance = self.recording.utterances.first()
        self.assertEqual(self.recording.utterances.count(), 1)
        self.assertIsNotNone(utterance.transcription)
        print("utterance.transcription = ", utterance.transcription)

        # Verify the bot adapter received the media
        controller.adapter.audio_raw_data_sender.send.assert_has_calls([
            # First call from audio request
            call(mp3_to_pcm(self.test_mp3_bytes, sample_rate=44100), 44100, mock_zoom_sdk_adapter.ZoomSDKAudioChannel_Mono),
            # Second call from text-to-speech
            call(pcm_speech_data, 44100, mock_zoom_sdk_adapter.ZoomSDKAudioChannel_Mono)
        ], any_order=True)
        
        controller.adapter.video_sender.sendVideoFrame.assert_has_calls([
            call(png_to_yuv420_frame(self.test_png_bytes), 640, 360, 0, mock_zoom_sdk_adapter.FrameDataFormat_I420_FULL)
        ], any_order=True)

        # Cleanup
        controller.cleanup()
        bot_thread.join(timeout=5)
        
        # Close the database connection since we're in a thread
        connection.close()

    @patch('bots.zoom_bot_adapter.video_input_manager.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    def test_bot_can_handle_failed_zoom_auth(self, MockStreamingUploader, mock_jwt, mock_zoom_sdk_adapter, mock_zoom_sdk_video):
        # Configure the mock class to return our mock instance
        mock_uploader = create_mock_streaming_uploader()
        MockStreamingUploader.return_value = mock_uploader
        
        # Mock the JWT token generation
        mock_jwt.encode.return_value = "fake_jwt_token"
        
        # Create bot controller
        controller = BotController(self.bot.id)
        
        # Run the bot in a separate thread since it has an event loop
        bot_thread = threading.Thread(target=controller.run)
        bot_thread.daemon = True
        bot_thread.start()
        
        def simulate_failed_auth_flow():
            # Simulate failed auth            
            controller.adapter.auth_event.onAuthenticationReturnCallback(mock_zoom_sdk_adapter.AUTHRET_JWTTOKENWRONG)
            # Clean up connections in thread
            connection.close()
        
        # Run join flow simulation after a short delay
        threading.Timer(2, simulate_failed_auth_flow).start()
        
        # Give the bot some time to process
        bot_thread.join(timeout=10)
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()
        
        # Check that the bot joined successfully
        bot_events = self.bot.bot_events.all()
        self.assertEqual(len(bot_events), 2)
        join_requested_event = bot_events[0]
        could_not_join_event = bot_events[1]

        # Verify join_requested_event properties
        self.assertEqual(join_requested_event.event_type, BotEventTypes.JOIN_REQUESTED)
        self.assertEqual(join_requested_event.old_state, BotStates.READY)
        self.assertEqual(join_requested_event.new_state, BotStates.JOINING)
        self.assertIsNone(join_requested_event.event_sub_type)
        self.assertEqual(join_requested_event.metadata, {})
        self.assertIsNotNone(join_requested_event.requested_bot_action_taken_at)

        # Verify could_not_join_event properties
        self.assertEqual(could_not_join_event.event_type, BotEventTypes.COULD_NOT_JOIN)
        self.assertEqual(could_not_join_event.old_state, BotStates.JOINING)
        self.assertEqual(could_not_join_event.new_state, BotStates.FATAL_ERROR)
        self.assertEqual(could_not_join_event.event_sub_type, BotEventSubTypes.COULD_NOT_JOIN_MEETING_ZOOM_AUTHORIZATION_FAILED)
        self.assertEqual(could_not_join_event.metadata, {"zoom_result_code": mock_zoom_sdk_adapter.AUTHRET_JWTTOKENWRONG})
        self.assertIsNone(could_not_join_event.requested_bot_action_taken_at)

        # Verify expected SDK calls
        mock_zoom_sdk_adapter.InitSDK.assert_called_once()
        mock_zoom_sdk_adapter.CreateMeetingService.assert_called_once()
        mock_zoom_sdk_adapter.CreateAuthService.assert_called_once()
        controller.adapter.meeting_service.Join.assert_not_called()
        
        # Additional verification for StreamingUploader
        # Probably should not be called, but it currently is
        #controller.streaming_uploader.start_upload.assert_not_called()
        
        # Cleanup
        # no need to cleanup since we already hit error
        # controller.cleanup() will be called by the bot controller

        bot_thread.join(timeout=5)
        
        # Close the database connection since we're in a thread
        connection.close()

    @patch('bots.zoom_bot_adapter.video_input_manager.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    def test_bot_can_handle_waiting_for_host(self, MockStreamingUploader, mock_jwt, mock_zoom_sdk_adapter, mock_zoom_sdk_video):
        # Configure the mock class to return our mock instance
        mock_uploader = create_mock_streaming_uploader()
        MockStreamingUploader.return_value = mock_uploader
        
        # Mock the JWT token generation
        mock_jwt.encode.return_value = "fake_jwt_token"
        
        # Create bot controller
        controller = BotController(self.bot.id)
        
        # Run the bot in a separate thread since it has an event loop
        bot_thread = threading.Thread(target=controller.run)
        bot_thread.daemon = True
        bot_thread.start()
        
        def simulate_waiting_for_host_flow():
            # Simulate successful auth
            controller.adapter.auth_event.onAuthenticationReturnCallback(mock_zoom_sdk_adapter.AUTHRET_SUCCESS)
            # Simulate waiting for host status
            controller.adapter.meeting_service_event.onMeetingStatusChangedCallback(mock_zoom_sdk_adapter.MEETING_STATUS_WAITINGFORHOST, 0)
            # Clean up connections in thread
            connection.close()
        
        # Run join flow simulation after a short delay
        threading.Timer(2, simulate_waiting_for_host_flow).start()
        
        # Give the bot some time to process
        bot_thread.join(timeout=10)
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()
        
        # Check the bot events
        bot_events = self.bot.bot_events.all()
        self.assertEqual(len(bot_events), 2)
        join_requested_event = bot_events[0]
        could_not_join_event = bot_events[1]

        # Verify join_requested_event properties
        self.assertEqual(join_requested_event.event_type, BotEventTypes.JOIN_REQUESTED)
        self.assertEqual(join_requested_event.old_state, BotStates.READY)
        self.assertEqual(join_requested_event.new_state, BotStates.JOINING)
        self.assertIsNone(join_requested_event.event_sub_type)
        self.assertEqual(join_requested_event.metadata, {})
        self.assertIsNotNone(join_requested_event.requested_bot_action_taken_at)

        # Verify could_not_join_event properties
        self.assertEqual(could_not_join_event.event_type, BotEventTypes.COULD_NOT_JOIN)
        self.assertEqual(could_not_join_event.old_state, BotStates.JOINING)
        self.assertEqual(could_not_join_event.new_state, BotStates.FATAL_ERROR)
        self.assertEqual(could_not_join_event.event_sub_type, BotEventSubTypes.COULD_NOT_JOIN_MEETING_NOT_STARTED_WAITING_FOR_HOST)
        self.assertEqual(could_not_join_event.metadata, {})
        self.assertIsNone(could_not_join_event.requested_bot_action_taken_at)

        # Verify expected SDK calls
        mock_zoom_sdk_adapter.InitSDK.assert_called_once()
        mock_zoom_sdk_adapter.CreateMeetingService.assert_called_once()
        mock_zoom_sdk_adapter.CreateAuthService.assert_called_once()
        controller.adapter.meeting_service.Join.assert_called_once()
        
        # Cleanup
        # no need to cleanup since we already hit error
        # controller.cleanup() will be called by the bot controller
        bot_thread.join(timeout=5)
        
        # Close the database connection since we're in a thread
        connection.close()

    @patch('bots.zoom_bot_adapter.video_input_manager.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    def test_bot_can_handle_unable_to_join_external_meeting(self, MockStreamingUploader, mock_jwt, mock_zoom_sdk_adapter, mock_zoom_sdk_video):
        # Configure the mock class to return our mock instance
        mock_uploader = create_mock_streaming_uploader()
        MockStreamingUploader.return_value = mock_uploader
        
        # Mock the JWT token generation
        mock_jwt.encode.return_value = "fake_jwt_token"
        
        # Create bot controller
        controller = BotController(self.bot.id)
        
        # Run the bot in a separate thread since it has an event loop
        bot_thread = threading.Thread(target=controller.run)
        bot_thread.daemon = True
        bot_thread.start()
        
        def simulate_unable_to_join_external_meeting_flow():
            # Simulate successful auth            
            controller.adapter.auth_event.onAuthenticationReturnCallback(mock_zoom_sdk_adapter.AUTHRET_SUCCESS)
            # Simulate meeting failed status with unable to join external meeting code
            controller.adapter.meeting_service_event.onMeetingStatusChangedCallback(
                mock_zoom_sdk_adapter.MEETING_STATUS_FAILED,
                mock_zoom_sdk_adapter.MeetingFailCode.MEETING_FAIL_UNABLE_TO_JOIN_EXTERNAL_MEETING
            )
            # Clean up connections in thread
            connection.close()
        
        # Run join flow simulation after a short delay
        threading.Timer(2, simulate_unable_to_join_external_meeting_flow).start()
        
        # Give the bot some time to process
        bot_thread.join(timeout=10)
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()
        
        # Check the bot events
        bot_events = self.bot.bot_events.all()
        self.assertEqual(len(bot_events), 2)
        join_requested_event = bot_events[0]
        could_not_join_event = bot_events[1]

        # Verify join_requested_event properties
        self.assertEqual(join_requested_event.event_type, BotEventTypes.JOIN_REQUESTED)
        self.assertEqual(join_requested_event.old_state, BotStates.READY)
        self.assertEqual(join_requested_event.new_state, BotStates.JOINING)
        self.assertIsNone(join_requested_event.event_sub_type)
        self.assertEqual(join_requested_event.metadata, {})
        self.assertIsNotNone(join_requested_event.requested_bot_action_taken_at)

        # Verify could_not_join_event properties
        self.assertEqual(could_not_join_event.event_type, BotEventTypes.COULD_NOT_JOIN)
        self.assertEqual(could_not_join_event.old_state, BotStates.JOINING)
        self.assertEqual(could_not_join_event.new_state, BotStates.FATAL_ERROR)
        self.assertEqual(could_not_join_event.event_sub_type, BotEventSubTypes.COULD_NOT_JOIN_MEETING_UNPUBLISHED_ZOOM_APP)
        self.assertEqual(could_not_join_event.metadata, {"zoom_result_code": mock_zoom_sdk_adapter.MeetingFailCode.MEETING_FAIL_UNABLE_TO_JOIN_EXTERNAL_MEETING})
        self.assertIsNone(could_not_join_event.requested_bot_action_taken_at)

        # Verify expected SDK calls
        mock_zoom_sdk_adapter.InitSDK.assert_called_once()
        mock_zoom_sdk_adapter.CreateMeetingService.assert_called_once()
        mock_zoom_sdk_adapter.CreateAuthService.assert_called_once()
        controller.adapter.meeting_service.Join.assert_called_once()
        
        # Cleanup
        # no need to cleanup since we already hit error
        # controller.cleanup() will be called by the bot controller
        bot_thread.join(timeout=5)
        
        # Close the database connection since we're in a thread
        connection.close()

    @patch('bots.zoom_bot_adapter.video_input_manager.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    def test_bot_can_handle_meeting_failed_blocked_by_admin(self, MockStreamingUploader, mock_jwt, mock_zoom_sdk_adapter, mock_zoom_sdk_video):
        # Configure the mock class to return our mock instance
        mock_uploader = create_mock_streaming_uploader()
        MockStreamingUploader.return_value = mock_uploader
        
        # Mock the JWT token generation
        mock_jwt.encode.return_value = "fake_jwt_token"
        
        # Create bot controller
        controller = BotController(self.bot.id)
        
        # Run the bot in a separate thread since it has an event loop
        bot_thread = threading.Thread(target=controller.run)
        bot_thread.daemon = True
        bot_thread.start()
        
        def simulate_meeting_failed_flow():
            # Simulate successful auth            
            controller.adapter.auth_event.onAuthenticationReturnCallback(mock_zoom_sdk_adapter.AUTHRET_SUCCESS)
            # Simulate meeting failed status with blocked by admin code
            controller.adapter.meeting_service_event.onMeetingStatusChangedCallback(
                mock_zoom_sdk_adapter.MEETING_STATUS_FAILED,
                mock_zoom_sdk_adapter.MeetingFailCode.MEETING_FAIL_BLOCKED_BY_ACCOUNT_ADMIN
            )
            # Clean up connections in thread
            connection.close()
        
        # Run join flow simulation after a short delay
        threading.Timer(2, simulate_meeting_failed_flow).start()
        
        # Give the bot some time to process
        bot_thread.join(timeout=10)
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()
        
        # Check the bot events
        bot_events = self.bot.bot_events.all()
        self.assertEqual(len(bot_events), 2)
        join_requested_event = bot_events[0]
        could_not_join_event = bot_events[1]

        # Verify join_requested_event properties
        self.assertEqual(join_requested_event.event_type, BotEventTypes.JOIN_REQUESTED)
        self.assertEqual(join_requested_event.old_state, BotStates.READY)
        self.assertEqual(join_requested_event.new_state, BotStates.JOINING)
        self.assertIsNone(join_requested_event.event_sub_type)
        self.assertEqual(join_requested_event.metadata, {})
        self.assertIsNotNone(join_requested_event.requested_bot_action_taken_at)

        # Verify could_not_join_event properties
        self.assertEqual(could_not_join_event.event_type, BotEventTypes.COULD_NOT_JOIN)
        self.assertEqual(could_not_join_event.old_state, BotStates.JOINING)
        self.assertEqual(could_not_join_event.new_state, BotStates.FATAL_ERROR)
        self.assertEqual(could_not_join_event.event_sub_type, BotEventSubTypes.COULD_NOT_JOIN_MEETING_ZOOM_MEETING_STATUS_FAILED)
        self.assertEqual(could_not_join_event.metadata, {'zoom_result_code': mock_zoom_sdk_adapter.MeetingFailCode.MEETING_FAIL_BLOCKED_BY_ACCOUNT_ADMIN})
        self.assertIsNone(could_not_join_event.requested_bot_action_taken_at)

        # Verify expected SDK calls
        mock_zoom_sdk_adapter.InitSDK.assert_called_once()
        mock_zoom_sdk_adapter.CreateMeetingService.assert_called_once()
        mock_zoom_sdk_adapter.CreateAuthService.assert_called_once()
        controller.adapter.meeting_service.Join.assert_called_once()
        
        # Cleanup
        # no need to cleanup since we already hit error
        # controller.cleanup() will be called by the bot controller
        bot_thread.join(timeout=5)
        
        # Close the database connection since we're in a thread
        connection.close()

    @patch('bots.zoom_bot_adapter.video_input_manager.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    @patch('deepgram.DeepgramClient')
    def test_bot_handles_rtmp_connection_failure(self, MockDeepgramClient, MockStreamingUploader, mock_jwt, mock_zoom_sdk_adapter, mock_zoom_sdk_video):
        # Set up Deepgram mock
        MockDeepgramClient.return_value = create_mock_deepgram()
        
        # Configure the mock uploader
        mock_uploader = create_mock_streaming_uploader()
        MockStreamingUploader.return_value = mock_uploader
        
        # Mock the JWT token generation
        mock_jwt.encode.return_value = "fake_jwt_token"
        
        # Set RTMP URL for the bot
        self.bot.settings = {
            "rtmp_settings": {
                "destination_url": "rtmp://example.com/live/stream",
                "stream_key": "1234"
            }
        }
        self.bot.save()

        # Create bot controller
        controller = BotController(self.bot.id)
        
        # Run the bot in a separate thread since it has an event loop
        bot_thread = threading.Thread(target=controller.run)
        bot_thread.daemon = True
        bot_thread.start()

        def simulate_join_flow():
            adapter = controller.adapter
            # Simulate successful auth            
            adapter.auth_event.onAuthenticationReturnCallback(mock_zoom_sdk_adapter.AUTHRET_SUCCESS)

            # Simulate connecting
            adapter.meeting_service_event.onMeetingStatusChangedCallback(
                mock_zoom_sdk_adapter.MEETING_STATUS_CONNECTING, 
                mock_zoom_sdk_adapter.SDKERR_SUCCESS
            )
            
            # Simulate successful join
            adapter.meeting_service_event.onMeetingStatusChangedCallback(
                mock_zoom_sdk_adapter.MEETING_STATUS_INMEETING, 
                mock_zoom_sdk_adapter.SDKERR_SUCCESS
            )

            # Wait for the video input manager to be set up
            time.sleep(2)

            # Send a bunch of frames to the bot it takes some time to recognize the rtmp failure
            for i in range(5):
                # Simulate video frame received
                adapter.video_input_manager.input_streams[0].renderer_delegate.onRawDataFrameReceivedCallback(
                    MockVideoFrame()
                )

                # Simulate audio frame received
                adapter.audio_source.onOneWayAudioRawDataReceivedCallback(
                    MockAudioFrame(),
                    2  # Simulated participant ID that's not the bot
                )
                adapter.audio_source.onMixedAudioRawDataReceivedCallback(MockAudioFrame())

                time.sleep(5.0)

            # Error will be triggered because the rtmp url we gave was bad
            # This will trigger the GStreamer pipeline to send a message to the bot
            connection.close()
        
        # Run join flow simulation after a short delay
        threading.Timer(3, simulate_join_flow).start()
        
        # Give the bot some time to process
        bot_thread.join(timeout=40)
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()

        # Assert that the bot is in the FATAL_ERROR state
        self.assertEqual(self.bot.state, BotStates.FATAL_ERROR)
        
        # Verify bot events in sequence
        bot_events = self.bot.bot_events.all()
        self.assertEqual(len(bot_events), 4)  # We expect 4 events in total

        # Verify join_requested_event (Event 1)
        join_requested_event = bot_events[0]
        self.assertEqual(join_requested_event.event_type, BotEventTypes.JOIN_REQUESTED)
        self.assertEqual(join_requested_event.old_state, BotStates.READY)
        self.assertEqual(join_requested_event.new_state, BotStates.JOINING)
        self.assertIsNone(join_requested_event.event_sub_type)
        self.assertEqual(join_requested_event.metadata, {})
        self.assertIsNotNone(join_requested_event.requested_bot_action_taken_at)

        # Verify bot_joined_meeting_event (Event 2)
        bot_joined_meeting_event = bot_events[1]
        self.assertEqual(bot_joined_meeting_event.event_type, BotEventTypes.BOT_JOINED_MEETING)
        self.assertEqual(bot_joined_meeting_event.old_state, BotStates.JOINING)
        self.assertEqual(bot_joined_meeting_event.new_state, BotStates.JOINED_NOT_RECORDING)
        self.assertIsNone(bot_joined_meeting_event.event_sub_type)
        self.assertEqual(bot_joined_meeting_event.metadata, {})
        self.assertIsNone(bot_joined_meeting_event.requested_bot_action_taken_at)

        # Verify recording_permission_granted_event (Event 3)
        recording_permission_granted_event = bot_events[2]
        self.assertEqual(recording_permission_granted_event.event_type, BotEventTypes.BOT_RECORDING_PERMISSION_GRANTED)
        self.assertEqual(recording_permission_granted_event.old_state, BotStates.JOINED_NOT_RECORDING)
        self.assertEqual(recording_permission_granted_event.new_state, BotStates.JOINED_RECORDING)
        self.assertIsNone(recording_permission_granted_event.event_sub_type)
        self.assertEqual(recording_permission_granted_event.metadata, {})
        self.assertIsNone(recording_permission_granted_event.requested_bot_action_taken_at)

        # Verify fatal_error_event (Event 4)
        fatal_error_event = bot_events[3]
        self.assertEqual(fatal_error_event.event_type, BotEventTypes.FATAL_ERROR)
        self.assertEqual(fatal_error_event.old_state, BotStates.JOINED_RECORDING)
        self.assertEqual(fatal_error_event.new_state, BotStates.FATAL_ERROR)
        self.assertEqual(fatal_error_event.event_sub_type, BotEventSubTypes.FATAL_ERROR_RTMP_CONNECTION_FAILED)
        self.assertEqual(fatal_error_event.metadata, {"rtmp_destination_url": "rtmp://example.com/live/stream/1234"})

    @patch('bots.zoom_bot_adapter.video_input_manager.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.zoom', new_callable=create_mock_zoom_sdk)
    @patch('bots.zoom_bot_adapter.zoom_bot_adapter.jwt')
    @patch('bots.bot_controller.bot_controller.StreamingUploader')
    def test_bot_can_handle_zoom_sdk_internal_error(self, MockStreamingUploader, mock_jwt, mock_zoom_sdk_adapter, mock_zoom_sdk_video):
        # Configure the mock class to return our mock instance
        mock_uploader = create_mock_streaming_uploader()
        MockStreamingUploader.return_value = mock_uploader
        
        # Mock the JWT token generation
        mock_jwt.encode.return_value = "fake_jwt_token"
        
        # Configure the auth service to return an error
        mock_zoom_sdk_adapter.CreateAuthService.return_value.SDKAuth.return_value = mock_zoom_sdk_adapter.SDKError.SDKERR_INTERNAL_ERROR
        
        # Create bot controller
        controller = BotController(self.bot.id)
        
        # Run the bot in a separate thread since it has an event loop
        bot_thread = threading.Thread(target=controller.run)
        bot_thread.daemon = True
        bot_thread.start()
        
        # Give the bot some time to process
        bot_thread.join(timeout=10)
        
        # Refresh the bot from the database
        self.bot.refresh_from_db()
        
        # Check the bot events
        bot_events = self.bot.bot_events.all()
        self.assertEqual(len(bot_events), 2)
        join_requested_event = bot_events[0]
        could_not_join_event = bot_events[1]

        # Verify join_requested_event properties
        self.assertEqual(join_requested_event.event_type, BotEventTypes.JOIN_REQUESTED)
        self.assertEqual(join_requested_event.old_state, BotStates.READY)
        self.assertEqual(join_requested_event.new_state, BotStates.JOINING)
        self.assertIsNone(join_requested_event.event_sub_type)
        self.assertEqual(join_requested_event.metadata, {})
        self.assertIsNotNone(join_requested_event.requested_bot_action_taken_at)

        # Verify could_not_join_event properties
        self.assertEqual(could_not_join_event.event_type, BotEventTypes.COULD_NOT_JOIN)
        self.assertEqual(could_not_join_event.old_state, BotStates.JOINING)
        self.assertEqual(could_not_join_event.new_state, BotStates.FATAL_ERROR)
        self.assertEqual(could_not_join_event.event_sub_type, BotEventSubTypes.COULD_NOT_JOIN_MEETING_ZOOM_SDK_INTERNAL_ERROR)
        self.assertEqual(could_not_join_event.metadata, {"zoom_result_code": mock_zoom_sdk_adapter.SDKError.SDKERR_INTERNAL_ERROR})
        self.assertIsNone(could_not_join_event.requested_bot_action_taken_at)

        # Verify expected SDK calls
        mock_zoom_sdk_adapter.InitSDK.assert_called_once()
        mock_zoom_sdk_adapter.CreateMeetingService.assert_called_once()
        mock_zoom_sdk_adapter.CreateAuthService.assert_called_once()
        controller.adapter.meeting_service.Join.assert_not_called()
        
        # Cleanup
        # no need to cleanup since we already hit error
        # controller.cleanup() will be called by the bot controller
        bot_thread.join(timeout=5)
        
        # Close the database connection since we're in a thread
        connection.close()