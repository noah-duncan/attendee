import os
import threading
import time
from unittest.mock import MagicMock, call, patch

import kubernetes
import numpy as np
from django.db import connection
from django.test.testcases import TransactionTestCase
from django.utils import timezone

from bots.bot_adapter import BotAdapter
from bots.bot_controller import BotController
from bots.models import (
    Bot,
    BotEventManager,
    BotEventSubTypes,
    BotEventTypes,
    BotStates,
    CreditTransaction,
    Organization,
    Project,
    Recording,
    RecordingStates,
    RecordingTypes,
    TranscriptionProviders,
    TranscriptionTypes,
    Utterance,
)

from .mock_data import MockF32AudioFrame


def create_mock_file_uploader():
    mock_file_uploader = MagicMock()
    mock_file_uploader.upload_file.return_value = None
    mock_file_uploader.wait_for_upload.return_value = None
    mock_file_uploader.delete_file.return_value = None
    mock_file_uploader.key = "test-recording-key"
    return mock_file_uploader


def create_mock_google_meet_driver():
    mock_driver = MagicMock()
    mock_driver.set_window_size.return_value = None
    mock_driver.execute_script.side_effect = [
        None,  # First call (window.ws.enableMediaSending())
        12345,  # Second call (performance.timeOrigin)
    ]
    mock_driver.save_screenshot.return_value = None
    return mock_driver


