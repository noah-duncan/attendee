import base64
import hashlib
import hmac
import json
import logging
import uuid

logger = logging.getLogger(__name__)


def trigger_webhook(webhook_event_type, bot, payload):
    """
    Trigger a webhook for a given event.
    """
    from bots.models import WebhookDeliveryAttempt, WebhookSubscription

    subscriptions = WebhookSubscription.objects.filter(events__contains=[webhook_event_type], is_active=True)

    delivery_attempts = []
    for subscription in subscriptions:
        # Create a webhook delivery attempt record
        delivery_attempt = WebhookDeliveryAttempt.objects.create(
            webhook_subscription=subscription,
            webhook_event_type=webhook_event_type,
            idempotency_key=uuid.uuid4(),
            bot=bot,
            payload=payload,
        )
        delivery_attempts.append(delivery_attempt)

        from bots.tasks.deliver_webhook_task import deliver_webhook

        deliver_webhook.delay(delivery_attempt.id)

    return len(delivery_attempts)


def sign_payload(payload, secret):
    """
    Sign a webhook payload using HMAC-SHA256. Returns a base64-encoded HMAC-SHA256 signature
    """
    # Convert the payload to a canonical JSON string
    payload_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))

    # Create the signature
    signature = hmac.new(secret, payload_json.encode("utf-8"), hashlib.sha256).digest()

    # Return base64 encoded signature
    return base64.b64encode(signature).decode("utf-8")


def verify_signature(payload, signature, secret):
    """
    Verify a webhook signature. Not used in production, but useful for testing.
    """
    expected_signature = sign_payload(payload, secret)

    # Use constant-time comparison to prevent timing attacks
    return hmac.compare_digest(signature, expected_signature)
