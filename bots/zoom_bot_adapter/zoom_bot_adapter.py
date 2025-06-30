import re
import time
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import cv2
import gi
import jwt
import numpy as np
import zoom_meeting_sdk as zoom

from bots.bot_adapter import BotAdapter
from bots.utils import png_to_yuv420_frame, scale_i420

from .mp4_demuxer import MP4Demuxer
from .video_input_manager import VideoInputManager

gi.require_version("GLib", "2.0")
import logging

from gi.repository import GLib

from bots.automatic_leave_configuration import AutomaticLeaveConfiguration
from bots.models import ParticipantEventTypes

logger = logging.getLogger(__name__)


def generate_jwt(client_id, client_secret):
    iat = datetime.utcnow()
    exp = iat + timedelta(hours=24)

    payload = {
        "iat": iat,
        "exp": exp,
        "appKey": client_id,
        "tokenExp": int(exp.timestamp()),
    }

    token = jwt.encode(payload, client_secret, algorithm="HS256")
    return token


def create_black_yuv420_frame(width=640, height=360):
    # Create BGR frame (red is [0,0,0] in BGR)
    bgr_frame = np.zeros((height, width, 3), dtype=np.uint8)
    bgr_frame[:, :] = [0, 0, 0]  # Pure black in BGR

    # Convert BGR to YUV420 (I420)
    yuv_frame = cv2.cvtColor(bgr_frame, cv2.COLOR_BGR2YUV_I420)

    # Return as bytes
    return yuv_frame.tobytes()


def parse_join_url(join_url):
    # Parse the URL into components
    parsed = urlparse(join_url)

    # Extract meeting ID using regex to match only numeric characters
    meeting_id_match = re.search(r"(\d+)", parsed.path)
    meeting_id = meeting_id_match.group(1) if meeting_id_match else None

    # Extract password from query parameters
    query_params = parse_qs(parsed.query)
    password = query_params.get("pwd", [None])[0]

    return (meeting_id, password)


