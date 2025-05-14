import logging

from selenium import webdriver

from bots.bot_adapter import BotAdapter

logger = logging.getLogger(__name__)

import time
class WebpageStreamer(BotAdapter):
    def __init__(
        self,
        *,
        webpage_url,
    ):
        self.driver = None
        self.webpage_url = webpage_url
        self.video_frame_size = (1280, 720)

    def init_driver(self):
        options = webdriver.ChromeOptions()


        options.add_argument("--autoplay-policy=no-user-gesture-required")
        #options.add_argument("--use-fake-device-for-media-stream")
        options.add_argument("--use-fake-ui-for-media-stream")
        options.add_argument(f"--window-size={self.video_frame_size[0]},{self.video_frame_size[1]}")
        options.add_argument("--no-sandbox")
        #options.add_argument("--start-fullscreen")
        # options.add_argument('--headless=new')
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-application-cache")
        options.add_argument("--disable-setuid-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--enable-blink-features=WebCodecs,WebRTC-InsertableStreams,-AutomationControlled")
        options.add_argument("--remote-debugging-port=9222")
        options.add_argument('--auto-select-desktop-capture-source="*"')
        options.add_experimental_option("excludeSwitches", ["enable-automation"])

        self.driver = webdriver.Chrome(options=options)
        logger.info(f"web driver server initialized at port {self.driver.service.port}")

        with open("bots/webpage_streamer/webpage_streamer_payload.js", "r") as file:
            payload_code = file.read()

        combined_code = f"""
            {payload_code}
        """

        # Add the combined script to execute on new document
        self.driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": combined_code})

        # navigate to the webpage
        self.driver.get(self.webpage_url)

        # wait for the page to load
        self.driver.implicitly_wait(600)

        time.sleep(60)
