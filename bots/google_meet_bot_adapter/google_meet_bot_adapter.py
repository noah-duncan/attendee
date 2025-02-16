import asyncio
import os
import datetime
import requests
import json
import threading
import wave
import numpy as np
import cv2

import time
from time import sleep

import undetected_chromedriver as uc
from pyvirtualdisplay import Display

from selenium.webdriver.common.by import By
from websockets.sync.server import serve
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from bots.bot_adapter import BotAdapter
from bots.google_meet_bot_adapter.google_meet_ui_methods import GoogleMeetUIMethods, UiRetryableException, UiRequestToJoinDeniedException

def half_ceil(x):
    return (x + 1) // 2

def scale_i420(frame, frame_size, new_size):
    """
    Scales an I420 (YUV 4:2:0) frame from 'frame_size' to 'new_size',
    handling odd frame widths/heights by using 'ceil' in the chroma planes.
   
    :param frame:      A bytes object containing the raw I420 frame data.
    :param frame_size: (orig_width, orig_height)
    :param new_size:   (new_width, new_height)
    :return:           A bytes object with the scaled I420 frame.
    """
   
    # 1) Unpack source / destination dimensions
    orig_width, orig_height = frame_size
    new_width, new_height = new_size

    # 2) Compute source plane sizes with rounding up for chroma
    orig_chroma_width  = half_ceil(orig_width)
    orig_chroma_height = half_ceil(orig_height)

    y_plane_size = orig_width * orig_height
    uv_plane_size = orig_chroma_width * orig_chroma_height  # for each U or V

    # 3) Extract Y, U, V planes from the byte array
    y = np.frombuffer(frame[0 : y_plane_size], dtype=np.uint8)
    u = np.frombuffer(frame[y_plane_size : y_plane_size + uv_plane_size], dtype=np.uint8)
    v = np.frombuffer(frame[y_plane_size + uv_plane_size : y_plane_size + 2*uv_plane_size], dtype=np.uint8)

    # 4) Reshape planes
    y = y.reshape(orig_height, orig_width)
    u = u.reshape(orig_chroma_height, orig_chroma_width)
    v = v.reshape(orig_chroma_height, orig_chroma_width)

    #---------------------------------------------------------
    # Scale preserving aspect ratio or do letterbox/pillarbox
    #---------------------------------------------------------
    input_aspect = orig_width / orig_height
    output_aspect = new_width / new_height

    if abs(input_aspect - output_aspect) < 1e-6:
        # Same aspect ratio; do a straightforward resize
        scaled_y = cv2.resize(y, (new_width, new_height), interpolation=cv2.INTER_LINEAR)
       
        # For U, V we should scale to half-dimensions (rounded up)
        # of the new size. But OpenCV requires exact (int) dims, so:
        target_u_width  = half_ceil(new_width)
        target_u_height = half_ceil(new_height)
       
        scaled_u = cv2.resize(u, (target_u_width, target_u_height), interpolation=cv2.INTER_LINEAR)
        scaled_v = cv2.resize(v, (target_u_width, target_u_height), interpolation=cv2.INTER_LINEAR)

        # Flatten and return
        return np.concatenate([
            scaled_y.flatten(),
            scaled_u.flatten(),
            scaled_v.flatten()
        ]).astype(np.uint8).tobytes()

    # Otherwise, the aspect ratios differ => letterbox or pillarbox
    if input_aspect > output_aspect:
        # The image is relatively wider => match width, shrink height
        scaled_width = new_width
        scaled_height = int(round(new_width / input_aspect))
    else:
        # The image is relatively taller => match height, shrink width
        scaled_height = new_height
        scaled_width  = int(round(new_height * input_aspect))

    # 5) Resize Y, U, and V to the scaled dimensions
    scaled_y = cv2.resize(y, (scaled_width, scaled_height), interpolation=cv2.INTER_LINEAR)
   
    # For U, V, use half-dimensions of the scaled result, rounding up.
    scaled_u_width  = half_ceil(scaled_width)
    scaled_u_height = half_ceil(scaled_height)
    scaled_u = cv2.resize(u, (scaled_u_width, scaled_u_height), interpolation=cv2.INTER_LINEAR)
    scaled_v = cv2.resize(v, (scaled_u_width, scaled_u_height), interpolation=cv2.INTER_LINEAR)

    # 6) Create the output buffers. For "dark" black:
    #    Y=0, U=128, V=128.
    final_y = np.zeros((new_height, new_width), dtype=np.uint8)
    final_u = np.full((half_ceil(new_height), half_ceil(new_width)), 128, dtype=np.uint8)
    final_v = np.full((half_ceil(new_height), half_ceil(new_width)), 128, dtype=np.uint8)

    # 7) Compute centering offsets for each plane (Y first)
    offset_y = (new_height - scaled_height) // 2
    offset_x = (new_width - scaled_width)   // 2

    final_y[offset_y:offset_y+scaled_height,
            offset_x:offset_x+scaled_width] = scaled_y

    # Offsets for U and V planes are half of the Y offsets (integer floor)
    offset_y_uv = offset_y // 2
    offset_x_uv = offset_x // 2

    final_u[offset_y_uv:offset_y_uv+scaled_u_height,
            offset_x_uv:offset_x_uv+scaled_u_width] = scaled_u
    final_v[offset_y_uv:offset_y_uv+scaled_u_height,
            offset_x_uv:offset_x_uv+scaled_u_width] = scaled_v

    # 8) Flatten back to I420 layout and return bytes

    return np.concatenate([
        final_y.flatten(),
        final_u.flatten(),
        final_v.flatten()
    ]).astype(np.uint8).tobytes()

