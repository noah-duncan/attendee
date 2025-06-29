import json
import logging
import os
from enum import Enum

import redis
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse

from .models import (
    Bot,
    BotChatMessageRequest,
    BotEventManager,
    BotEventTypes,
    BotMediaRequest,
    BotMediaRequestMediaTypes,
    BotStates,
    Credentials,
    MediaBlob,
    MeetingTypes,
    Project,
    Recording,
    TranscriptionTypes,
    WebhookSecret,
    WebhookSubscription,
    WebhookTriggerTypes,
)
from .serializers import (
    CreateBotSerializer,
)
from .utils import meeting_type_from_url, transcription_provider_from_meeting_url_and_transcription_settings

logger = logging.getLogger(__name__)


def send_sync_command(bot, command="sync"):
    redis_url = os.getenv("REDIS_URL") + ("?ssl_cert_reqs=none" if os.getenv("DISABLE_REDIS_SSL") else "")
    redis_client = redis.from_url(redis_url)
    channel = f"bot_{bot.id}"
    message = {"command": command}
    redis_client.publish(channel, json.dumps(message))


def create_bot_chat_message_request(bot, chat_message_data):
    """
    Creates a BotChatMessageRequest for the given bot with the provided data.

    Args:
        bot: The Bot instance
        chat_message_data: Validated data containing to_user_uuid, to, and message

    Returns:
        BotChatMessageRequest: The created chat message request
    """
    try:
        bot_chat_message_request = BotChatMessageRequest.objects.create(
            bot=bot,
            to_user_uuid=chat_message_data.get("to_user_uuid"),
            to=chat_message_data["to"],
            message=chat_message_data["message"],
        )
    except Exception as e:
        error_message_first_line = str(e).split("\n")[0]
        logging.error(f"Error creating bot chat message request: {error_message_first_line}")
        raise ValidationError(f"Error creating the bot chat message request: {error_message_first_line}.")

    return bot_chat_message_request


def create_bot_media_request_for_image(bot, image):
    content_type = image["type"]
    image_data = image["decoded_data"]
    try:
        # Create or get existing MediaBlob
        media_blob = MediaBlob.get_or_create_from_blob(project=bot.project, blob=image_data, content_type=content_type)
    except Exception as e:
        error_message_first_line = str(e).split("\n")[0]
        logging.error(f"Error creating image blob: {error_message_first_line} (content_type={content_type})")
        raise ValidationError(f"Error creating the image blob: {error_message_first_line}.")

    # Create BotMediaRequest
    BotMediaRequest.objects.create(
        bot=bot,
        media_blob=media_blob,
        media_type=BotMediaRequestMediaTypes.IMAGE,
    )


def validate_meeting_url_and_credentials(meeting_url, project):
    """
    Validates meeting URL format and required credentials.
    Returns error message if validation fails, None if validation succeeds.
    """

    if meeting_type_from_url(meeting_url) == MeetingTypes.ZOOM:
        zoom_credentials = project.credentials.filter(credential_type=Credentials.CredentialTypes.ZOOM_OAUTH).first()
        if not zoom_credentials:
            relative_url = reverse("bots:project-credentials", kwargs={"object_id": project.object_id})
            settings_url = f"https://{os.getenv('SITE_DOMAIN', 'app.attendee.dev')}{relative_url}"
            return {"error": f"Zoom App credentials are required to create a Zoom bot. Please add Zoom credentials at {settings_url}"}

    return None


class BotCreationSource(str, Enum):
    API = "api"
    DASHBOARD = "dashboard"
    SCHEDULER = "scheduler"


def create_bot(data: dict, source: BotCreationSource, project: Project) -> tuple[Bot | None, dict | None]:
    # Given them a small grace period before we start rejecting requests
    if project.organization.out_of_credits():
        logger.error(f"Organization {project.organization.id} has insufficient credits. Please add credits in the Settings -> Billing page.")
        return None, {"error": "Organization has run out of credits. Please add more credits in the Settings -> Billing page."}

    serializer = CreateBotSerializer(data=data)
    if not serializer.is_valid():
        return None, serializer.errors

    # Access the bot through the api key
    meeting_url = serializer.validated_data["meeting_url"]

    error = validate_meeting_url_and_credentials(meeting_url, project)
    if error:
        return None, error

    bot_name = serializer.validated_data["bot_name"]
    transcription_settings = serializer.validated_data["transcription_settings"]
    rtmp_settings = serializer.validated_data["rtmp_settings"]
    recording_settings = serializer.validated_data["recording_settings"]
    debug_settings = serializer.validated_data["debug_settings"]
    automatic_leave_settings = serializer.validated_data["automatic_leave_settings"]
    teams_settings = serializer.validated_data["teams_settings"]
    bot_image = serializer.validated_data["bot_image"]
    bot_chat_message = serializer.validated_data["bot_chat_message"]
    metadata = serializer.validated_data["metadata"]
    join_at = serializer.validated_data["join_at"]
    webhook_subscriptions = serializer.validated_data["webhooks"]
    initial_state = BotStates.SCHEDULED if join_at else BotStates.READY

    settings = {
        "transcription_settings": transcription_settings,
        "rtmp_settings": rtmp_settings,
        "recording_settings": recording_settings,
        "debug_settings": debug_settings,
        "automatic_leave_settings": automatic_leave_settings,
        "teams_settings": teams_settings,
    }

    with transaction.atomic():
        bot = Bot.objects.create(
            project=project,
            meeting_url=meeting_url,
            name=bot_name,
            settings=settings,
            metadata=metadata,
            join_at=join_at,
            state=initial_state,
        )

        Recording.objects.create(
            bot=bot,
            recording_type=bot.recording_type(),
            transcription_type=TranscriptionTypes.NON_REALTIME,
            transcription_provider=transcription_provider_from_meeting_url_and_transcription_settings(meeting_url, transcription_settings),
            is_default_recording=True,
        )

        if bot_image:
            try:
                create_bot_media_request_for_image(bot, bot_image)
            except ValidationError as e:
                return None, {"error": e.messages[0]}

        if bot_chat_message:
            try:
                create_bot_chat_message_request(bot, bot_chat_message)
            except ValidationError as e:
                return None, {"error": e.messages[0]}

        # Create bot-level webhook subscriptions if provided
        if webhook_subscriptions:
            success, error = create_webhook_subscriptions(webhook_subscriptions, project, bot)
            if not success:
                return None, {"error": error}

        if bot.state == BotStates.READY:
            # Try to transition the state from READY to JOINING
            BotEventManager.create_event(bot=bot, event_type=BotEventTypes.JOIN_REQUESTED, event_metadata={"source": source})

        return bot, None


