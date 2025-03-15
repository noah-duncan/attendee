import uuid

from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from unittest.mock import patch

from bots.models import (
    Bot,
    BotStates,
    Organization,
    Project,
    ApiKey,
    WebhookSubscription,
    WebhookSecret,
    WebhookTriggerTypes,
    WebhookDeliveryAttempt,
    WebhookDeliveryAttemptStatus,
)
from bots.tasks.deliver_webhook_task import deliver_webhook
from bots.webhook_utils import sign_payload, verify_signature

class WebhookSubscriptionTest(APITestCase):
    def setUp(self):
        """Set up test data"""
        # Create organization and project
        self.organization = Organization.objects.create(name="Test Org")
        self.project = Project.objects.create(
            name="Test Project",
            organization=self.organization
        )
        
        # Create API key for authentication
        self.api_key, self.api_key_plain = ApiKey.create(
            project=self.project,
            name="Test API Key"
        )
        
        # Set up authentication header
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.api_key_plain}')
        
        # URL for webhook subscription endpoint
        self.url = reverse('webhook-subscription')
        
        # Valid webhook data
        self.valid_webhook_data = {
            "url": "https://example.com/webhook",
            "events": [WebhookTriggerTypes.BOT_STATE_CHANGE]
        }

    def test_create_webhook_subscription_success(self):
        """Test successful webhook subscription creation"""
        response = self.client.post(self.url, self.valid_webhook_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(WebhookSubscription.objects.count(), 1)
        
        # Verify response data
        self.assertEqual(response.data['url'], self.valid_webhook_data['url'])
        self.assertEqual(response.data['events'], self.valid_webhook_data['events'])
        
        # Verify webhook secret was created
        self.assertTrue(WebhookSecret.objects.filter(project=self.project).exists())

    def test_create_webhook_subscription_duplicate_url(self):
        """Test that duplicate URLs are not allowed"""
        # Create first subscription
        self.client.post(self.url, self.valid_webhook_data, format='json')
        
        # Try to create second subscription with same URL
        response = self.client.post(self.url, self.valid_webhook_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(WebhookSubscription.objects.count(), 1)
        self.assertEqual(response.data['error'], 'URL already subscribed')

    def test_create_webhook_subscription_invalid_url(self):
        """Test validation of invalid URLs"""
        invalid_data = self.valid_webhook_data.copy()
        invalid_data['url'] = 'not-a-url'
        
        response = self.client.post(self.url, invalid_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(WebhookSubscription.objects.count(), 0)

    def test_create_webhook_subscription_invalid_events(self):
        """Test validation of invalid events"""
        invalid_data = self.valid_webhook_data.copy()
        invalid_data['events'] = ['invalid.event']
        
        response = self.client.post(self.url, invalid_data, format='json')
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(WebhookSubscription.objects.count(), 0)

    def test_create_webhook_subscription_unauthorized(self):
        """Test that authentication is required"""
        # Remove authentication credentials
        self.client.credentials()
        
        response = self.client.post(self.url, self.valid_webhook_data, format='json')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_webhook_secret_reuse(self):
        """Test that existing webhook secret is reused for same project"""
        # Create first subscription which should create a secret
        response1 = self.client.post(self.url, self.valid_webhook_data, format='json')
        first_secret = WebhookSecret.objects.get(project=self.project)
        
        # Create second subscription with different URL
        different_url_data = self.valid_webhook_data.copy()
        different_url_data['url'] = 'https://another-example.com/webhook'
        response2 = self.client.post(self.url, different_url_data, format='json')
        
        # Verify same secret is used
        self.assertEqual(WebhookSecret.objects.filter(project=self.project).count(), 1)
        second_secret = WebhookSecret.objects.get(project=self.project)
        self.assertEqual(first_secret.id, second_secret.id) 

    def test_signature_verification(self):
        payload = {'test': 'data', 'number': 123}
        secret = b'testsecret'
        
        signature = sign_payload(payload, secret)
        
        # Verify the signature
        self.assertTrue(verify_signature(payload, signature, secret))
        
        # Modify the payload and verify that the signature is invalid
        modified_payload = payload.copy()
        modified_payload['number'] = 456
        self.assertFalse(verify_signature(modified_payload, signature, secret))

class WebhookDeliveryTest(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Test Project", organization=self.organization)
        self.webhook_subscription = WebhookSubscription.objects.create(
            project=self.project,
            url="https://example.com/webhook",
            events=[WebhookTriggerTypes.BOT_STATE_CHANGE],
            secret=WebhookSecret.objects.create(project=self.project)
        )
        self.bot = Bot.objects.create(
            project=self.project,
            meeting_url="https://zoom.us/j/123",
            state=BotStates.READY
        )

    @patch('bots.tasks.deliver_webhook_task.requests.post')
    def test_webhook_delivery_success(self, mock_post):
        """Test successful webhook delivery"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "OK"

        # Create delivery attempt
        attempt = WebhookDeliveryAttempt.objects.create(
            webhook_subscription=self.webhook_subscription,
            webhook_event_type=WebhookTriggerTypes.BOT_STATE_CHANGE,
            bot=self.bot,
            idempotency_key=uuid.uuid4(),
            payload={"test": "data"}
        )

        # Call delivery task
        deliver_webhook.apply(args=[attempt.id])

        # Verify request was made with correct data
        mock_post.assert_called_once()
        self.assertEqual(attempt.status, WebhookDeliveryAttemptStatus.SUCCESS)
        self.assertIsNotNone(attempt.succeeded_at)

    @patch('bots.tasks.deliver_webhook_task.requests.post')
    def test_webhook_delivery_failure(self, mock_post):
        """Test webhook delivery failure and retry"""
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "Server Error"

        attempt = WebhookDeliveryAttempt.objects.create(
            webhook_subscription=self.webhook_subscription,
            webhook_event_type=WebhookTriggerTypes.BOT_STATE_CHANGE,
            bot=self.bot,
            idempotency_key=uuid.uuid4(),
            payload={"test": "data"}
        )

        # Call delivery task
        deliver_webhook.apply(args=[attempt.id])

        self.assertEqual(attempt.status, WebhookDeliveryAttemptStatus.FAILURE)
        self.assertIsNone(attempt.succeeded_at)
        self.assertEqual(attempt.attempt_count, 1)