class GoogleMeetBotAdapter(BotAdapter, GoogleMeetUIMethods):

    def __init__(self, *, display_name, send_message_callback, meeting_url, add_video_frame_callback, wants_any_video_frames_callback, add_mixed_audio_chunk_callback, upsert_caption_callback):
        self.display_name = display_name
        self.send_message_callback = send_message_callback
        self.add_mixed_audio_chunk_callback = add_mixed_audio_chunk_callback
        self.add_video_frame_callback = add_video_frame_callback
        self.wants_any_video_frames_callback = wants_any_video_frames_callback
        self.upsert_caption_callback = upsert_caption_callback

        self.meeting_url = meeting_url

        self.video_frame_size = (1920, 1080)

        self.driver = None

        self.send_frames = True

        self.left_meeting = False
        self.was_removed_from_meeting = False
        self.cleaned_up = False

        self.websocket_port = None
        self.websocket_server = None
        self.websocket_thread = None
        self.last_websocket_message_processed_time = None
        self.last_media_message_processed_time = None
        self.first_buffer_timestamp_ms_offset = time.time() * 1000

        self.participants_info = {}
        self.only_one_participant_in_meeting_at = None
        self.video_frame_ticker = 0

    def get_participant(self, participant_id):
        if participant_id in self.participants_info:
            return {
                'participant_uuid': participant_id,
                'participant_full_name': self.participants_info[participant_id]['fullName'],
                'participant_user_uuid': None
            }

        return None

    def handle_websocket(self, websocket):
        audio_file = None
        audio_format = None
        frame_counter = 0  # Add frame counter
        output_dir = 'frames'  # Add output directory
        
        # Create frames directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)

        try:
            for message in websocket:
                # Get first 4 bytes as message type
                message_type = int.from_bytes(message[:4], byteorder='little')
                
                if message_type == 1:  # JSON
                    json_data = json.loads(message[4:].decode('utf-8'))
                    print("Received JSON message:", json_data)
                    
                    # Handle audio format information
                    if isinstance(json_data, dict):
                        if json_data.get('type') == 'AudioFormatUpdate':
                            audio_format = json_data['format']
                            # Create a new WAV file
                            audio_file = wave.open('recorded_audio.wav', 'wb')
                            audio_file.setnchannels(audio_format['numberOfChannels'])
                            audio_file.setsampwidth(4)  # 4 bytes for float32
                            audio_file.setframerate(audio_format['sampleRate']/2)

                        elif json_data.get('type') == 'CaptionUpdate':
                            self.upsert_caption_callback(json_data['caption'])

                        elif json_data.get('type') == 'UsersUpdate':
                            for user in json_data['newUsers']:
                                user['active'] = user['humanized_status'] == 'in_meeting'
                                self.participants_info[user['deviceId']] = user
                            for user in json_data['removedUsers']:
                                user['active'] = False
                                self.participants_info[user['deviceId']] = user
                            for user in json_data['updatedUsers']:
                                user['active'] = user['humanized_status'] == 'in_meeting'
                                self.participants_info[user['deviceId']] = user

                                if user['humanized_status'] == 'removed_from_meeting' and user['fullName'] == self.display_name:
                                    # if this is the only participant with that name in the meeting, then we can assume that it was us who was removed
                                    if len([x for x in self.participants_info.values() if x['fullName'] == self.display_name]) == 1:
                                        self.was_removed_from_meeting = True
                                        self.send_message_callback({'message': self.Messages.MEETING_ENDED})
                        
                            if len([x for x in self.participants_info.values() if x['active']]) == 1:
                                if self.only_one_participant_in_meeting_at is None:
                                    self.only_one_participant_in_meeting_at = time.time()
                            else:
                                self.only_one_participant_in_meeting_at = None

                elif message_type == 2:  # VIDEO
                    self.last_media_message_processed_time = time.time()
                    if len(message) > 24:  # Minimum length check
                        # Bytes 4-12 contain the timestamp
                        timestamp = int.from_bytes(message[4:12], byteorder='little')

                        # Get stream ID length and string
                        stream_id_length = int.from_bytes(message[12:16], byteorder='little')
                        stream_id = message[16:16+stream_id_length].decode('utf-8')

                        # Get width and height after stream ID
                        offset = 16 + stream_id_length
                        width = int.from_bytes(message[offset:offset+4], byteorder='little')
                        height = int.from_bytes(message[offset+4:offset+8], byteorder='little')
                        
                        # Keep track of the video frame dimensions
                        if self.video_frame_ticker % 300 == 0:
                            print("video dimensions", width, height, " message length", len(message) - offset - 8)
                        self.video_frame_ticker += 1
                    
                        # Convert I420 format to BGR for OpenCV
                        expected_video_data_length = width * height + 2 * half_ceil(width) * half_ceil(height)
                        video_data = np.frombuffer(message[offset+8:], dtype=np.uint8)

                        # Check if len(video_data) does not agree with width and height
                        if len(video_data) == expected_video_data_length:  # I420 format uses 1.5 bytes per pixel
      
                            scaled_i420_frame = scale_i420(video_data, (width, height), (1920, 1080))
                            if self.wants_any_video_frames_callback() and self.send_frames:                
                                self.add_video_frame_callback(scaled_i420_frame, timestamp * 1000)

                        else:
                            print("video data length does not agree with width and height", len(video_data), width, height)                        

                elif message_type == 3:  # AUDIO
                    self.last_media_message_processed_time = time.time()
                    if audio_file is not None and len(message) > 12:
                        # Bytes 4-12 contain the timestamp
                        timestamp = int.from_bytes(message[4:12], byteorder='little')
                        # Convert the float32 audio data to int16 for WAV file
                        audio_data = np.frombuffer(message[12:], dtype=np.float32)

                        if self.wants_any_video_frames_callback() and self.send_frames:  
                            self.add_mixed_audio_chunk_callback(audio_data.tobytes(), timestamp * 1000)
                    
                self.last_websocket_message_processed_time = time.time()
        except Exception as e:
            print(f"Websocket error: {e}")


    def run_websocket_server(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        port = 8765
        max_retries = 10
        
        for attempt in range(max_retries):
            try:
                self.websocket_server = serve(self.handle_websocket, 
                                           "localhost", 
                                           port,
                                           compression=None,
                                           max_size=None)
                print(f"Websocket server started on ws://localhost:{port}")
                self.websocket_port = port
                self.websocket_server.serve_forever()
                break
            except OSError as e:
                if e.errno == 98:  # Address already in use
                    print(f"Port {port} is already in use, trying next port...")
                    port += 1
                    if attempt == max_retries - 1:
                        raise Exception(f"Could not find available port after {max_retries} attempts")
                    continue
                raise  # Re-raise other OSErrors

    def send_request_to_join_denied_message(self):
        self.send_message_callback({'message': self.Messages.REQUEST_TO_JOIN_DENIED})

    def send_debug_screenshot_message(self, step, exception, inner_exception):
        current_time = datetime.datetime.now()
        timestamp = current_time.strftime("%Y%m%d_%H%M%S")
        screenshot_path = f"/tmp/ui_element_not_found_{timestamp}.png"
        try:
            self.driver.save_screenshot(screenshot_path)
        except Exception as e:
            print(f"Error saving screenshot: {e}")
            screenshot_path = None

        self.send_message_callback({
            'message': self.Messages.UI_ELEMENT_NOT_FOUND, 
            'step': step, 
            'current_time': current_time, 
            'screenshot_path': screenshot_path,
            'exception_type': exception.__class__.__name__ if exception else "exception_not_available",
            'exception_message': exception.__str__() if exception else "exception_message_not_available",
            'inner_exception_type': inner_exception.__class__.__name__ if inner_exception else "inner_exception_not_available",
            'inner_exception_message': inner_exception.__str__() if inner_exception else "inner_exception_message_not_available"
        })

    def init_driver(self):
        log_path = "chromedriver.log"

        options = uc.ChromeOptions()

        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument("--window-size=1920x1080")
        options.add_argument("--no-sandbox")
        # options.add_argument('--headless=new')
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-extensions")
        options.add_argument("--disable-application-cache")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-dev-shm-usage")

        if self.driver:
            try:
                self.driver.quit()
            except Exception as e:
                print(f"Error closing existing driver: {e}")
            self.driver = None

        self.driver = uc.Chrome(service_log_path=log_path, use_subprocess=True, options=options, version_main=133)

        initial_data_code = f"window.initialData = {{websocketPort: {self.websocket_port}}}"

        # Define the CDN libraries needed
        CDN_LIBRARIES = [
            'https://cdnjs.cloudflare.com/ajax/libs/protobufjs/7.4.0/protobuf.min.js',
        ]

        # Download all library code
        libraries_code = ""
        for url in CDN_LIBRARIES:
            response = requests.get(url)
            if response.status_code == 200:
                libraries_code += response.text + "\n"
            else:
                raise Exception(f"Failed to download library from {url}")
        
        # Get directory of current file
        current_dir = os.path.dirname(os.path.abspath(__file__))        
        # Read your payload using path relative to current file
        with open(os.path.join(current_dir, 'chromedriver_payload.js'), 'r') as file:
            payload_code = file.read()
        
        # Combine them ensuring libraries load first
        combined_code = f"""
            {initial_data_code}
            {libraries_code}
            {payload_code}
        """
        
        # Add the combined script to execute on new document
        self.driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
            'source': combined_code
        })

    def init(self):
        if os.environ.get('DISPLAY') is None:
            # Create virtual display only if no real display is available
            display = Display(visible=0, size=(1920, 1080))
            display.start()
        
        # Start websocket server in a separate thread
        websocket_thread = threading.Thread(target=self.run_websocket_server, daemon=True)
        websocket_thread.start()
        
        sleep(0.5)  # Give the websocketserver time to start
        if not self.websocket_port:
            raise Exception("WebSocket server failed to start")

        print(f"Trying to join google meet meeting at {self.meeting_url}")

        num_retries = 0
        max_retries = 2
        while num_retries <= max_retries: 
            try:
                self.init_driver()
                self.attempt_to_join_meeting()
                print("Successfully joined meeting")
                break

            except UiRequestToJoinDeniedException:
                self.send_request_to_join_denied_message()
                return

            except UiRetryableException as e:

                if num_retries >= max_retries:
                    print(f"Failed to join meeting and the {e.__class__.__name__} exception is retryable but the number of retries exceeded the limit, so returning")
                    self.send_debug_screenshot_message(step = e.step, exception = e, inner_exception = e.inner_exception)
                    return
                
                print(f"Failed to join meeting and the {e.__class__.__name__} exception is retryable so retrying")

            num_retries += 1
            sleep(1)

        # Trying making it smaller so GMeet sends smaller video frames
        self.driver.set_window_size(1920/2, 1080/2)

        self.send_message_callback({'message': self.Messages.BOT_JOINED_MEETING})
        self.send_message_callback({'message': self.Messages.BOT_RECORDING_PERMISSION_GRANTED})

        self.send_frames = True
        self.driver.execute_script("window.ws.enableMediaSending();")
        self.first_buffer_timestamp_ms_offset = self.driver.execute_script("return performance.timeOrigin;")
        
    def leave(self):
        if self.left_meeting:
            return
        if self.was_removed_from_meeting:
            return

        try:
            print("disable media sending")
            self.driver.execute_script("window.ws?.disableMediaSending();")
            
            print("Waiting for the leave button")
            leave_button = WebDriverWait(self.driver, 6).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'button[jsname="CQylAd"][aria-label="Leave call"]'))
            )
            print("Clicking the leave button")
            leave_button.click()
        except Exception as e:
            print(f"Error during leave: {e}")
        finally:
            self.send_message_callback({'message': self.Messages.MEETING_ENDED})
            self.left_meeting = True

    def cleanup(self):
        try:
            print("disable media sending")
            self.driver.execute_script("window.ws?.disableMediaSending();")
        except Exception as e:
            print(f"Error during media sending disable: {e}")

        # Wait for websocket buffers to be processed
        if self.last_websocket_message_processed_time:
            time_when_shutdown_initiated = time.time() 
            while time.time() - self.last_websocket_message_processed_time < 2 and time.time() - time_when_shutdown_initiated < 30:
                print(f"Waiting until it's 2 seconds since last websockets message was processed or 30 seconds have passed. Currently it is {time.time() - self.last_websocket_message_processed_time} seconds and {time.time() - time_when_shutdown_initiated} seconds have passed")
                sleep(0.5)

        try:
            if self.driver:
                self.driver.quit()
        except Exception as e:
            print(f"Error during cleanup: {e}")

        # Properly shutdown the websocket server
        if self.websocket_server:
            try:
                self.websocket_server.shutdown()
            except Exception as e:
                print(f"Error shutting down websocket server: {e}")

        self.cleaned_up = True

    def get_first_buffer_timestamp_ms_offset(self):
        return self.first_buffer_timestamp_ms_offset

    def check_auto_leave_conditions(self):
        if self.left_meeting:
            return
        if self.cleaned_up:
            return

        if self.only_one_participant_in_meeting_at is not None:
            if time.time() - self.only_one_participant_in_meeting_at > 30:
                print("Auto-leaving meeting because there was only one participant in the meeting for 30 seconds")
                self.leave()
                return

        if self.last_media_message_processed_time is not None:
            if time.time() - self.last_media_message_processed_time > 300:
                print("Auto-leaving meeting because there was no media message for 300 seconds")
                self.leave()
                return

    def send_raw_audio(self, bytes, sample_rate):
        print("send_raw_audio not supported in google meet bots")
