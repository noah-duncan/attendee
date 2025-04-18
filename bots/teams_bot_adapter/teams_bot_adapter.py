from bots.teams_bot_adapter.teams_ui_methods import (
    TeamsUIMethods,
)
from bots.web_bot_adapter import WebBotAdapter


class TeamsBotAdapter(WebBotAdapter, TeamsUIMethods):
    def get_chromedriver_payload_file_name(self):
        return "teams_bot_adapter/teams_chromedriver_payload.js"

    def get_websocket_port(self):
        return 8097

    def send_raw_image(self, image_bytes):
        # If we have a memoryview, convert it to bytes
        if isinstance(image_bytes, memoryview):
            image_bytes = image_bytes.tobytes()

        logger.info(f"Sending raw image of size {len(image_bytes)}")

        # Pass the raw bytes directly to JavaScript
        # The JavaScript side can convert it to appropriate format
        self.driver.execute_script(
            """
            const bytes = new Uint8Array(arguments[0]);
            window.botOutputManager.displayImage(bytes);
        """,
            list(image_bytes),
        )
