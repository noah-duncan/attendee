import json
import datetime
import requests
import logging
from celery import shared_task
from django.utils import timezone
from bots.models import WebhookDeliveryAttempt
from bots.utils import sign_payload

logger = logging.getLogger(__name__)

@shared_task(
    bind=True, 
    max_retries=None,
    retry_backoff=True,  # Enable exponential backoff
    max_retries=5,
)
def deliver_webhook(self, delivery_id):
    """
    Deliver a webhook to its destination.
    """
    try:
        delivery = WebhookDeliveryAttempt.objects.get(id=delivery_id)
    except WebhookDeliveryAttempt.DoesNotExist:
        logger.error(f"Webhook delivery attempt {delivery_id} not found")
        return
    
    subscription = delivery.subscription
    
    # If the subscription is no longer active, mark as failed and return
    if not subscription.is_active:
        delivery.status = 'failed'
        delivery.error_message = 'Webhook subscription is no longer active'
        delivery.save()
        return
    
    # Prepare the webhook payload
    webhook_data = {
        'id': str(delivery.id),
        'event': delivery.event_type,
        'created': delivery.created_at.isoformat(),
        'data': delivery.payload
    }
    
    # Sign the payload
    signature = sign_payload(webhook_data, subscription.secret)
    
    # Increment attempt counter
    delivery.attempt_count += 1
    delivery.last_attempt_at = timezone.now()
    
    # Send the webhook
    try:
        response = requests.post(
            subscription.url,
            json=webhook_data,
            headers={
                'Content-Type': 'application/json',
                'User-Agent': 'Attendee-Webhook/1.0',
                'X-Webhook-Signature': signature
            },
            timeout=10  # 10-second timeout
        )
        
        # Update the delivery attempt with the response
        delivery.response_status_code = response.status_code
        
        # Limit response body storage to prevent DB issues with large responses
        response_body = response.text[:10000]
        delivery.response_body_list.append(response_body)
        
        # Check if the delivery was successful (2xx status code)
        if 200 <= response.status_code < 300:
            delivery.status = WebhookDeliveryAttemptStatus.SUCCESS
            delivery.succeeded_at = timezone.now()
            delivery.save()
            return
        
        # If we got here, the delivery failed with a non-2xx status code
        delivery.status = WebhookDeliveryAttemptStatus.FAILURE
        
    except requests.RequestException as e:
        # Handle network errors, timeouts, etc.
        delivery.status = WebhookDeliveryAttemptStatus.FAILURE
    
    delivery.save()

    # Check if this was the last retry attempt
    if delivery.attempt_count >= self.max_retries and delivery.status == WebhookDeliveryAttemptStatus.FAILURE:
        logger.error(
            f"Webhook delivery failed after {delivery.attempt_count} attempts. "
            f"Webhook ID: {delivery.id}, URL: {subscription.url}, "
            f"Event: {delivery.event_type}, Status: {delivery.status}"
        )