class ZoomBotAdapter(BotAdapter):
    def __init__(
        self,
        *,
        use_one_way_audio,
        use_mixed_audio,
        use_video,
        display_name,
        send_message_callback,
        add_audio_chunk_callback,
        zoom_client_id,
        zoom_client_secret,
        meeting_url,
        add_video_frame_callback,
        wants_any_video_frames_callback,
        add_mixed_audio_chunk_callback,
        upsert_chat_message_callback,
        add_participant_event_callback,
        automatic_leave_configuration: AutomaticLeaveConfiguration,
        video_frame_size: tuple[int, int],
    ):
        self.use_one_way_audio = use_one_way_audio
        self.use_mixed_audio = use_mixed_audio
        self.use_video = use_video
        self.display_name = display_name
        self.send_message_callback = send_message_callback
        self.add_audio_chunk_callback = add_audio_chunk_callback
        self.add_mixed_audio_chunk_callback = add_mixed_audio_chunk_callback
        self.add_video_frame_callback = add_video_frame_callback
        self.wants_any_video_frames_callback = wants_any_video_frames_callback
        self.upsert_chat_message_callback = upsert_chat_message_callback
        self.add_participant_event_callback = add_participant_event_callback

        self._jwt_token = generate_jwt(zoom_client_id, zoom_client_secret)
        self.meeting_id, self.meeting_password = parse_join_url(meeting_url)

        self.meeting_service = None
        self.setting_service = None
        self.auth_service = None

        self.auth_event = None
        self.recording_event = None
        self.meeting_service_event = None

        self.audio_source = None
        self.audio_helper = None

        self.audio_settings = None

        self.use_raw_recording = True
        self.recording_permission_granted = False

        self.reminder_controller = None

        self.recording_ctrl = None

        self.audio_raw_data_sender = None
        self.virtual_audio_mic_event_passthrough = None

        self.my_participant_id = None
        self.participants_ctrl = None
        self.meeting_reminder_event = None
        self.on_mic_start_send_callback_called = False
        self.on_virtual_camera_start_send_callback_called = False

        self.meeting_video_controller = None
        self.video_sender = None
        self.virtual_camera_video_source = None
        self.video_source_helper = None
        self.video_frame_size = video_frame_size
        self.send_image_timeout_id = None

        self.automatic_leave_configuration = automatic_leave_configuration

        self.only_one_participant_in_meeting_at = None
        self.last_audio_received_at = None
        self.silence_detection_activated = False
        self.cleaned_up = False
        self.requested_leave = False
        self.joined_at = None

        if self.use_video:
            self.video_input_manager = VideoInputManager(
                new_frame_callback=self.add_video_frame_callback,
                wants_any_frames_callback=self.wants_any_video_frames_callback,
                video_frame_size=self.video_frame_size,
            )
        else:
            self.video_input_manager = None

        self.meeting_sharing_controller = None
        self.meeting_share_ctrl_event = None

        self.active_speaker_id = None
        self.active_sharer_id = None
        self.active_sharer_source_id = None

        self._participant_cache = {}

        self.meeting_status = None

        self.suggested_video_cap = None

        self.mp4_demuxer = None

        self.cannot_send_video_error_ticker = 0
        self.cannot_send_audio_error_ticker = 0
        self.send_raw_audio_unmute_ticker = 0

    def on_user_join_callback(self, joined_user_ids, _):
        logger.info(f"on_user_join_callback called. joined_user_ids = {joined_user_ids}")
        for joined_user_id in joined_user_ids:
            self.get_participant(joined_user_id)
            self.send_participant_event(joined_user_id, event_type=ParticipantEventTypes.JOIN)

    def on_user_left_callback(self, left_user_ids, _):
        logger.info(f"on_user_left_callback called. left_user_ids = {left_user_ids}")
        all_participant_ids = self.participants_ctrl.GetParticipantsList()
        if len(all_participant_ids) == 1:
            if self.only_one_participant_in_meeting_at is None:
                self.only_one_participant_in_meeting_at = time.time()
        else:
            self.only_one_participant_in_meeting_at = None

        for left_user_id in left_user_ids:
            self.send_participant_event(left_user_id, event_type=ParticipantEventTypes.LEAVE)

    def on_host_request_start_audio_callback(self, handler):
        logger.info("on_host_request_start_audio_callback called. Accepting request.")
        handler.Accept()

    def on_user_active_audio_change_callback(self, user_ids):
        if len(user_ids) == 0:
            return

        if user_ids[0] == self.my_participant_id:
            return

        if self.active_speaker_id == user_ids[0]:
            return

        self.active_speaker_id = user_ids[0]
        self.set_video_input_manager_based_on_state()

    def set_video_input_manager_based_on_state(self):
        if not self.wants_any_video_frames_callback():
            return

        if not self.recording_permission_granted:
            return

        if not self.video_input_manager:
            return

        logger.info(f"set_video_input_manager_based_on_state self.active_speaker_id = {self.active_speaker_id}, self.active_sharer_id = {self.active_sharer_id}, self.active_sharer_source_id = {self.active_sharer_source_id}")
        if self.active_sharer_id:
            self.video_input_manager.set_mode(
                mode=VideoInputManager.Mode.ACTIVE_SHARER,
                active_sharer_id=self.active_sharer_id,
                active_sharer_source_id=self.active_sharer_source_id,
                active_speaker_id=self.active_speaker_id,
            )
        elif self.active_speaker_id:
            self.video_input_manager.set_mode(
                mode=VideoInputManager.Mode.ACTIVE_SPEAKER,
                active_sharer_id=self.active_sharer_id,
                active_sharer_source_id=self.active_sharer_source_id,
                active_speaker_id=self.active_speaker_id,
            )
        else:
            # If there is no active sharer or speaker, we'll just use the video of the first participant that is not the bot
            # or if there are no participants, we'll use the bot
            default_participant_id = self.my_participant_id

            participant_list = self.participants_ctrl.GetParticipantsList()
            for participant_id in participant_list:
                if participant_id != self.my_participant_id:
                    default_participant_id = participant_id
                    break

            logger.info(f"set_video_input_manager_based_on_state hit default case. default_participant_id = {default_participant_id}")
            self.video_input_manager.set_mode(
                mode=VideoInputManager.Mode.ACTIVE_SPEAKER,
                active_speaker_id=default_participant_id,
                active_sharer_id=None,
                active_sharer_source_id=None,
            )

    def set_up_video_input_manager(self):
        # If someone was sharing before we joined, we will not receive an event, so we need to poll for the active sharer
        viewable_sharing_user_list = self.meeting_sharing_controller.GetViewableSharingUserList()
        self.active_sharer_id = None
        self.active_sharer_source_id = None

        if viewable_sharing_user_list:
            sharing_source_info_list = self.meeting_sharing_controller.GetSharingSourceInfoList(viewable_sharing_user_list[0])
            if sharing_source_info_list:
                self.active_sharer_id = sharing_source_info_list[0].userid
                self.active_sharer_source_id = sharing_source_info_list[0].shareSourceID

        self.set_video_input_manager_based_on_state()

    def cleanup(self):
        if self.audio_source:
            performance_data = self.audio_source.getPerformanceData()
            logger.info(f"totalProcessingTimeMicroseconds = {performance_data.totalProcessingTimeMicroseconds}")
            logger.info(f"numCalls = {performance_data.numCalls}")
            logger.info(f"maxProcessingTimeMicroseconds = {performance_data.maxProcessingTimeMicroseconds}")
            logger.info(f"minProcessingTimeMicroseconds = {performance_data.minProcessingTimeMicroseconds}")
            logger.info(f"meanProcessingTimeMicroseconds = {float(performance_data.totalProcessingTimeMicroseconds) / performance_data.numCalls}")

            # Print processing time distribution
            bin_size = (performance_data.processingTimeBinMax - performance_data.processingTimeBinMin) / len(performance_data.processingTimeBinCounts)
            logger.info("\nProcessing time distribution (microseconds):")
            for bin_idx, count in enumerate(performance_data.processingTimeBinCounts):
                if count > 0:
                    bin_start = bin_idx * bin_size
                    bin_end = (bin_idx + 1) * bin_size
                    logger.info(f"{bin_start:6.0f} - {bin_end:6.0f} us: {count:5d} calls")

        if self.meeting_service:
            zoom.DestroyMeetingService(self.meeting_service)
            logger.info("Destroyed Meeting service")
        if self.setting_service:
            zoom.DestroySettingService(self.setting_service)
            logger.info("Destroyed Setting service")
        if self.auth_service:
            zoom.DestroyAuthService(self.auth_service)
            logger.info("Destroyed Auth service")

        if self.audio_helper:
            audio_helper_unsubscribe_result = self.audio_helper.unSubscribe()
            logger.info(f"audio_helper.unSubscribe() returned {audio_helper_unsubscribe_result}")

        if self.video_input_manager:
            self.video_input_manager.cleanup()

        logger.info("CleanUPSDK() called")
        zoom.CleanUPSDK()
        logger.info("CleanUPSDK() finished")
        self.cleaned_up = True

    def init(self):
        init_param = zoom.InitParam()

        init_param.strWebDomain = "https://zoom.us"
        init_param.strSupportUrl = "https://zoom.us"
        init_param.enableGenerateDump = True
        init_param.emLanguageID = zoom.SDK_LANGUAGE_ID.LANGUAGE_English
        init_param.enableLogByDefault = True

        init_sdk_result = zoom.InitSDK(init_param)
        if init_sdk_result != zoom.SDKERR_SUCCESS:
            raise Exception("InitSDK failed")

        self.create_services()

    def get_participant(self, participant_id):
        try:
            speaker_object = self.participants_ctrl.GetUserByUserID(participant_id)
            participant_info = {
                "participant_uuid": participant_id,
                "participant_user_uuid": speaker_object.GetPersistentId(),
                "participant_full_name": speaker_object.GetUserName(),
                "participant_is_the_bot": speaker_object.GetUserID() == self.my_participant_id,
            }
            self._participant_cache[participant_id] = participant_info
            return participant_info
        except:
            logger.info(f"Error getting participant {participant_id}, falling back to cache")
            return self._participant_cache.get(participant_id)

    def on_sharing_status_callback(self, sharing_info):
        user_id = sharing_info.userid
        sharing_status = sharing_info.status
        logger.info(f"on_sharing_status_callback called. sharing_status = {sharing_status}, user_id = {user_id}")

        if sharing_status == zoom.Sharing_Other_Share_Begin or sharing_status == zoom.Sharing_View_Other_Sharing:
            new_active_sharer_id = user_id
            new_active_sharer_source_id = sharing_info.shareSourceID
        else:
            new_active_sharer_id = None
            new_active_sharer_source_id = None

        if new_active_sharer_id != self.active_sharer_id or new_active_sharer_source_id != self.active_sharer_source_id:
            self.active_sharer_id = new_active_sharer_id
            self.active_sharer_source_id = new_active_sharer_source_id
            self.set_video_input_manager_based_on_state()

    def send_chat_message(self, text):
        # Send a welcome message to the chat
        builder = self.chat_ctrl.GetChatMessageBuilder()
        builder.SetContent(text)
        builder.SetReceiver(0)
        builder.SetMessageType(zoom.SDKChatMessageType.To_All)
        msg = builder.Build()
        send_chat_message_result = self.chat_ctrl.SendChatMsgTo(msg)
        logger.info(f"send_chat_message_result = {send_chat_message_result}")
        builder.Clear()

    def on_chat_msg_notification_callback(self, chat_msg_info, content):
        try:
            self.upsert_chat_message_callback(
                {
                    "text": chat_msg_info.GetContent(),
                    "participant_uuid": chat_msg_info.GetSenderUserId(),
                    "timestamp": chat_msg_info.GetTimeStamp(),
                    "message_uuid": chat_msg_info.GetMessageID(),
                    # Simplified logic to determine if the message is for the bot. Not completely accurate.
                    "to_bot": not chat_msg_info.IsChatToAllPanelist() and not chat_msg_info.IsChatToAll() and not chat_msg_info.IsChatToWaitingroom(),
                    "additional_data": {
                        "is_comment": chat_msg_info.IsComment(),
                        "is_thread": chat_msg_info.IsThread(),
                        "thread_id": chat_msg_info.GetThreadID(),
                        "is_chat_to_all": chat_msg_info.IsChatToAll(),
                        "is_chat_to_all_panelist": chat_msg_info.IsChatToAllPanelist(),
                        "is_chat_to_waitingroom": chat_msg_info.IsChatToWaitingroom(),
                    },
                }
            )
        except Exception as e:
            logger.error(f"Error processing chat message: {e}")

    def send_participant_event(self, participant_id, event_type, event_data={}):
        self.add_participant_event_callback({"participant_uuid": participant_id, "event_type": event_type, "event_data": event_data, "timestamp_ms": int(time.time() * 1000)})

    def on_join(self):
        # Meeting reminder controller
        self.joined_at = time.time()
        self.meeting_reminder_event = zoom.MeetingReminderEventCallbacks(onReminderNotifyCallback=self.on_reminder_notify)
        self.reminder_controller = self.meeting_service.GetMeetingReminderController()
        self.reminder_controller.SetEvent(self.meeting_reminder_event)

        # Participants controller
        self.participants_ctrl = self.meeting_service.GetMeetingParticipantsController()
        self.participants_ctrl_event = zoom.MeetingParticipantsCtrlEventCallbacks(onUserJoinCallback=self.on_user_join_callback, onUserLeftCallback=self.on_user_left_callback)
        self.participants_ctrl.SetEvent(self.participants_ctrl_event)
        self.my_participant_id = self.participants_ctrl.GetMySelfUser().GetUserID()
        participant_ids_list = self.participants_ctrl.GetParticipantsList()
        for participant_id in participant_ids_list:
            self.get_participant(participant_id)
            self.send_participant_event(participant_id, event_type=ParticipantEventTypes.JOIN)

        # Chats controller
        self.chat_ctrl = self.meeting_service.GetMeetingChatController()
        self.chat_ctrl_event = zoom.MeetingChatEventCallbacks(onChatMsgNotificationCallback=self.on_chat_msg_notification_callback)
        self.chat_ctrl.SetEvent(self.chat_ctrl_event)
        self.send_message_callback({"message": self.Messages.READY_TO_SEND_CHAT_MESSAGE})

        # Meeting sharing controller
        self.meeting_sharing_controller = self.meeting_service.GetMeetingShareController()
        self.meeting_share_ctrl_event = zoom.MeetingShareCtrlEventCallbacks(onSharingStatusCallback=self.on_sharing_status_callback)
        self.meeting_sharing_controller.SetEvent(self.meeting_share_ctrl_event)

        # Audio controller
        self.audio_ctrl = self.meeting_service.GetMeetingAudioController()
        self.audio_ctrl_event = zoom.MeetingAudioCtrlEventCallbacks(onHostRequestStartAudioCallback=self.on_host_request_start_audio_callback, onUserActiveAudioChangeCallback=self.on_user_active_audio_change_callback)
        self.audio_ctrl.SetEvent(self.audio_ctrl_event)
        # Raw audio input got borked in the Zoom SDK after 6.3.5.
        # This is work-around to get it to work again.
        # See here for more details: https://devforum.zoom.us/t/cant-record-audio-with-linux-meetingsdk-after-6-3-5-6495-error-code-32/130689/5
        self.audio_ctrl.JoinVoip()

        if self.use_raw_recording:
            self.recording_ctrl = self.meeting_service.GetMeetingRecordingController()

            def on_recording_privilege_changed(can_rec):
                logger.info(f"on_recording_privilege_changed called. can_record = {can_rec}")
                if can_rec:
                    self.start_raw_recording()
                else:
                    self.stop_raw_recording()

            self.recording_event = zoom.MeetingRecordingCtrlEventCallbacks(onRecordPrivilegeChangedCallback=on_recording_privilege_changed)
            self.recording_ctrl.SetEvent(self.recording_event)

            self.start_raw_recording()

        # Set up media streams
        GLib.timeout_add_seconds(1, self.set_up_bot_audio_input)
        GLib.timeout_add_seconds(1, self.set_up_bot_video_input)

    def set_up_bot_video_input(self):
        self.virtual_camera_video_source = zoom.ZoomSDKVideoSourceCallbacks(
            onInitializeCallback=self.on_virtual_camera_initialize_callback,
            onStartSendCallback=self.on_virtual_camera_start_send_callback,
        )
        self.video_source_helper = zoom.GetRawdataVideoSourceHelper()
        if self.video_source_helper:
            set_external_video_source_result = self.video_source_helper.setExternalVideoSource(self.virtual_camera_video_source)
            logger.info(f"set_external_video_source_result = {set_external_video_source_result}")
            if set_external_video_source_result == zoom.SDKERR_SUCCESS:
                self.meeting_video_controller = self.meeting_service.GetMeetingVideoController()
                unmute_video_result = self.meeting_video_controller.UnmuteVideo()
                logger.info(f"unmute_video_result = {unmute_video_result}")
        else:
            logger.info("video_source_helper is None")

    def on_virtual_camera_start_send_callback(self):
        logger.info("on_virtual_camera_start_send_callback called")
        # As soon as we get this callback, we need to send a blank frame and it will fail with SDKERR_WRONG_USAGE
        # Then the callback will be triggered again and subsequent calls will succeed.
        # Not sure why this happens.
        if self.video_sender and not self.on_virtual_camera_start_send_callback_called and self.suggested_video_cap:
            blank = create_black_yuv420_frame(self.suggested_video_cap.width, self.suggested_video_cap.height)
            initial_send_video_frame_response = self.video_sender.sendVideoFrame(blank, self.suggested_video_cap.width, self.suggested_video_cap.height, 0, zoom.FrameDataFormat_I420_FULL)
            logger.info(f"initial_send_video_frame_response = {initial_send_video_frame_response}")
        self.on_virtual_camera_start_send_callback_called = True

        # At this point, we can show the bot image if there is one
        self.send_message_callback({"message": self.Messages.READY_TO_SHOW_BOT_IMAGE})

    def on_virtual_camera_initialize_callback(self, video_sender, support_cap_list, suggest_cap):
        logger.info(f"on_virtual_camera_initialize_callback called with support_cap_list = {list(map(lambda x: f'{x.width}x{x.height}x{x.frame}', support_cap_list))} suggest_cap = {suggest_cap.width}x{suggest_cap.height}x{suggest_cap.frame}")
        self.video_sender = video_sender
        self.suggested_video_cap = suggest_cap

    def send_raw_image(self, png_image_bytes):
        if not self.on_virtual_camera_start_send_callback_called:
            if self.cannot_send_video_error_ticker % 500 == 0:
                logger.error("on_virtual_camera_start_send_callback_called not called so cannot send raw image")
            self.cannot_send_video_error_ticker += 1
            return

        if not self.suggested_video_cap:
            logger.error("suggested_video_cap is None so cannot send raw image")
            return

        yuv420_image_bytes, original_width, original_height = png_to_yuv420_frame(png_image_bytes)
        # We have to scale the image to the zoom video capability width and height for it to display properly
        yuv420_image_bytes_scaled = scale_i420(yuv420_image_bytes, (original_width, original_height), (self.suggested_video_cap.width, self.suggested_video_cap.height))

        self.current_image_to_send = yuv420_image_bytes_scaled

        # Add a timeout to send the image every 500ms if one isn't already active
        if self.send_image_timeout_id is None:
            self.send_image_timeout_id = GLib.timeout_add(500, self.send_current_image_to_zoom)

    def send_current_image_to_zoom(self):
        if self.requested_leave or self.cleaned_up or (not self.suggested_video_cap) or (not self.current_image_to_send):
            self.send_image_timeout_id = None
            return False

        send_video_frame_response = self.video_sender.sendVideoFrame(self.current_image_to_send, self.suggested_video_cap.width, self.suggested_video_cap.height, 0, zoom.FrameDataFormat_I420_FULL)
        if send_video_frame_response != zoom.SDKERR_SUCCESS:
            logger.info(f"send_current_image_to_zoom failed with send_video_frame_response = {send_video_frame_response}")

        return True

    def send_video_frame_to_zoom(self, yuv420_image_bytes, original_width, original_height):
        if self.requested_leave or self.cleaned_up or (not self.suggested_video_cap):
            return False

        # Only scale if the dimensions are different
        if original_width != self.suggested_video_cap.width or original_height != self.suggested_video_cap.height:
            yuv420_image_bytes_scaled = scale_i420(yuv420_image_bytes, (original_width, original_height), (self.suggested_video_cap.width, self.suggested_video_cap.height))
            logger.info(f"Sending scaled video frame to Zoom. Original dimensions: {original_width}x{original_height}, Suggested dimensions: {self.suggested_video_cap.width}x{self.suggested_video_cap.height}")
        else:
            yuv420_image_bytes_scaled = yuv420_image_bytes

        send_video_frame_response = self.video_sender.sendVideoFrame(yuv420_image_bytes_scaled, self.suggested_video_cap.width, self.suggested_video_cap.height, 0, zoom.FrameDataFormat_I420_FULL)
        if send_video_frame_response != zoom.SDKERR_SUCCESS:
            logger.info(f"send_video_frame_to_zoom failed with send_video_frame_response = {send_video_frame_response}")
        return True

    def set_up_bot_audio_input(self):
        if self.audio_helper is None:
            self.audio_helper = zoom.GetAudioRawdataHelper()

        if self.audio_helper is None:
            logger.info("set_up_bot_audio_input failed because audio_helper is None")
            return

        self.virtual_audio_mic_event_passthrough = zoom.ZoomSDKVirtualAudioMicEventCallbacks(
            onMicInitializeCallback=self.on_mic_initialize_callback,
            onMicStartSendCallback=self.on_mic_start_send_callback,
        )

        audio_helper_set_external_audio_source_result = self.audio_helper.setExternalAudioSource(self.virtual_audio_mic_event_passthrough)
        logger.info(f"audio_helper_set_external_audio_source_result = {audio_helper_set_external_audio_source_result}")
        if audio_helper_set_external_audio_source_result != zoom.SDKERR_SUCCESS:
            logger.info("Failed to set external audio source")
            return

    def on_mic_initialize_callback(self, sender):
        self.audio_raw_data_sender = sender

    def periodically_unmute_audio(self):
        # Let's periodically try to unmute the audio, in case someone muted us
        if self.send_raw_audio_unmute_ticker % 1000 == 0 and self.my_participant_id is not None and self.audio_ctrl is not None:
            if self.audio_ctrl.CanUnMuteBySelf():
                unmute_result = self.audio_ctrl.UnMuteAudio(self.my_participant_id)
                if unmute_result != zoom.SDKERR_SUCCESS:
                    logger.info(f"Failed to unmute audio. unmute_result = {unmute_result}")
            else:
                logger.info("Cannot unmute audio by self")
        self.send_raw_audio_unmute_ticker += 1

    def send_raw_audio(self, bytes, sample_rate):
        self.periodically_unmute_audio()

        if not self.on_mic_start_send_callback_called:
            if self.cannot_send_audio_error_ticker % 500 == 0:
                logger.error("on_mic_start_send_callback_called not called so cannot send raw audio")
            self.cannot_send_audio_error_ticker += 1
            return

        send_result = self.audio_raw_data_sender.send(bytes, sample_rate, zoom.ZoomSDKAudioChannel_Mono)
        if send_result != zoom.SDKERR_SUCCESS:
            logger.info(f"error with send_raw_audio send_result = {send_result}")

    def on_mic_start_send_callback(self):
        self.on_mic_start_send_callback_called = True
        logger.info("on_mic_start_send_callback called")

    def on_one_way_audio_raw_data_received_callback(self, data, node_id):
        if node_id == self.my_participant_id:
            return

        current_time = datetime.utcnow()
        self.last_audio_received_at = time.time()
        self.add_audio_chunk_callback(node_id, current_time, data.GetBuffer())

    def add_mixed_audio_chunk_convert_to_bytes(self, data):
        self.add_mixed_audio_chunk_callback(chunk=data.GetBuffer())

    def start_raw_recording(self):
        self.recording_ctrl = self.meeting_service.GetMeetingRecordingController()

        can_start_recording_result = self.recording_ctrl.CanStartRawRecording()
        if can_start_recording_result != zoom.SDKERR_SUCCESS:
            self.recording_ctrl.RequestLocalRecordingPrivilege()
            logger.info("Requesting recording privilege.")
            return

        start_raw_recording_result = self.recording_ctrl.StartRawRecording()
        if start_raw_recording_result != zoom.SDKERR_SUCCESS:
            logger.info("Start raw recording failed.")
            return

        if self.audio_helper is None:
            self.audio_helper = zoom.GetAudioRawdataHelper()
        if self.audio_helper is None:
            logger.info("audio_helper is None")
            return

        if self.audio_source is None:
            self.audio_source = zoom.ZoomSDKAudioRawDataDelegateCallbacks(
                collectPerformanceData=True,
                onOneWayAudioRawDataReceivedCallback=self.on_one_way_audio_raw_data_received_callback if self.use_one_way_audio else None,
                onMixedAudioRawDataReceivedCallback=self.add_mixed_audio_chunk_convert_to_bytes if self.use_mixed_audio else None,
            )

        audio_helper_subscribe_result = self.audio_helper.subscribe(self.audio_source, False)
        logger.info(f"audio_helper_subscribe_result = {audio_helper_subscribe_result}")

        self.send_message_callback({"message": self.Messages.BOT_RECORDING_PERMISSION_GRANTED})
        self.recording_permission_granted = True

        GLib.timeout_add(100, self.set_up_video_input_manager)

    def stop_raw_recording(self):
        rec_ctrl = self.meeting_service.StopRawRecording()
        if rec_ctrl.StopRawRecording() != zoom.SDKERR_SUCCESS:
            raise Exception("Error with stop raw recording")

    def leave(self):
        if self.meeting_service is None:
            return

        status = self.meeting_service.GetMeetingStatus()
        if status == zoom.MEETING_STATUS_IDLE or status == zoom.MEETING_STATUS_ENDED:
            logger.info(f"Aborting leave because meeting status is {status}")
            return

        logger.info("Requesting to leave meeting...")
        leave_result = self.meeting_service.Leave(zoom.LEAVE_MEETING)
        logger.info(f"Requested to leave meeting. result = {leave_result}")
        self.requested_leave = True

    def join_meeting(self):
        meeting_number = int(self.meeting_id)

        join_param = zoom.JoinParam()
        join_param.userType = zoom.SDKUserType.SDK_UT_WITHOUT_LOGIN

        param = join_param.param
        param.meetingNumber = meeting_number
        param.userName = self.display_name
        param.psw = self.meeting_password if self.meeting_password is not None else ""
        param.isVideoOff = False
        param.isAudioOff = False
        param.isAudioRawDataStereo = False
        param.isMyVoiceInMix = False
        param.eAudioRawdataSamplingRate = zoom.AudioRawdataSamplingRate.AudioRawdataSamplingRate_32K

        join_result = self.meeting_service.Join(join_param)
        logger.info(f"join_result = {join_result}")

        self.audio_settings = self.setting_service.GetAudioSettings()
        self.audio_settings.EnableAutoJoinAudio(True)

    def on_reminder_notify(self, content, handler):
        if handler:
            handler.Accept()

    def auth_return(self, result):
        if result == zoom.AUTHRET_SUCCESS:
            logger.info("Auth completed successfully.")
            return self.join_meeting()

        self.send_message_callback(
            {
                "message": self.Messages.ZOOM_AUTHORIZATION_FAILED,
                "zoom_result_code": result,
            }
        )

    def leave_meeting_if_not_started_yet(self):
        if self.meeting_status != zoom.MEETING_STATUS_WAITINGFORHOST:
            return

        logger.info(f"Give up trying to join meeting because we've waited for the host to start it for over {self.automatic_leave_configuration.wait_for_host_to_start_meeting_timeout_seconds} seconds")
        self.send_message_callback({"message": self.Messages.LEAVE_MEETING_WAITING_FOR_HOST})

    def leave_meeting_if_still_in_waiting_room(self):
        if self.meeting_status != zoom.MEETING_STATUS_IN_WAITING_ROOM:
            return

        logger.info(f"Give up trying to join meeting because we've been in the waiting room for over {self.automatic_leave_configuration.waiting_room_timeout_seconds} seconds")
        self.send_message_callback({"message": self.Messages.LEAVE_MEETING_WAITING_ROOM_TIMEOUT_EXCEEDED})

    def wait_for_host_to_start_meeting_then_give_up(self):
        wait_time = self.automatic_leave_configuration.wait_for_host_to_start_meeting_timeout_seconds
        logger.info(f"Waiting for host to start meeting. If host doesn't start meeting in {wait_time} seconds, we'll give up")
        GLib.timeout_add_seconds(wait_time, self.leave_meeting_if_not_started_yet)

    def meeting_status_changed(self, status, iResult):
        logger.info(f"meeting_status_changed called. status = {status}, iResult={iResult}")
        self.meeting_status = status

        if status == zoom.MEETING_STATUS_WAITINGFORHOST:
            self.wait_for_host_to_start_meeting_then_give_up()

        if status == zoom.MEETING_STATUS_IN_WAITING_ROOM:
            self.send_message_callback({"message": self.Messages.BOT_PUT_IN_WAITING_ROOM})
            GLib.timeout_add_seconds(self.automatic_leave_configuration.waiting_room_timeout_seconds, self.leave_meeting_if_still_in_waiting_room)

        if status == zoom.MEETING_STATUS_INMEETING:
            self.send_message_callback({"message": self.Messages.BOT_JOINED_MEETING})

        if status == zoom.MEETING_STATUS_ENDED:
            # We get the MEETING_STATUS_ENDED regardless of whether we initiated the leave or not
            self.send_message_callback({"message": self.Messages.MEETING_ENDED})

        if status == zoom.MEETING_STATUS_FAILED:
            # Since the unable to join external meeting issue is so common, we'll handle it separately
            if iResult == zoom.MeetingFailCode.MEETING_FAIL_UNABLE_TO_JOIN_EXTERNAL_MEETING:
                self.send_message_callback(
                    {
                        "message": self.Messages.ZOOM_MEETING_STATUS_FAILED_UNABLE_TO_JOIN_EXTERNAL_MEETING,
                        "zoom_result_code": iResult,
                    }
                )
            else:
                self.send_message_callback(
                    {
                        "message": self.Messages.ZOOM_MEETING_STATUS_FAILED,
                        "zoom_result_code": iResult,
                    }
                )

        if status == zoom.MEETING_STATUS_INMEETING:
            return self.on_join()

    def create_services(self):
        self.meeting_service = zoom.CreateMeetingService()

        self.setting_service = zoom.CreateSettingService()

        self.meeting_service_event = zoom.MeetingServiceEventCallbacks(onMeetingStatusChangedCallback=self.meeting_status_changed)

        meeting_service_set_revent_result = self.meeting_service.SetEvent(self.meeting_service_event)
        if meeting_service_set_revent_result != zoom.SDKERR_SUCCESS:
            raise Exception("Meeting Service set event failed")

        self.auth_event = zoom.AuthServiceEventCallbacks(onAuthenticationReturnCallback=self.auth_return)

        self.auth_service = zoom.CreateAuthService()

        set_event_result = self.auth_service.SetEvent(self.auth_event)
        logger.info(f"set_event_result = {set_event_result}")

        # Use the auth service
        auth_context = zoom.AuthContext()
        auth_context.jwt_token = self._jwt_token

        result = self.auth_service.SDKAuth(auth_context)

        if result == zoom.SDKError.SDKERR_SUCCESS:
            logger.info("Authentication successful")
        else:
            logger.info(f"Authentication failed with error: {result}")
            self.send_message_callback(
                {
                    "message": self.Messages.ZOOM_SDK_INTERNAL_ERROR,
                    "zoom_result_code": result,
                }
            )

    def get_first_buffer_timestamp_ms_offset(self):
        return 0

    def check_auto_leave_conditions(self):
        if self.requested_leave:
            return
        if self.cleaned_up:
            return

        if self.only_one_participant_in_meeting_at is not None:
            if time.time() - self.only_one_participant_in_meeting_at > self.automatic_leave_configuration.only_participant_in_meeting_timeout_seconds:
                logger.info(f"Auto-leaving meeting because there was only one participant in the meeting for {self.automatic_leave_configuration.only_participant_in_meeting_timeout_seconds} seconds")
                self.send_message_callback({"message": self.Messages.ADAPTER_REQUESTED_BOT_LEAVE_MEETING, "leave_reason": BotAdapter.LEAVE_REASON.AUTO_LEAVE_ONLY_PARTICIPANT_IN_MEETING})
                return

        if not self.silence_detection_activated and self.joined_at is not None and time.time() - self.joined_at > self.automatic_leave_configuration.silence_activate_after_seconds:
            self.silence_detection_activated = True
            self.last_audio_received_at = time.time()
            logger.info(f"Silence detection activated after {self.automatic_leave_configuration.silence_activate_after_seconds} seconds")

        if self.last_audio_received_at is not None and self.silence_detection_activated:
            if time.time() - self.last_audio_received_at > self.automatic_leave_configuration.silence_timeout_seconds:
                logger.info(f"Auto-leaving meeting because there was no audio message for {self.automatic_leave_configuration.silence_timeout_seconds} seconds")
                self.send_message_callback({"message": self.Messages.ADAPTER_REQUESTED_BOT_LEAVE_MEETING, "leave_reason": BotAdapter.LEAVE_REASON.AUTO_LEAVE_SILENCE})
                return

        if self.joined_at is not None and self.automatic_leave_configuration.max_uptime_seconds is not None:
            if time.time() - self.joined_at > self.automatic_leave_configuration.max_uptime_seconds:
                logger.info(f"Auto-leaving meeting because bot has been running for more than {self.automatic_leave_configuration.max_uptime_seconds} seconds")
                self.send_message_callback({"message": self.Messages.ADAPTER_REQUESTED_BOT_LEAVE_MEETING, "leave_reason": BotAdapter.LEAVE_REASON.AUTO_LEAVE_MAX_UPTIME})
                return

    def is_sent_video_still_playing(self):
        if not self.mp4_demuxer:
            return False
        return self.mp4_demuxer.is_playing()

    def send_video(self, video_url):
        logger.info(f"send_video called with video_url = {video_url}")
        if self.mp4_demuxer:
            self.mp4_demuxer.stop()
            self.mp4_demuxer = None

        if self.suggested_video_cap is None:
            logger.info("No suggested video cap. Not sending video.")
            return

        self.mp4_demuxer = MP4Demuxer(
            url=video_url,
            output_video_dimensions=(self.suggested_video_cap.width, self.suggested_video_cap.height),
            on_video_sample=self.mp4_demuxer_on_video_sample,
            on_audio_sample=self.mp4_demuxer_on_audio_sample,
        )
        self.mp4_demuxer.start()
        return

    def mp4_demuxer_on_video_sample(self, pts, bytes_from_gstreamer):
        if self.requested_leave or self.cleaned_up or (not self.suggested_video_cap):
            self.mp4_demuxer.stop()
            self.mp4_demuxer = None
            return

        self.send_video_frame_to_zoom(bytes_from_gstreamer, self.suggested_video_cap.width, self.suggested_video_cap.height)

    def mp4_demuxer_on_audio_sample(self, pts, bytes_from_gstreamer):
        if self.requested_leave or self.cleaned_up:
            self.mp4_demuxer.stop()
            self.mp4_demuxer = None
            return

        self.send_raw_audio(bytes_from_gstreamer, 8000)

    def get_staged_bot_join_delay_seconds(self):
        return 0
