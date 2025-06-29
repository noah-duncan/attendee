import uuid
from unittest.mock import patch

from django.contrib.messages.storage.fallback import FallbackStorage
from django.http import Http404, HttpRequest
from django.http.request import QueryDict
from django.test import TransactionTestCase

from accounts.models import User
from bots.models import (
    Bot,
    BotStates,
    Organization,
    Project,
    WebhookDeliveryAttempt,
    WebhookDeliveryAttemptStatus,
    WebhookSecret,
    WebhookSubscription,
    WebhookTriggerTypes,
)
from bots.projects_views import CreateWebhookView, DeleteWebhookView, ProjectWebhooksView
from bots.tasks.deliver_webhook_task import deliver_webhook
from bots.webhook_utils import sign_payload, verify_signature


class WebhookSubscriptionTest(TransactionTestCase):
    def setUp(self):
        # Create test user with organization
        self.organization = Organization.objects.create(name="Test Organization")
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpassword")
        self.user.organization = self.organization
        self.user.save()

        # Create test project
        self.project = Project.objects.create(
            name="Test Project",
            organization=self.organization,
        )

        # Create test webhook subscriptions
        self.webhook_subscriptions = [
            WebhookSubscription.objects.create(project=self.project, url="https://example.com/webhook1", triggers=[WebhookTriggerTypes.BOT_STATE_CHANGE]),
            WebhookSubscription.objects.create(project=self.project, url="https://example.com/webhook2", triggers=[WebhookTriggerTypes.BOT_STATE_CHANGE]),
        ]

        # Create webhook secret
        self.webhook_secret = WebhookSecret.objects.create(project=self.project)

        self.get_webhooks_view = ProjectWebhooksView()
        self.create_webhook_view = CreateWebhookView()
        self.delete_webhook_view = DeleteWebhookView()

        # Configure Celery to run tasks eagerly (synchronously)
        from django.conf import settings

        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = True

    def _get_request(self, user=None, method="GET", post_data=None):
        """Helper method to create a request object"""
        request = HttpRequest()
        request.method = method

        # Set the user if provided
        if user:
            request.user = user

        # Set POST data if provided
        if method == "POST" and post_data:
            # Create a QueryDict from the post_data
            q_dict = QueryDict("", mutable=True)
            for key, value in post_data.items():
                if isinstance(value, list):
                    for item in value:
                        q_dict.update({key: item})
                else:
                    q_dict[key] = value
            request.POST = q_dict

        # Add messages support to request
        setattr(request, "session", "session")
        messages = FallbackStorage(request)
        setattr(request, "_messages", messages)

        return request

    def test_project_webhooks_view(self):
        """Test that project webhooks view renders correctly"""
        request = self._get_request(user=self.user)

        # Call the view directly
        response = self.get_webhooks_view.get(request, self.project.object_id)

        # Check response code
        self.assertEqual(response.status_code, 200)

    def test_project_webhooks_view_unauthorized(self):
        """Test that unauthorized users cannot access the webhooks view"""
        # Create another organization and project
        other_org = Organization.objects.create(name="Other Organization")
        other_project = Project.objects.create(name="Other Project", organization=other_org)

        # Create request
        request = self._get_request(user=self.user)

        # Patch the get_object_or_404 function to simulate a 404
        with patch("django.shortcuts.get_object_or_404") as mock_get_object:
            mock_get_object.side_effect = Http404()

            # This should raise Http404
            with self.assertRaises(Http404):
                self.get_webhooks_view.get(request, other_project.object_id)

    def test_create_webhook_subscription_success(self):
        # Clear the existing webhooks
        WebhookSubscription.objects.filter(project=self.project).delete()

        """Test successful webhook subscription creation"""
        # New webhook data
        webhook_data = {
            "url": "https://example.com/new-webhook",
            "triggers[]": [
                WebhookTriggerTypes.trigger_type_to_api_code(WebhookTriggerTypes.BOT_STATE_CHANGE),
            ],
        }

        # Create a mock request
        request = self._get_request(user=self.user, method="POST", post_data=webhook_data)

        # Call the view directly
        response = self.create_webhook_view.post(request, self.project.object_id)

        # Check response status
        self.assertEqual(response.status_code, 200)

        # Check that webhook was created in database
        new_webhook = WebhookSubscription.objects.get(url="https://example.com/new-webhook")
        self.assertIsNotNone(new_webhook)
        self.assertEqual(new_webhook.project, self.project)
        self.assertEqual(
            set(new_webhook.triggers),
            set(
                [
                    WebhookTriggerTypes.BOT_STATE_CHANGE,
                ]
            ),
        )

    def test_create_webhook_invalid_url(self):
        """Test webhook creation with invalid URL (non-HTTPS)"""
        # Clear the existing webhooks to avoid hitting limits
        WebhookSubscription.objects.filter(project=self.project).delete()

        webhook_data = {"url": "http://example.com/insecure", "triggers[]": [WebhookTriggerTypes.trigger_type_to_api_code(WebhookTriggerTypes.BOT_STATE_CHANGE)]}

        request = self._get_request(user=self.user, method="POST", post_data=webhook_data)
        response = self.create_webhook_view.post(request, self.project.object_id)

        # Check for error response
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "webhook URL must start with https://")

        # Verify webhook wasn't created
        self.assertFalse(WebhookSubscription.objects.filter(url="http://example.com/insecure").exists())

    def test_create_webhook_duplicate_url(self):
        """Test webhook creation with already existing URL"""
        # Clear existing webhooks first, then create one to test duplication
        WebhookSubscription.objects.filter(project=self.project).delete()

        # Create a webhook to test duplication against
        WebhookSubscription.objects.create(project=self.project, url="https://example.com/webhook1", triggers=[WebhookTriggerTypes.BOT_STATE_CHANGE])

        webhook_data = {
            "url": "https://example.com/webhook1",  # This URL now exists
            "triggers[]": [WebhookTriggerTypes.trigger_type_to_api_code(WebhookTriggerTypes.BOT_STATE_CHANGE)],
        }

        request = self._get_request(user=self.user, method="POST", post_data=webhook_data)
        response = self.create_webhook_view.post(request, self.project.object_id)

        # Check for error response
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "URL already subscribed")

    def test_create_webhook_invalid_event(self):
        # Clear the existing webhooks
        WebhookSubscription.objects.filter(project=self.project).delete()

        """Test webhook creation with invalid event type"""
        webhook_data = {
            "url": "https://example.com/new-webhook",
            "triggers[]": [9999],  # Invalid event type integer
        }

        request = self._get_request(user=self.user, method="POST", post_data=webhook_data)
        response = self.create_webhook_view.post(request, self.project.object_id)

        # Check for error response
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.content.decode(), "Invalid webhook trigger type: 9999")

    def test_delete_webhook(self):
        """Test webhook deletion"""
        request = self._get_request(user=self.user, method="DELETE")
        response = self.delete_webhook_view.delete(request, self.project.object_id, self.webhook_subscriptions[0].object_id)

        # Check response
        self.assertEqual(response.status_code, 200)

        # Verify webhook is deleted
        self.assertFalse(WebhookSubscription.objects.filter(object_id=self.webhook_subscriptions[0].object_id).exists())

    def test_delete_webhook_unauthorized(self):
        """Test unauthorized webhook deletion"""
        # Create webhook in another org
        other_org = Organization.objects.create(name="Other Organization")
        other_project = Project.objects.create(name="Other Project", organization=other_org)
        other_webhook = WebhookSubscription.objects.create(project=other_project, url="https://example.com/other-webhook", triggers=[WebhookTriggerTypes.BOT_STATE_CHANGE])

        request = self._get_request(user=self.user, method="DELETE")

        # Patch the get_object_or_404 function to simulate a 404
        with patch("django.shortcuts.get_object_or_404") as mock_get_object:
            mock_get_object.side_effect = Http404()

            # This should raise Http404
            with self.assertRaises(Http404):
                self.delete_webhook_view.delete(request, other_project.object_id, other_webhook.object_id)

        # Webhook should still exist
        self.assertTrue(WebhookSubscription.objects.filter(object_id=other_webhook.object_id).exists())

    def test_webhook_secret_reuse(self):
        """Test that existing webhook secret is reused for same project"""
        # Create first subscription which should create a secret
        webhook_data = {
            "url": "https://example.com/new-webhook",
            "triggers[]": [
                WebhookTriggerTypes.trigger_type_to_api_code(WebhookTriggerTypes.BOT_STATE_CHANGE),
            ],
        }
        request = self._get_request(user=self.user, method="POST", post_data=webhook_data)
        self.create_webhook_view.post(request, self.project.object_id)
        first_secret = WebhookSecret.objects.get(project=self.project)

        # Create second subscription with different URL
        different_url_data = webhook_data.copy()
        different_url_data["url"] = "https://another-example.com/webhook"
        request = self._get_request(user=self.user, method="POST", post_data=different_url_data)
        self.create_webhook_view.post(request, self.project.object_id)

        # Verify same secret is used
        self.assertEqual(WebhookSecret.objects.filter(project=self.project).count(), 1)
        second_secret = WebhookSecret.objects.get(project=self.project)
        self.assertEqual(first_secret.id, second_secret.id)

    def test_signature_verification(self):
        payload = {"test": "data", "number": 123}
        secret = b"testsecret"

        signature = sign_payload(payload, secret)

        # Verify the signature
        self.assertTrue(verify_signature(payload, signature, secret))

        # Modify the payload and verify that the signature is invalid
        modified_payload = payload.copy()
        modified_payload["number"] = 456
        self.assertFalse(verify_signature(modified_payload, signature, secret))


