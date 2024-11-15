from django.shortcuts import render, get_object_or_404
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import BotSession, BotSessionEvent, BotSessionEventManager, AnalysisTask, AnalysisTaskTypes, AnalysisTaskSubTypes, Utterance, Participant, Bot
from .serializers import CreateSessionSerializer, SessionSerializer
from .authentication import ApiKeyAuthentication
from .tasks import run_bot_session
import redis
import json
import os

class NotFoundView(APIView):
    def get(self, request, *args, **kwargs):
        return self.handle_request(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        return self.handle_request(request, *args, **kwargs)

    def put(self, request, *args, **kwargs):
        return self.handle_request(request, *args, **kwargs)

    def patch(self, request, *args, **kwargs):
        return self.handle_request(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        return self.handle_request(request, *args, **kwargs)

    def handle_request(self, request, *args, **kwargs):
        return Response(
            {'error': 'Not found'},
            status=status.HTTP_404_NOT_FOUND
        )

class SessionCreateView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    
    def post(self, request):
        serializer = CreateSessionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        # Access the bot through the api key
        bot = request.auth.bot
        
        meeting_url = serializer.validated_data['meeting_url']
        
        session = BotSession.objects.create(
            bot=bot,
            meeting_url=meeting_url
        )

        AnalysisTask.objects.create(
            bot_session=session,
            analysis_type=AnalysisTaskTypes.SPEECH_TRANSCRIPTION,
            analysis_sub_type=AnalysisTaskSubTypes.DEEPGRAM,
            parameters={}
        )
        
        # Try to transition the state from READY to JOINING_REQ_NOT_STARTED_BY_BOT
        BotSessionEventManager.create_event(session, BotSessionEvent.EventTypes.JOIN_REQUESTED_BY_API)

        # Launch the Celery task after successful creation
        run_bot_session.delay(session.id)
        
        return Response(
            SessionSerializer(session).data,
            status=status.HTTP_201_CREATED
        )
        

class LeaveCallView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    
    def send_sync_command(self, session):
        redis_url = os.getenv('REDIS_URL') + ("?ssl_cert_reqs=none" if os.getenv('DISABLE_REDIS_SSL') else "")
        redis_client = redis.from_url(redis_url)
        channel = f"bot_session_{session.id}"
        message = {
            'command': 'sync'
        }
        redis_client.publish(channel, json.dumps(message))

    def post(self, request, object_id):
        try:
            session = BotSession.objects.get(object_id=object_id, bot=request.auth.bot)
            
            BotSessionEventManager.create_event(session, BotSessionEvent.EventTypes.LEAVE_REQUESTED_BY_API)

            self.send_sync_command(session)
            
            return Response(
                SessionSerializer(session).data,
                status=status.HTTP_200_OK
            )
            
        except BotSession.DoesNotExist:
            return Response(
                {'error': 'Session not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )

class TranscriptView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    
    def get(self, request, object_id):
        try:
            session = BotSession.objects.get(object_id=object_id, bot=request.auth.bot)
            
            # Get all utterances with transcriptions, sorted by timeline
            utterances = Utterance.objects.select_related('participant').filter(
                bot_session=session,
                transcription__isnull=False
            ).order_by('timeline_ms')
            
            # Format the response, skipping empty transcriptions
            transcript = [
                {
                    'speaker_name': utterance.participant.full_name,
                    'speaker_uuid': utterance.participant.uuid,
                    'speaker_user_uuid': utterance.participant.user_uuid,
                    'timestamp_ms': utterance.timeline_ms,
                    'duration_ms': utterance.duration_ms,
                    'transcription': utterance.transcription['transcript']
                }
                for utterance in utterances     
                if utterance.transcription.get('words', [])  # Only include if words list is non-empty
            ]
            
            return Response(transcript)
            
        except BotSession.DoesNotExist:
            return Response(
                {'error': 'Session not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )

class SessionDetailView(APIView):
    authentication_classes = [ApiKeyAuthentication]
    
    def get(self, request, object_id):
        try:
            session = BotSession.objects.get(object_id=object_id, bot=request.auth.bot)
            return Response(SessionSerializer(session).data)
            
        except BotSession.DoesNotExist:
            return Response(
                {'error': 'Session not found'}, 
                status=status.HTTP_404_NOT_FOUND
            )
