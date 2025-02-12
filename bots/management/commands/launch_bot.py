from django.core.management.base import BaseCommand
from bots.tasks import run_bot  # Import your task
from bots.models import Bot, BotEventManager, Project, Recording, RecordingTypes, TranscriptionTypes, TranscriptionProviders, BotEventTypes
import json

class Command(BaseCommand):
    help = 'Runs the celery task directly for debugging'

    def add_arguments(self, parser):
        # Add any arguments you need
        parser.add_argument('--joinurl', type=str, help='Join URL')
        parser.add_argument('--rtmpsettings', type=str, help='RTMP Settings')
        parser.add_argument('--botname', type=str, help='Bot Name')
        parser.add_argument('--projectid', type=str, help='Project ID')

    def handle(self, *args, **options):
        self.stdout.write('Running task...')
        
        project = Project.objects.get(object_id=options['projectid'])
        
        meeting_url = options['joinurl']
        rtmp_settings = json.loads(options.get('rtmpsettings')) if options.get('rtmpsettings') else None
        bot_name = options['botname']
        bot = Bot.objects.create(
            project=project,
            meeting_url=meeting_url,
            name=bot_name,
            settings={
                'rtmp_settings': rtmp_settings
            }
        )

        Recording.objects.create(
            bot=bot,
            recording_type=RecordingTypes.AUDIO_AND_VIDEO,
            transcription_type=TranscriptionTypes.NON_REALTIME,
            transcription_provider=TranscriptionProviders.DEEPGRAM,
            is_default_recording=True
        )
        
        # Try to transition the state from READY to JOINING
        BotEventManager.create_event(bot, BotEventTypes.JOIN_REQUESTED)

        # Call your task directly
        result = run_bot.run(
            bot.id
        )
        
        self.stdout.write(self.style.SUCCESS(f'Task completed with result: {result}'))