def validate_webhook_data(url, triggers, project, bot=None, check_limits=True):
    """
    Validates webhook URL and triggers for both project-level and bot-level webhooks.
    Returns error message and normalized triggers if validation succeeds.

    Args:
        url: The webhook URL
        triggers: List of trigger types (strings or integers)
        project: The Project instance
        bot: Optional Bot instance for bot-level webhooks
        check_limits: Whether to check webhook limits (default: True)

    Returns:
        tuple: (error_message, normalized_triggers)
               error_message is None if validation succeeds
               normalized_triggers is list of integers if validation succeeds
    """
    # Normalize triggers (convert strings to integers)
    normalized_triggers = WebhookTriggerTypes.normalize_triggers(triggers)
    if normalized_triggers is None:
        # Find the first invalid trigger for a more helpful error message
        invalid_triggers = []
        for t in triggers:
            if isinstance(t, str) and WebhookTriggerTypes.api_code_to_trigger_type(t) is None:
                invalid_triggers.append(t)
            elif isinstance(t, int) and t not in [trigger_type.value for trigger_type in WebhookTriggerTypes]:
                invalid_triggers.append(t)
            elif not isinstance(t, (str, int)):
                invalid_triggers.append(t)

        error_msg = f"Invalid webhook trigger type: {invalid_triggers[0] if invalid_triggers else 'unknown'}"
        return error_msg, None

    # Check if URL is valid
    if not url.startswith("https://"):
        return "webhook URL must start with https://", None

    # Check for duplicate URLs
    existing_webhook_query = WebhookSubscription.objects.filter(url=url, project=project)
    if bot:
        # For bot-level webhooks, check if URL already exists for this bot
        if existing_webhook_query.filter(bot=bot).exists():
            return "URL already subscribed for this bot", None
    else:
        # For project-level webhooks, check if URL already exists for project
        if existing_webhook_query.filter(bot__isnull=True).exists():
            return "URL already subscribed", None

    # Webhook limit check (only if check_limits is True)
    if check_limits:
        if not bot:
            # For project-level webhooks, check the limit (only count project-level webhooks)
            project_level_webhooks = WebhookSubscription.objects.filter(project=project, bot__isnull=True).count()
            if project_level_webhooks >= 2:
                return "You have reached the maximum number of webhooks", None

    return None, normalized_triggers


def create_webhook_subscription(url, triggers, project, bot=None):
    """
    Creates a single webhook subscription for a project or bot.

    Args:
        url: The webhook URL
        triggers: List of trigger types (strings or integers)
        project: The Project instance
        bot: Optional Bot instance for bot-level webhooks

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    # Validate the webhook data
    error, normalized_triggers = validate_webhook_data(url, triggers, project, bot)
    if error:
        return False, error

    # Get or create webhook secret for the project
    WebhookSecret.objects.get_or_create(project=project)

    # Create the webhook subscription
    WebhookSubscription.objects.create(
        project=project,
        bot=bot,
        url=url,
        triggers=normalized_triggers,
    )

    return True, None


def create_webhook_subscriptions(webhook_data_list, project, bot=None):
    """
    Creates multiple webhook subscriptions for a project or bot.

    Args:
        webhook_data_list: List of webhook data dictionaries with 'url' and 'triggers'
        project: The Project instance
        bot: Optional Bot instance for bot-level webhooks

    Returns:
        tuple: (success: bool, error_message: str or None)
    """
    if not webhook_data_list:
        return True, None

    # Create all webhook subscriptions
    for webhook_data in webhook_data_list:
        url = webhook_data.get("url")
        triggers = webhook_data.get("triggers", [])

        success, error = create_webhook_subscription(url, triggers, project, bot)
        if not success:
            return False, error

    return True, None