class WebhookDeliveryTest(TransactionTestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Test Project", organization=self.organization)
        self.webhook_subscription = WebhookSubscription.objects.create(
            project=self.project,
            url="https://example.com/webhook",
            triggers=[
                WebhookTriggerTypes.BOT_STATE_CHANGE,
            ],
        )
        # Create webhook secret
        self.webhook_secret = WebhookSecret.objects.create(project=self.project)
        self.bot = Bot.objects.create(
            project=self.project,
            meeting_url="https://zoom.us/j/123",
            state=BotStates.READY,
        )

        # Configure Celery to run tasks eagerly (synchronously)
        from django.conf import settings

        settings.CELERY_TASK_ALWAYS_EAGER = True
        settings.CELERY_TASK_EAGER_PROPAGATES = True

    @patch("bots.tasks.deliver_webhook_task.requests.post")
    def test_webhook_delivery_success(self, mock_post):
        """Test successful webhook delivery"""
        mock_post.return_value.status_code = 200
        mock_post.return_value.text = "OK"

        # Create delivery attempt
        attempt = WebhookDeliveryAttempt.objects.create(
            webhook_subscription=self.webhook_subscription,
            webhook_trigger_type=WebhookTriggerTypes.BOT_STATE_CHANGE,
            bot=self.bot,
            idempotency_key=uuid.uuid4(),
            payload={"test": "data"},
        )

        # Call delivery task
        deliver_webhook.apply(args=[attempt.id])

        # Refresh the attempt object from the db
        attempt.refresh_from_db()

        # Verify request was made with correct data
        mock_post.assert_called_once()
        self.assertTrue(isinstance(attempt.status, int))
        self.assertEqual(attempt.status, WebhookDeliveryAttemptStatus.SUCCESS)
        self.assertEqual(len(attempt.response_body_list), 1)
        self.assertIsNotNone(attempt.succeeded_at)

    @patch("bots.tasks.deliver_webhook_task.requests.post")
    def test_webhook_delivery_failure(self, mock_post):
        """Test webhook delivery failure and retry"""
        mock_post.return_value.status_code = 500
        mock_post.return_value.text = "Server Error"

        attempt = WebhookDeliveryAttempt.objects.create(
            webhook_subscription=self.webhook_subscription,
            webhook_trigger_type=WebhookTriggerTypes.BOT_STATE_CHANGE,
            bot=self.bot,
            idempotency_key=uuid.uuid4(),
            payload={"test": "data"},
        )

        # Call delivery task - manually simulate the retries
        for _ in range(3):
            try:
                deliver_webhook.apply(args=[attempt.id])
            except:
                # Ignore the retry exception
                pass

        # Refresh the attempt object from the db
        attempt.refresh_from_db()

        self.assertTrue(isinstance(attempt.status, int))
        self.assertEqual(attempt.status, WebhookDeliveryAttemptStatus.FAILURE)
        self.assertEqual(len(attempt.response_body_list), 3)
        self.assertIsNone(attempt.succeeded_at)
        self.assertEqual(attempt.attempt_count, 3)

    @patch("bots.tasks.deliver_webhook_task.requests.post")
    def test_webhook_delivery_inactive(self, mock_post):
        """Test webhook delivery does not deliver when the subscription is inactive"""

        attempt = WebhookDeliveryAttempt.objects.create(
            webhook_subscription=self.webhook_subscription,
            webhook_trigger_type=WebhookTriggerTypes.BOT_STATE_CHANGE,
            bot=self.bot,
            idempotency_key=uuid.uuid4(),
            payload={"test": "data"},
        )
        attempt.webhook_subscription.is_active = False
        attempt.webhook_subscription.save()

        # Call delivery task
        deliver_webhook.apply(args=[attempt.id])

        # Refresh the attempt object from the db
        attempt.refresh_from_db()

        self.assertEqual(attempt.status, WebhookDeliveryAttemptStatus.FAILURE)
        self.assertEqual(len(attempt.response_body_list), 1)
        self.assertIsNone(attempt.response_body_list[0]["status_code"])
        self.assertIsNone(attempt.succeeded_at)
        self.assertEqual(attempt.attempt_count, 0)