class TestGoogleMeetBot(TransactionTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Set required environment variables
        os.environ["AWS_RECORDING_STORAGE_BUCKET_NAME"] = "test-bucket"
        os.environ["CHARGE_CREDITS_FOR_BOTS"] = "false"

    def setUp(self):
        # Recreate organization and project for each test
        self.organization = Organization.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Test Project", organization=self.organization)

        # Create a bot for each test
        self.bot = Bot.objects.create(
            project=self.project,
            name="Test Bot",
            meeting_url="https://meet.google.com/abc-defg-hij",
        )

        # Create default recording
        self.recording = Recording.objects.create(
            bot=self.bot,
            recording_type=RecordingTypes.AUDIO_AND_VIDEO,
            transcription_type=TranscriptionTypes.NON_REALTIME,
            transcription_provider=TranscriptionProviders.DEEPGRAM,
            is_default_recording=True,
        )

        # Try to transition the state from READY to JOINING
        BotEventManager.create_event(self.bot, BotEventTypes.JOIN_REQUESTED)

        # Configure Celery to run tasks eagerly (synchronously)
        from django.conf import settings

        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = True

    @patch("bots.web_bot_adapter.web_bot_adapter.Display")
    @patch("bots.web_bot_adapter.web_bot_adapter.uc.Chrome")
    @patch("bots.bot_controller.bot_controller.FileUploader")
    def test_google_meet_bot_can_join_meeting_and_record_audio_and_video(
        self,
        MockFileUploader,
        MockChromeDriver,
        MockDisplay,
    ):
        # Configure the mock uploader
        mock_uploader = create_mock_file_uploader()
        MockFileUploader.return_value = mock_uploader

        # Mock the Chrome driver
        mock_driver = create_mock_google_meet_driver()
        MockChromeDriver.return_value = mock_driver

        # Mock virtual display
        mock_display = MagicMock()
        MockDisplay.return_value = mock_display

        # Create bot controller
        controller = BotController(self.bot.id)

        # Run the bot in a separate thread since it has an event loop
        bot_thread = threading.Thread(target=controller.run)
        bot_thread.daemon = True
        bot_thread.start()

        def simulate_join_flow():
            # Sleep to allow initialization
            time.sleep(2)

            # Add participants - simulate websocket message processing
            controller.adapter.participants_info["user1"] = {"deviceId": "user1", "fullName": "Test User", "active": True}

            # Simulate audio data arrival - fake a float32 array of 1000 samples
            # Create a mock audio message in the format expected by process_audio_frame
            mock_audio_message = bytearray()
            # Add message type (3 for AUDIO) as first 4 bytes
            mock_audio_message.extend((3).to_bytes(4, byteorder="little"))
            # Add timestamp (12345) as next 8 bytes
            mock_audio_message.extend((12345).to_bytes(8, byteorder="little"))
            # Add stream ID (0) as next 4 bytes
            mock_audio_message.extend((0).to_bytes(4, byteorder="little"))
            # Add mock audio data (1000 float32 samples)
            mock_audio_message.extend(MockF32AudioFrame().GetBuffer())

            controller.adapter.process_audio_frame(mock_audio_message)

            # Simulate video data arrival
            # Create a mock video message in the format expected by process_video_frame
            mock_video_frame = create_mock_video_frame()
            controller.adapter.process_video_frame(mock_video_frame)

            # Simulate caption data arrival
            caption_data = {"captionId": "caption1", "deviceId": "user1", "text": "This is a test caption"}
            controller.closed_caption_manager.upsert_caption(caption_data)

            # Process these events
            time.sleep(2)

            # Simulate flushing captions - normally done before leaving
            controller.closed_caption_manager.flush_captions()

            # Simulate meeting ended
            controller.on_message_from_adapter({"message": BotAdapter.Messages.MEETING_ENDED})

            # Clean up connections in thread
            connection.close()

        # Run join flow simulation after a short delay
        threading.Timer(2, simulate_join_flow).start()

        # Give the bot some time to process
        bot_thread.join(timeout=10)

        # Refresh the bot from the database
        self.bot.refresh_from_db()

        # Assert that the heartbeat timestamp was set
        self.assertIsNotNone(self.bot.first_heartbeat_timestamp)
        self.assertIsNotNone(self.bot.last_heartbeat_timestamp)

        # Assert that the bot is in the ENDED state
        self.assertEqual(self.bot.state, BotStates.ENDED)

        # Verify bot events in sequence
        bot_events = self.bot.bot_events.all()
        self.assertEqual(len(bot_events), 5)  # We expect 5 events in total

        # Verify join_requested_event (Event 1)
        join_requested_event = bot_events[0]
        self.assertEqual(join_requested_event.event_type, BotEventTypes.JOIN_REQUESTED)
        self.assertEqual(join_requested_event.old_state, BotStates.READY)
        self.assertEqual(join_requested_event.new_state, BotStates.JOINING)

        # Verify bot_joined_meeting_event (Event 2)
        bot_joined_meeting_event = bot_events[1]
        self.assertEqual(bot_joined_meeting_event.event_type, BotEventTypes.BOT_JOINED_MEETING)
        self.assertEqual(bot_joined_meeting_event.old_state, BotStates.JOINING)
        self.assertEqual(bot_joined_meeting_event.new_state, BotStates.JOINED_NOT_RECORDING)

        # Verify recording_permission_granted_event (Event 3)
        recording_permission_granted_event = bot_events[2]
        self.assertEqual(
            recording_permission_granted_event.event_type,
            BotEventTypes.BOT_RECORDING_PERMISSION_GRANTED,
        )
        self.assertEqual(recording_permission_granted_event.old_state, BotStates.JOINED_NOT_RECORDING)
        self.assertEqual(recording_permission_granted_event.new_state, BotStates.JOINED_RECORDING)

        # Verify meeting_ended_event (Event 4)
        meeting_ended_event = bot_events[3]
        self.assertEqual(meeting_ended_event.event_type, BotEventTypes.MEETING_ENDED)
        self.assertEqual(meeting_ended_event.old_state, BotStates.JOINED_RECORDING)
        self.assertEqual(meeting_ended_event.new_state, BotStates.POST_PROCESSING)

        # Verify post_processing_completed_event (Event 5)
        post_processing_completed_event = bot_events[4]
        self.assertEqual(post_processing_completed_event.event_type, BotEventTypes.POST_PROCESSING_COMPLETED)
        self.assertEqual(post_processing_completed_event.old_state, BotStates.POST_PROCESSING)
        self.assertEqual(post_processing_completed_event.new_state, BotStates.ENDED)

        # Verify that the recording was finished
        self.recording.refresh_from_db()
        self.assertEqual(self.recording.state, RecordingStates.COMPLETE)

        # Verify captions were processed
        utterances = Utterance.objects.filter(recording=self.recording)
        self.assertGreater(utterances.count(), 0)

        # Verify a caption utterance exists with the correct text
        caption_utterance = utterances.filter(source=Utterance.Sources.CLOSED_CAPTION_FROM_PLATFORM).first()
        self.assertIsNotNone(caption_utterance)
        self.assertEqual(caption_utterance.transcription.get("transcript"), "This is a test caption")

        # Verify driver was set up with the correct window size
        mock_driver.set_window_size.assert_called_with(1920 / 2, 1080 / 2)

        # Verify WebSocket media sending was enabled and performance.timeOrigin was queried
        mock_driver.execute_script.assert_has_calls([call("window.ws?.enableMediaSending();"), call("return performance.timeOrigin;")])

        # Verify first_buffer_timestamp_ms_offset was set correctly
        self.assertEqual(controller.adapter.get_first_buffer_timestamp_ms_offset(), 12345)

        # Verify that no charge was created (since the env var is not set in this test suite)
        credit_transaction = CreditTransaction.objects.filter(bot=self.bot).first()
        self.assertIsNone(credit_transaction, "A credit transaction was created for the bot")

        # Verify file uploader was used
        mock_uploader.upload_file.assert_called_once()
        self.assertGreater(mock_uploader.upload_file.call_count, 0)
        mock_uploader.wait_for_upload.assert_called_once()
        mock_uploader.delete_file.assert_called_once()
        # Cleanup
        controller.cleanup()
        bot_thread.join(timeout=5)

        # Close the database connection since we're in a thread
        connection.close()

    @patch("kubernetes.client.CoreV1Api")
    @patch("kubernetes.config.load_incluster_config")
    @patch("kubernetes.config.load_kube_config")
    def test_terminate_bots_with_heartbeat_timeout(self, mock_load_kube_config, mock_load_incluster_config, MockCoreV1Api):
        # Set up mock Kubernetes API
        mock_k8s_api = MagicMock()
        MockCoreV1Api.return_value = mock_k8s_api

        # Set up config.load_incluster_config to raise ConfigException so load_kube_config gets called
        mock_load_incluster_config.side_effect = kubernetes.config.config_exception.ConfigException("Mock ConfigException")

        # Create a bot with a stale heartbeat (more than 10 minutes old)
        current_time = int(timezone.now().timestamp())
        eleven_minutes_ago = current_time - 660  # 11 minutes ago

        # Set the bot's heartbeat timestamps
        self.bot.first_heartbeat_timestamp = eleven_minutes_ago
        self.bot.last_heartbeat_timestamp = eleven_minutes_ago
        self.bot.state = BotStates.JOINED_RECORDING  # Set to a non-terminal state
        self.bot.save()

        # Set bot launch method to kubernetes
        with patch.dict(os.environ, {"LAUNCH_BOT_METHOD": "kubernetes"}):
            # Import and run the command
            from bots.management.commands.terminate_bots_with_heartbeat_timeout import Command

            command = Command()
            command.handle()

        # Refresh the bot state from the database
        self.bot.refresh_from_db()

        # Verify the bot was moved to FATAL_ERROR state
        self.assertEqual(self.bot.state, BotStates.FATAL_ERROR)

        # Verify that a FATAL_ERROR event was created with the correct sub type
        fatal_error_event = self.bot.bot_events.filter(event_type=BotEventTypes.FATAL_ERROR, event_sub_type=BotEventSubTypes.FATAL_ERROR_HEARTBEAT_TIMEOUT).first()
        self.assertIsNotNone(fatal_error_event)
        self.assertEqual(fatal_error_event.old_state, BotStates.JOINED_RECORDING)
        self.assertEqual(fatal_error_event.new_state, BotStates.FATAL_ERROR)

        # Verify Kubernetes pod deletion was attempted with the correct pod name
        pod_name = self.bot.k8s_pod_name()
        mock_k8s_api.delete_namespaced_pod.assert_called_once_with(name=pod_name, namespace="attendee", grace_period_seconds=0)

    def test_bots_with_recent_heartbeat_not_terminated(self):
        # Create a bot with a recent heartbeat (9 minutes old)
        current_time = int(timezone.now().timestamp())
        nine_minutes_ago = current_time - 540  # 9 minutes ago

        # Set the bot's heartbeat timestamps
        self.bot.first_heartbeat_timestamp = nine_minutes_ago
        self.bot.last_heartbeat_timestamp = nine_minutes_ago
        self.bot.state = BotStates.JOINED_RECORDING  # Set to a non-terminal state
        self.bot.save()

        # Import and run the command
        from bots.management.commands.terminate_bots_with_heartbeat_timeout import Command

        command = Command()
        command.handle()

        # Refresh the bot state from the database
        self.bot.refresh_from_db()

        # Verify the bot was NOT moved to FATAL_ERROR state
        self.assertEqual(self.bot.state, BotStates.JOINED_RECORDING)

        # Verify that no FATAL_ERROR event was created with heartbeat timeout subtype
        fatal_error_event = self.bot.bot_events.filter(event_type=BotEventTypes.FATAL_ERROR, event_sub_type=BotEventSubTypes.FATAL_ERROR_HEARTBEAT_TIMEOUT).first()
        self.assertIsNone(fatal_error_event)


# Simulate video data arrival
# Create a mock video message in the format expected by process_video_frame
def create_mock_video_frame(width=640, height=480):
    # Create a bytearray for the message
    mock_video_message = bytearray()

    # Add message type (2 for VIDEO) as first 4 bytes
    mock_video_message.extend((2).to_bytes(4, byteorder="little"))

    # Add timestamp (12345) as next 8 bytes
    mock_video_message.extend((12345).to_bytes(8, byteorder="little"))

    # Add stream ID length (4) and stream ID ("main") - total 8 bytes
    stream_id = "main"
    mock_video_message.extend(len(stream_id).to_bytes(4, byteorder="little"))
    mock_video_message.extend(stream_id.encode("utf-8"))

    # Add width and height - 8 bytes
    mock_video_message.extend(width.to_bytes(4, byteorder="little"))
    mock_video_message.extend(height.to_bytes(4, byteorder="little"))

    # Create I420 frame data (Y, U, V planes)
    # Y plane: width * height bytes
    y_plane_size = width * height
    y_plane = np.ones(y_plane_size, dtype=np.uint8) * 128  # mid-gray

    # U and V planes: (width//2 * height//2) bytes each
    uv_width = (width + 1) // 2  # half_ceil implementation
    uv_height = (height + 1) // 2
    uv_plane_size = uv_width * uv_height

    u_plane = np.ones(uv_plane_size, dtype=np.uint8) * 128  # no color tint
    v_plane = np.ones(uv_plane_size, dtype=np.uint8) * 128  # no color tint

    # Add the frame data to the message
    mock_video_message.extend(y_plane.tobytes())
    mock_video_message.extend(u_plane.tobytes())
    mock_video_message.extend(v_plane.tobytes())

    return mock_video_message
