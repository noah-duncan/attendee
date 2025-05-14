import logging

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
from selenium.webdriver import ActionChains
from selenium import webdriver

from bots.bot_adapter import BotAdapter

logger = logging.getLogger(__name__)

from pyvirtualdisplay import Display

import time

import os

import subprocess

class WebpageStreamer(BotAdapter):
    def __init__(
        self,
        *,
        webpage_url,
    ):
        self.driver = None
        self.webpage_url = webpage_url
        self.video_frame_size = (1580, 1024)
        self.display_var_for_debug_recording = None
        self.display = None

    def init_driver(self):

        self.display_var_for_debug_recording = os.environ.get("DISPLAY")
        if os.environ.get("DISPLAY") is None:
            # Create virtual display only if no real display is available
            self.display = Display(visible=0, size=(1930, 1090))
            self.display.start()
            self.display_var_for_debug_recording = self.display.new_display_var

        options = webdriver.ChromeOptions()

        # Load extension
        extension_path = "bots/webpage_streamer/extension"  # Example relative path
        options.add_argument(f"--load-extension={extension_path}")

        options.add_argument("--autoplay-policy=no-user-gesture-required")
        #options.add_argument("--use-fake-device-for-media-stream")
        #options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument(f"--window-size={self.video_frame_size[0]},{self.video_frame_size[1]}")
        options.add_argument("--no-sandbox")
        #options.add_argument("--start-fullscreen")
        # options.add_argument('--headless=new')
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-web-security")
        #options.add_argument("--mute-audio")
        options.add_argument("--disable-application-cache")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--enable-blink-features=WebCodecs,WebRTC-InsertableStreams,-AutomationControlled")
        options.add_argument("--remote-debugging-port=9222")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        self.driver = webdriver.Chrome(options=options)
        logger.info(f"web driver server initialized at port {self.driver.service.port}")

        with open("bots/webpage_streamer/webpage_streamer_payload.js", "r") as file:
            payload_code = file.read()

        combined_code = f"""
            {payload_code}
        """

        # Add the combined script to execute on new document
        # self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": combined_code})

        # navigate to the webpage
        self.driver.get(self.webpage_url)

        # wait for the page to load
        self.driver.implicitly_wait(600)

        time.sleep(3)

        # Make sure to use the correct display
        display_var = self.display_var_for_debug_recording if self.display_var_for_debug_recording else os.environ.get("DISPLAY", ":0")
        
        # Execute xdotool command to simulate Ctrl+Shift+Y
        cmd = f"DISPLAY={display_var} xdotool key ctrl+shift+y"
        try:
            subprocess.run(cmd, shell=True, check=True)
            print(f"Executed OS-level keypress: {cmd}")
        except subprocess.CalledProcessError as e:
            print(f"Failed to execute keypress: {e}")
        
        print("Pressed Ctrl+Shift+Y at OS level")

        time.sleep(600)
