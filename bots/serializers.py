from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field, extend_schema_serializer, OpenApiExample
from .models import Bot, BotEventTypes, BotEventSubTypes, BotStates, Recording, RecordingStates, RecordingTranscriptionStates
import jsonschema


@extend_schema_field({
    "type": "object",
    "properties": {
        "deepgram": {
            "type": "object",
            "properties": {
                "language": {
                    "type": "string",
                    "description": "The language code for transcription (e.g. 'en'). See here for available languages: https://developers.deepgram.com/docs/models-languages-overview"
                },
                "detect_language": {
                    "type": "boolean",
                    "description": "Whether to automatically detect the spoken language"
                }
            }
        }
    },
    "required": ["deepgram"]
})
class TranscriptionSettingsJSONField(serializers.JSONField): 
    pass

@extend_schema_field({
    "type": "object",
    "properties": {
        "destination_url": {"type": "string", "description": "The URL of the RTMP server to send the stream to"},
        "stream_key": {"type": "string", "description": "The stream key to use for the RTMP server"}
    },
    "required": ["destination_url", "stream_key"]
})
class RTMPSettingsJSONField(serializers.JSONField):
    pass

@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Valid meeting URL',
            value={'meeting_url': 'https://zoom.us/j/123?pwd=456', 'bot_name': 'My Bot'},
            description='Example of a valid Zoom meeting URL'
        )
    ]
)
class CreateBotSerializer(serializers.Serializer):
    meeting_url = serializers.CharField(
        help_text="The URL of the meeting to join, e.g. https://zoom.us/j/123?pwd=456"
    )
    bot_name = serializers.CharField(
        help_text="The name of the bot to create, e.g. 'My Bot'"
    )

    transcription_settings = TranscriptionSettingsJSONField(
        help_text="The transcription settings for the bot, e.g. {'deepgram': {'language': 'en'}}",
        required=False,
        default={
            'deepgram': {
                'language': 'en'
            }
        }
    )

    TRANSCRIPTION_SETTINGS_SCHEMA = {
        "type": "object",
        "properties": {
            "deepgram": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                    },
                    "detect_language": {
                        "type": "boolean"
                    }
                },
                "oneOf": [
                    {"required": ["language"]},
                    {"required": ["detect_language"]}
                ],
                "additionalProperties": False
            }
        },
        "required": ["deepgram"],
        "additionalProperties": False
    }

    def validate_transcription_settings(self, value):
        if value is None:
            return value

        try:
            jsonschema.validate(instance=value, schema=self.TRANSCRIPTION_SETTINGS_SCHEMA)
        except jsonschema.exceptions.ValidationError as e:
            raise serializers.ValidationError(e.message)

        return value

    
    rtmp_settings = RTMPSettingsJSONField(
        help_text="RTMP server to stream to, e.g. {'destination_url': 'rtmp://global-live.mux.com:5222/app', 'stream_key': 'xxxx'}.",
        required=False,
        default=None
    )

    RTMP_SETTINGS_SCHEMA = {
        "type": "object",
        "properties": {
            "destination_url": {"type": "string"},
            "stream_key": {"type": "string"}
        },
        "required": ["destination_url", "stream_key"]
    }

    def validate_rtmp_settings(self, value):
        if value is None:
            return value

        try:
            jsonschema.validate(instance=value, schema=self.RTMP_SETTINGS_SCHEMA)
        except jsonschema.exceptions.ValidationError as e:
            raise serializers.ValidationError(e.message)

        # Validate RTMP URL format
        destination_url = value.get('destination_url', '')
        if not (destination_url.lower().startswith('rtmp://') or destination_url.lower().startswith('rtmps://')):
            raise serializers.ValidationError({
                'destination_url': 'URL must start with rtmp:// or rtmps://'
            })

        return value

