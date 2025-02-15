from bots.models import *
from .individual_audio_input_manager import IndividualAudioInputManager
from .audio_output_manager import AudioOutputManager
from .streaming_uploader import StreamingUploader
from .closed_caption_manager import ClosedCaptionManager
import os
import signal
import redis
from bots.bot_adapter import BotAdapter
from .gstreamer_pipeline import GstreamerPipeline
from .rtmp_client import RTMPClient
from django.core.files.base import ContentFile
from .pipeline_configuration import PipelineConfiguration
import traceback

import gi
gi.require_version('GLib', '2.0')
from gi.repository import GLib

class BotController:
    MEETING_TYPE_ZOOM = "zoom"
    MEETING_TYPE_GOOGLE_MEET = "google_meet"

    def get_google_meet_bot_adapter(self):
        from bots.google_meet_bot_adapter import GoogleMeetBotAdapter

        return GoogleMeetBotAdapter(
            display_name=self.bot_in_db.name,
            send_message_callback=self.on_message_from_adapter,
            meeting_url=self.bot_in_db.meeting_url,
            add_video_frame_callback=self.gstreamer_pipeline.on_new_video_frame,
            wants_any_video_frames_callback=self.gstreamer_pipeline.wants_any_video_frames,
            add_mixed_audio_chunk_callback=self.gstreamer_pipeline.on_mixed_audio_raw_data_received_callback,
            upsert_caption_callback=self.closed_caption_manager.upsert_caption
        )

    def get_zoom_bot_adapter(self):
        from bots.zoom_bot_adapter import ZoomBotAdapter

        zoom_oauth_credentials_record = self.bot_in_db.project.credentials.filter(credential_type=Credentials.CredentialTypes.ZOOM_OAUTH).first()
        if not zoom_oauth_credentials_record:
            raise Exception("Zoom OAuth credentials not found")

        zoom_oauth_credentials = zoom_oauth_credentials_record.get_credentials()
        if not zoom_oauth_credentials:
            raise Exception("Zoom OAuth credentials data not found")
        
        return ZoomBotAdapter(
            use_one_way_audio=self.pipeline_configuration.transcribe_audio,
            use_mixed_audio=self.pipeline_configuration.record_audio or self.pipeline_configuration.rtmp_stream_audio,
            use_video=self.pipeline_configuration.record_video or self.pipeline_configuration.rtmp_stream_video,
            display_name=self.bot_in_db.name,
            send_message_callback=self.on_message_from_adapter,
            add_audio_chunk_callback=self.individual_audio_input_manager.add_chunk,
            zoom_client_id=zoom_oauth_credentials['client_id'],
            zoom_client_secret=zoom_oauth_credentials['client_secret'],
            meeting_url=self.bot_in_db.meeting_url,
            add_video_frame_callback=self.gstreamer_pipeline.on_new_video_frame,
            wants_any_video_frames_callback=self.gstreamer_pipeline.wants_any_video_frames,
            add_mixed_audio_chunk_callback=self.gstreamer_pipeline.on_mixed_audio_raw_data_received_callback
        )

    def get_meeting_type(self):
        if "zoom.us" in self.bot_in_db.meeting_url:
            return self.MEETING_TYPE_ZOOM
        elif "meet.google.com" in self.bot_in_db.meeting_url:
            return self.MEETING_TYPE_GOOGLE_MEET
        else:
            raise Exception(f"Unknown meeting type: {self.bot_in_db.meeting_type}")

    def get_audio_format(self):
        meeting_type = self.get_meeting_type()
        if meeting_type == self.MEETING_TYPE_ZOOM:
            return GstreamerPipeline.AUDIO_FORMAT_PCM
        elif meeting_type == self.MEETING_TYPE_GOOGLE_MEET:
            return GstreamerPipeline.AUDIO_FORMAT_FLOAT

    def get_bot_adapter(self):
        meeting_type = self.get_meeting_type()
        if meeting_type == self.MEETING_TYPE_ZOOM:
            return self.get_zoom_bot_adapter()
        elif meeting_type == self.MEETING_TYPE_GOOGLE_MEET:
            return self.get_google_meet_bot_adapter()
    
    def get_first_buffer_timestamp_ms(self):
        if self.gstreamer_pipeline.start_time_ns is None:
            return None
        return int(self.gstreamer_pipeline.start_time_ns / 1_000_000) + self.adapter.get_first_buffer_timestamp_ms_offset()

    def recording_file_saved(self, s3_storage_key):
        recording = Recording.objects.get(bot=self.bot_in_db, is_default_recording=True)
        recording.file = s3_storage_key
        recording.first_buffer_timestamp_ms = self.get_first_buffer_timestamp_ms()
        recording.save()

    def get_recording_filename(self):
        recording = Recording.objects.get(bot=self.bot_in_db, is_default_recording=True)
        return f"{hashlib.md5(recording.object_id.encode()).hexdigest()}.mp4"
    
    def on_rtmp_connection_failed(self):
        print("RTMP connection failed")
        BotEventManager.create_event(
            bot=self.bot_in_db,
            event_type=BotEventTypes.FATAL_ERROR,
            event_sub_type=BotEventSubTypes.FATAL_ERROR_RTMP_CONNECTION_FAILED,
            event_metadata={"rtmp_destination_url": self.bot_in_db.rtmp_destination_url()}
        )
        self.cleanup()

    def on_new_sample_from_gstreamer_pipeline(self, data):
        # For now, we'll assume that if rtmp streaming is enabled, we don't need to upload to s3
        if self.rtmp_client:
            write_succeeded = self.rtmp_client.write_data(data)
            if not write_succeeded:
                GLib.idle_add(lambda: self.on_rtmp_connection_failed())
        else:
            self.streaming_uploader.upload_part(data)

    def cleanup(self):
        if self.cleanup_called:
            print("Cleanup already called, exiting")
            return
        self.cleanup_called = True

        normal_quitting_process_worked = False
        import threading
        def terminate_worker():
            import time
            time.sleep(20)
            if normal_quitting_process_worked:
                print("Normal quitting process worked, not force terminating worker")
                return
            print("Terminating worker with hard timeout...")
            os.kill(os.getpid(), signal.SIGKILL)  # Force terminate the worker process
        
        termination_thread = threading.Thread(target=terminate_worker, daemon=True)
        termination_thread.start()

        if self.gstreamer_pipeline:
            print("Telling gstreamer pipeline to cleanup...")
            self.gstreamer_pipeline.cleanup()

        if self.streaming_uploader:
            print("Telling streaming uploader to cleanup...")
            self.streaming_uploader.complete_upload()
            self.recording_file_saved(self.streaming_uploader.key)

        if self.rtmp_client:
            print("Telling rtmp client to cleanup...")
            self.rtmp_client.stop()

        if self.adapter:
            print("Telling adapter to leave meeting...")
            self.adapter.leave()
            print("Telling adapter to cleanup...")
            self.adapter.cleanup()

        if self.main_loop and self.main_loop.is_running():
            self.main_loop.quit()

        normal_quitting_process_worked = True

    def __init__(self, bot_id):
        self.bot_in_db = Bot.objects.get(id=bot_id)
        self.cleanup_called = False
        self.run_called = False

        if self.bot_in_db.rtmp_destination_url():
            self.pipeline_configuration = PipelineConfiguration.rtmp_streaming_bot()
        else:
            self.pipeline_configuration = PipelineConfiguration.recorder_bot()

    def run(self):
        if self.run_called:
            raise Exception("Run already called, exiting")
        self.run_called = True

        redis_url = os.getenv('REDIS_URL') + ("?ssl_cert_reqs=none" if os.getenv('DISABLE_REDIS_SSL') else "")
        redis_client = redis.from_url(redis_url)
        pubsub = redis_client.pubsub()
        channel = f"bot_{self.bot_in_db.id}"
        pubsub.subscribe(channel)

        # Initialize core objects
        # Only used for adapters that can provider per-participant audio
        self.individual_audio_input_manager = IndividualAudioInputManager(save_utterance_callback=self.save_individual_audio_utterance, get_participant_callback=self.get_participant)
        self.closed_caption_manager = ClosedCaptionManager(save_utterance_callback=self.save_closed_caption_utterance, get_participant_callback=self.get_participant)

        gstreamer_output_format = GstreamerPipeline.OUTPUT_FORMAT_MP4
        self.rtmp_client = None
        if self.pipeline_configuration.rtmp_stream_audio or self.pipeline_configuration.rtmp_stream_video:
            gstreamer_output_format = GstreamerPipeline.OUTPUT_FORMAT_FLV
            self.rtmp_client = RTMPClient(rtmp_url=self.bot_in_db.rtmp_destination_url())
            self.rtmp_client.start()
        
        self.gstreamer_pipeline = GstreamerPipeline(
            on_new_sample_callback=self.on_new_sample_from_gstreamer_pipeline, 
            video_frame_size=(1920, 1080), 
            audio_format=self.get_audio_format(), 
            output_format=gstreamer_output_format
        )
        self.gstreamer_pipeline.setup()
        
        self.streaming_uploader = StreamingUploader(os.environ.get('AWS_RECORDING_STORAGE_BUCKET_NAME'), self.get_recording_filename())
        self.streaming_uploader.start_upload()

        self.adapter = self.get_bot_adapter()

        self.audio_output_manager = AudioOutputManager(currently_playing_audio_media_request_finished_callback=self.currently_playing_audio_media_request_finished, play_raw_audio_callback=self.adapter.send_raw_audio)

        # Create GLib main loop
        self.main_loop = GLib.MainLoop()
        
        # Set up Redis listener in a separate thread
        import threading
        def redis_listener():
            while True:
                try:
                    message = pubsub.get_message(timeout=1.0)
                    if message:
                        # Schedule Redis message handling in the main GLib loop
                        GLib.idle_add(lambda: self.handle_redis_message(message))
                except Exception as e:
                    print(f"Error in Redis listener: {e}")
                    break

        redis_thread = threading.Thread(target=redis_listener, daemon=True)
        redis_thread.start()

        # Add timeout just for audio processing
        self.first_timeout_call = True
        GLib.timeout_add(100, self.on_main_loop_timeout)
        
        # Add signal handlers so that when we get a SIGTERM or SIGINT, we can clean up the bot
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGTERM, self.handle_glib_shutdown)
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, signal.SIGINT, self.handle_glib_shutdown)
        
        # Run the main loop
        try:
            self.main_loop.run()
        except Exception as e:
            print(f"Error in bot {self.bot_in_db.id}: {str(e)}")
            self.cleanup()
        finally:
            # Clean up Redis subscription
            pubsub.unsubscribe(channel)
            pubsub.close()

    def take_action_based_on_bot_in_db(self):
        if self.bot_in_db.state == BotStates.JOINING:
            print("take_action_based_on_bot_in_db - JOINING")
            BotEventManager.set_requested_bot_action_taken_at(self.bot_in_db)
            self.adapter.init()
        if self.bot_in_db.state == BotStates.LEAVING:
            print("take_action_based_on_bot_in_db - LEAVING")
            BotEventManager.set_requested_bot_action_taken_at(self.bot_in_db)
            self.adapter.leave()

    def get_participant(self, participant_id):
        return self.adapter.get_participant(participant_id)

    def currently_playing_audio_media_request_finished(self, audio_media_request):
        print("currently_playing_audio_media_request_finished called")
        BotMediaRequestManager.set_media_request_finished(audio_media_request)
        self.take_action_based_on_audio_media_requests_in_db()

    def take_action_based_on_audio_media_requests_in_db(self):
        media_type = BotMediaRequestMediaTypes.AUDIO
        oldest_enqueued_media_request = self.bot_in_db.media_requests.filter(state=BotMediaRequestStates.ENQUEUED, media_type=media_type).order_by('created_at').first()
        if not oldest_enqueued_media_request:
            return
        currently_playing_media_request = self.bot_in_db.media_requests.filter(state=BotMediaRequestStates.PLAYING, media_type=media_type).first()
        if currently_playing_media_request:
            print(f"Currently playing media request {currently_playing_media_request.id} so cannot play another media request")
            return
        
        try:
            BotMediaRequestManager.set_media_request_playing(oldest_enqueued_media_request)
            self.audio_output_manager.start_playing_audio_media_request(oldest_enqueued_media_request)
        except Exception as e:
            print(f"Error sending raw audio: {e}")
            BotMediaRequestManager.set_media_request_failed_to_play(oldest_enqueued_media_request)

    def take_action_based_on_image_media_requests_in_db(self):
        from bots.utils import png_to_yuv420_frame

        media_type = BotMediaRequestMediaTypes.IMAGE
        
        # Get all enqueued image media requests for this bot, ordered by creation time
        enqueued_requests = self.bot_in_db.media_requests.filter(
            state=BotMediaRequestStates.ENQUEUED,
            media_type=media_type
        ).order_by('created_at')

        if not enqueued_requests.exists():
            return

        # Get the most recently created request
        most_recent_request = enqueued_requests.last()
        
        # Mark the most recent request as FINISHED
        try:
            BotMediaRequestManager.set_media_request_playing(most_recent_request)
            self.adapter.send_raw_image(png_to_yuv420_frame(most_recent_request.media_blob.blob))
            BotMediaRequestManager.set_media_request_finished(most_recent_request)
        except Exception as e:
            print(f"Error sending raw image: {e}")
            BotMediaRequestManager.set_media_request_failed_to_play(most_recent_request)
        
        # Mark all other enqueued requests as DROPPED
        for request in enqueued_requests.exclude(id=most_recent_request.id):
            BotMediaRequestManager.set_media_request_dropped(request)

    def take_action_based_on_media_requests_in_db(self):
        self.take_action_based_on_audio_media_requests_in_db()
        self.take_action_based_on_image_media_requests_in_db()

    def handle_glib_shutdown(self):
        print("handle_glib_shutdown called")

        try:
            BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.FATAL_ERROR,
                event_sub_type=BotEventSubTypes.FATAL_ERROR_PROCESS_TERMINATED
            )
        except Exception as e:
            print(f"Error creating FATAL_ERROR event: {e}")

        self.cleanup()
        return False

    def handle_redis_message(self, message):
        if message and message['type'] == 'message':
            data = json.loads(message['data'].decode('utf-8'))
            command = data.get('command')
            
            if command == 'sync':
                print(f"Syncing bot {self.bot_in_db.object_id}")
                self.bot_in_db.refresh_from_db()
                self.take_action_based_on_bot_in_db()
            elif command == 'sync_media_requests':
                print(f"Syncing media requests for bot {self.bot_in_db.object_id}")
                self.bot_in_db.refresh_from_db()
                self.take_action_based_on_media_requests_in_db()
            else:
                print(f"Unknown command: {command}")

    def on_main_loop_timeout(self):
        try:            
            if self.first_timeout_call:
                print("First timeout call - taking initial action")
                self.bot_in_db.refresh_from_db()
                self.take_action_based_on_bot_in_db()
                self.first_timeout_call = False

            # Process audio chunks
            self.individual_audio_input_manager.process_chunks()

            # Process captions
            self.closed_caption_manager.process_captions()

            #Check if auto-leave conditions are met
            self.adapter.check_auto_leave_conditions()

            # Process audio output
            self.audio_output_manager.monitor_currently_playing_audio_media_request()
            return True
            
        except Exception as e:
            print(f"Error in timeout callback: {e}")
            print("Traceback:")
            traceback.print_exc()
            self.cleanup()
            return False

    def get_recording_in_progress(self):
        recordings_in_progress = Recording.objects.filter(bot=self.bot_in_db, state=RecordingStates.IN_PROGRESS)
        if recordings_in_progress.count() == 0:
            raise Exception("No recording in progress found")
        if recordings_in_progress.count() > 1:
            raise Exception(f"Expected at most one recording in progress for bot {self.bot_in_db.object_id}, but found {recordings_in_progress.count()}")
        return recordings_in_progress.first()

    def save_closed_caption_utterance(self, message):
        participant, _ = Participant.objects.get_or_create(
            bot=self.bot_in_db,
            uuid=message['participant_uuid'],
            defaults={
                'user_uuid': message['participant_user_uuid'],
                'full_name': message['participant_full_name'],
            }
        )

        # Create new utterance record
        recording_in_progress = self.get_recording_in_progress()
        source_uuid = f"{recording_in_progress.object_id}-{message['source_uuid_suffix']}"
        utterance, _ = Utterance.objects.update_or_create(
            recording=recording_in_progress,
            source_uuid=source_uuid,
            defaults={
                'source': Utterance.Sources.CLOSED_CAPTION_FROM_PLATFORM,
                'participant': participant,
                'transcription': {'transcript': message['text']},
                'timestamp_ms': message['timestamp_ms'],
                'duration_ms': message['duration_ms'],
            }
        )

        RecordingManager.set_recording_transcription_in_progress(recording_in_progress)

    def save_individual_audio_utterance(self, message):
        from bots.tasks.process_utterance_task import process_utterance

        print("Received message that new utterance was detected")

        # Create participant record if it doesn't exist
        participant, _ = Participant.objects.get_or_create(
            bot=self.bot_in_db,
            uuid=message['participant_uuid'],
            defaults={
                'user_uuid': message['participant_user_uuid'],
                'full_name': message['participant_full_name'],
            }
        )

        # Create new utterance record
        recording_in_progress = self.get_recording_in_progress()
        utterance = Utterance.objects.create(
            source=Utterance.Sources.PER_PARTICIPANT_AUDIO,
            recording=recording_in_progress,
            participant=participant,
            audio_blob=message['audio_data'],
            audio_format=Utterance.AudioFormat.PCM,
            timestamp_ms=message['timestamp_ms'],
            duration_ms=len(message['audio_data']) / 64,
        )

        # Process the utterance immediately
        process_utterance.delay(utterance.id)
        return

    def on_message_from_adapter(self, message):
        GLib.idle_add(lambda: self.take_action_based_on_message_from_adapter(message))

    def take_action_based_on_message_from_adapter(self, message):
        if message.get('message') == BotAdapter.Messages.REQUEST_TO_JOIN_DENIED:
            print("Received message that request to join was denied")
            BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.COULD_NOT_JOIN,
                event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_REQUEST_TO_JOIN_DENIED
            )
            self.cleanup()
            return

        if message.get('message') == BotAdapter.Messages.UI_ELEMENT_NOT_FOUND:
            print(f"Received message that UI element not found at {message.get('current_time')}")

            screenshot_available = message.get('screenshot_path') is not None

            new_bot_event = BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.FATAL_ERROR,
                event_sub_type=BotEventSubTypes.FATAL_ERROR_UI_ELEMENT_NOT_FOUND,
                event_metadata={
                        'step': message.get('step'),
                        'current_time': message.get('current_time').isoformat(),
                        'exception_type': message.get('exception_type'),
                        'exception_message': message.get('exception_message'),
                        'inner_exception_type': message.get('inner_exception_type'),
                        'inner_exception_message': message.get('inner_exception_message'),
                    }
            )

            if screenshot_available:
                # Create debug screenshot
                debug_screenshot = BotDebugScreenshot.objects.create(
                    bot_event=new_bot_event
                )
                
                # Read the file content from the path
                with open(message.get('screenshot_path'), 'rb') as f:
                    screenshot_content = f.read()
                    debug_screenshot.file.save('debug_screenshot.png', ContentFile(screenshot_content), save=True)
            
            self.cleanup()
            return


        if message.get('message') == BotAdapter.Messages.MEETING_ENDED:
            print("Received message that meeting ended")
            if self.individual_audio_input_manager:
                print("Flushing utterances...")
                self.individual_audio_input_manager.flush_utterances()
            if self.closed_caption_manager:
                print("Flushing captions...")
                self.closed_caption_manager.flush_captions()

            if self.bot_in_db.state == BotStates.LEAVING:
                BotEventManager.create_event(
                    bot=self.bot_in_db,
                    event_type=BotEventTypes.BOT_LEFT_MEETING
                )
            else:
                BotEventManager.create_event(
                    bot=self.bot_in_db,
                    event_type=BotEventTypes.MEETING_ENDED
                )
            self.cleanup()
            return

        if message.get('message') == BotAdapter.Messages.ZOOM_MEETING_STATUS_FAILED_UNABLE_TO_JOIN_EXTERNAL_MEETING:
            print(f"Received message that meeting status failed unable to join external meeting with zoom_result_code={message.get('zoom_result_code')}")
            BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.COULD_NOT_JOIN,
                event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_UNPUBLISHED_ZOOM_APP,
                event_metadata={"zoom_result_code": message.get('zoom_result_code')}
            )
            self.cleanup()
            return

        if message.get('message') == BotAdapter.Messages.ZOOM_MEETING_STATUS_FAILED:
            print(f"Received message that meeting status failed with zoom_result_code={message.get('zoom_result_code')}")
            BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.COULD_NOT_JOIN,
                event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_ZOOM_MEETING_STATUS_FAILED,
                event_metadata={"zoom_result_code": message.get('zoom_result_code')}
            )
            self.cleanup()
            return

        if message.get('message') == BotAdapter.Messages.ZOOM_AUTHORIZATION_FAILED:
            print(f"Received message that authorization failed with zoom_result_code={message.get('zoom_result_code')}")
            BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.COULD_NOT_JOIN,
                event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_ZOOM_AUTHORIZATION_FAILED,
                event_metadata={"zoom_result_code": message.get('zoom_result_code')}
            )
            self.cleanup()
            return

        if message.get('message') == BotAdapter.Messages.ZOOM_SDK_INTERNAL_ERROR:
            print(f"Received message that SDK internal error with zoom_result_code={message.get('zoom_result_code')}")
            BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.COULD_NOT_JOIN,
                event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_ZOOM_SDK_INTERNAL_ERROR,
                event_metadata={"zoom_result_code": message.get('zoom_result_code')}
            )
            self.cleanup()
            return

        if message.get('message') == BotAdapter.Messages.LEAVE_MEETING_WAITING_FOR_HOST:
            print("Received message to Leave meeting because received waiting for host status")
            BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.COULD_NOT_JOIN,
                event_sub_type=BotEventSubTypes.COULD_NOT_JOIN_MEETING_NOT_STARTED_WAITING_FOR_HOST
            )
            self.cleanup()
            return

        if message.get('message') == BotAdapter.Messages.BOT_PUT_IN_WAITING_ROOM:
            print("Received message to put bot in waiting room")
            BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.BOT_PUT_IN_WAITING_ROOM
            )
            return

        if message.get('message') == BotAdapter.Messages.BOT_JOINED_MEETING:
            print("Received message that bot joined meeting")
            BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.BOT_JOINED_MEETING
            )
            return

        if message.get('message') == BotAdapter.Messages.BOT_RECORDING_PERMISSION_GRANTED:
            print("Received message that bot recording permission granted")
            BotEventManager.create_event(
                bot=self.bot_in_db,
                event_type=BotEventTypes.BOT_RECORDING_PERMISSION_GRANTED
            )
            return

        raise Exception(f"Received unexpected message from bot adapter: {message}")