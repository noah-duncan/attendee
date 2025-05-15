import logging
import os
import signal
import subprocess
from celery import shared_task
from celery.signals import worker_shutting_down

from bots.bot_controller import BotController

logger = logging.getLogger(__name__)


@shared_task(bind=True, soft_time_limit=3600)
def run_bot(self, bot_id):
    logger.info(f"Running bot {bot_id}")

    # Make sub process to run websocket server
    websocket_process = subprocess.Popen(["python", "simple_va_experiment_server.py"])
    websocket_process_voice_only = subprocess.Popen(["python", "simple_va_experiment_server.py", "--voice-only"])
   # websocket_process.start()

    # Make another process to run image streamer
    image_streamer_process = subprocess.Popen(["python", "manage.py", "stream_webpage", "--url", "https://www.sesame.com/research/crossing_the_uncanny_valley_of_voice#demo"])
    #image_streamer_process.start()

    bot_controller = BotController(bot_id)
    bot_controller.run()


def kill_child_processes():
    # Get the process group ID (PGID) of the current process
    pgid = os.getpgid(os.getpid())

    try:
        # Send SIGTERM to all processes in the process group
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        pass  # Process group may no longer exist


@worker_shutting_down.connect
def shutting_down_handler(sig, how, exitcode, **kwargs):
    # Just adding this code so we can see how to shut down all the tasks
    # when the main process is terminated.
    # It's likely overkill.
    logger.info("Celery worker shutting down, sending SIGTERM to all child processes")
    kill_child_processes()