class BotSerializer(serializers.ModelSerializer):
    id = serializers.CharField(source='object_id')
    state = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()
    transcription_state = serializers.SerializerMethodField()
    recording_state = serializers.SerializerMethodField()

    @extend_schema_field({
        'type': 'string',
        'enum': [BotStates.state_to_api_code(state.value) for state in BotStates]
    })
    def get_state(self, obj):
        return BotStates.state_to_api_code(obj.state)

    @extend_schema_field({
        'type': 'array',
        'items': {
            'type': 'object',
            'properties': {
                'type': {'type': 'string'},
                'sub_type': {'type': 'string', 'nullable': True},
                'created_at': {'type': 'string', 'format': 'date-time'}
            }
        }
    })
    def get_events(self, obj):
        events = []
        for event in obj.bot_events.all():
            event_type = BotEventTypes.type_to_api_code(event.event_type)
            event_data = {
                'type': event_type,
                'created_at': event.created_at
            }
            
            if event.event_sub_type:
                event_data['sub_type'] = BotEventSubTypes.sub_type_to_api_code(event.event_sub_type)
            
            events.append(event_data)
        return events

    @extend_schema_field({
        'type': 'string',
        'enum': [RecordingTranscriptionStates.state_to_api_code(state.value) for state in RecordingTranscriptionStates],
    })
    def get_transcription_state(self, obj):
        default_recording = Recording.objects.filter(bot=obj, is_default_recording=True).first()
        if not default_recording:
            return None
            
        return RecordingTranscriptionStates.state_to_api_code(default_recording.transcription_state)

    @extend_schema_field({
        'type': 'string',
        'enum': [RecordingStates.state_to_api_code(state.value) for state in RecordingStates],
    })
    def get_recording_state(self, obj):
        default_recording = Recording.objects.filter(bot=obj, is_default_recording=True).first()
        if not default_recording:
            return None
            
        return RecordingStates.state_to_api_code(default_recording.state)

    class Meta:
        model = Bot
        fields = ['id', 'meeting_url', 'state', 'events', 'transcription_state', 'recording_state']
        read_only_fields = fields

class TranscriptUtteranceSerializer(serializers.Serializer):
    speaker_name = serializers.CharField()
    speaker_uuid = serializers.CharField()
    speaker_user_uuid = serializers.CharField(allow_null=True)
    timestamp_ms = serializers.IntegerField()
    duration_ms = serializers.IntegerField()
    transcription = serializers.JSONField()

@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Recording Upload',
            value={'url': 'https://attendee-short-term-storage-production.s3.amazonaws.com/e4da3b7fbbce2345d7772b0674a318d5.mp4?...', 'start_timestamp_ms': 1733114771000},
        )
    ]
)
class RecordingSerializer(serializers.ModelSerializer):
    start_timestamp_ms = serializers.IntegerField(source='first_buffer_timestamp_ms')

    class Meta:
        model = Recording
        fields = ['url', 'start_timestamp_ms']

@extend_schema_field({
    "type": "object",
    "properties": {
        "google": {
            "type": "object",
            "properties": {
                "voice_language_code": {
                    "type": "string",
                    "description": "The voice language code (e.g. 'en-US'). See https://cloud.google.com/text-to-speech/docs/voices for a list of available language codes and voices."
                },
                "voice_name": {
                    "type": "string",
                    "description": "The name of the voice to use (e.g. 'en-US-Casual-K')"
                }
            }
        }
    },
    "required": ["google"]
})
class TextToSpeechSettingsJSONField(serializers.JSONField):
    pass

@extend_schema_serializer(
    examples=[
        OpenApiExample(
            'Valid speech request',
            value={'text': 'Hello, this is a bot speaking text.', 'text_to_speech_settings': {'google': {'voice_language_code': 'en-US', 'voice_name': 'en-US-Casual-K'}}},
            description='Example of a valid speech request'
        )
    ]
)
class SpeechSerializer(serializers.Serializer):
    text = serializers.CharField()
    text_to_speech_settings = TextToSpeechSettingsJSONField()

    TEXT_TO_SPEECH_SETTINGS_SCHEMA = {
        "type": "object",
        "properties": {
            "google": {
                "type": "object",
                "properties": {
                    "voice_language_code": {"type": "string"},
                    "voice_name": {"type": "string"}
                },
                "required": ["voice_language_code", "voice_name"],
                "additionalProperties": False
            }
        },
        "required": ["google"],
        "additionalProperties": False
    }

    def validate_text_to_speech_settings(self, value):
        if value is None:
            return None

        try:
            jsonschema.validate(instance=value, schema=self.TEXT_TO_SPEECH_SETTINGS_SCHEMA)
        except jsonschema.exceptions.ValidationError as e:
            raise serializers.ValidationError(e.message)

        return value
