import json
import logging
from queue import Empty, SimpleQueue
from threading import Thread
from typing import Callable

from websockets import ConnectionClosed
from websockets.protocol import State
from websockets.sync.client import connect

logger = logging.getLogger(__name__)


class BotWebsocketClient:
    """
    A websocket loop that sends and receives messages to/from a websocket server
    Designed to be used by a BotController to control the bot audio/video
    remotely.
    """

    def __init__(self, url: str, on_message_callback: Callable[[dict], None]):
        self.on_message_callback = on_message_callback
        self.websocket_url = url
        self.websocket = None

        self.recv_loop_thread = Thread(target=self.recv_loop, daemon=True)
        self.send_loop_thread = Thread(target=self.send_loop, daemon=True)
        self.send_queue = SimpleQueue()

    def started(self):
        return self.websocket is not None

    def start(self):
        if self.websocket:
            raise Exception("Websocket already started")

        logger.info("Starting websocket client")
        self.websocket = connect(self.websocket_url)

        self.recv_loop_thread.start()
        self.send_loop_thread.start()

    def stop(self):
        logger.info("Stopping websocket client")
        # This should trigger the recv_loop to exit
        self.websocket.close()

    def send_async(self, message: dict):
        """
        This function exists so that we can send messages to the websocket
        but not block the main thread executing the BotController.
        """
        if self.websocket.state not in [State.OPEN, State.CONNECTING]:
            return
        self.send_queue.put(message)

    def send_loop(self):
        logger.info("Send loop started")
        while self.websocket.state in [State.OPEN, State.CONNECTING]:
            try:
                message = self.send_queue.get(timeout=1)
            except Empty:
                # No message to send yet
                continue

            message_str = json.dumps(message)
            try:
                self.websocket.send(message_str)
            except OSError as e:
                logger.info("OSError: Maybe Connection closed. Leaving loop: %s", e)
                break
        logger.info("Send loop exited")

    def recv_loop(self):
        logger.info("Recv loop started")
        while True:
            try:
                message = self.websocket.recv()
                self.on_message_callback(message)
            except ConnectionClosed:
                logger.info("Connection closed. Leaving loop.")
                break
        logger.info("Recv loop exited")
