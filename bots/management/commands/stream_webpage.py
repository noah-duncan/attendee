import logging

from django.core.management.base import BaseCommand

from bots.webpage_streamer.webpage_streamer import WebpageStreamer

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Runs the celery task directly for debugging"

    def add_arguments(self, parser):
        # Add any arguments you need
        parser.add_argument("--url", type=str, help="URL to stream")

    def handle(self, *args, **options):
        logger.info("Running task...")
        webpage_streamer = WebpageStreamer(webpage_url=options["url"])
        webpage_streamer.init_driver()
