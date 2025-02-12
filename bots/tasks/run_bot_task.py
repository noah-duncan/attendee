from celery import shared_task
from bots.models import *
import os
import signal
from celery.signals import worker_shutting_down
from bots.bot_controller import BotController

@shared_task(bind=True, soft_time_limit=3600)
def run_bot(self, bot_id):
    print("Running bot", bot_id)
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
    print("Celery worker shutting down, sending SIGTERM to all child processes")
    kill_child_processes()