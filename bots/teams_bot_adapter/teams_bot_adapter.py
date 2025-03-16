from bots.teams_bot_adapter.teams_ui_methods import (
    TeamsUIMethods,
)
from bots.web_bot_adapter import WebBotAdapter


class TeamsBotAdapter(WebBotAdapter, TeamsUIMethods):
    def get_chromedriver_payload_file_name(self):
        return "teams_bot_adapter/teams_chromedriver_payload.js"

    def get_websocket_port(self):
        return 8097

    def send_raw_audio(self, bytes, sample_rate):
        print("send_raw_audio not supported in teams bots")