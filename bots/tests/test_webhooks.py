from django.test import TestCase
from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase

from bots.models import (
    Organization,
    Project,
    ApiKey,
    WebhookSubscription,
    WebhookSecret,
    WebhookEventTypes,
)


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
            "events": [WebhookEventTypes.BOT_EVENTS]
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