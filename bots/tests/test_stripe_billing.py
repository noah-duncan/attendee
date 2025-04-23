import json
import os
from unittest.mock import MagicMock, patch
from uuid import uuid4

import stripe
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Organization, User
from bots.models import CreditTransaction, Project
from bots.stripe_utils import process_checkout_session_completed


class StripeBillingTestCase(TestCase):
    def setUp(self):
        # Create test org and user
        self.org = Organization.objects.create(name="Test Org", centicredits=1000)
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123", organization=self.org)
        self.project = Project.objects.create(name="Test Project", organization=self.org)
        self.client = Client()
        self.client.force_login(self.user)

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session(self, mock_session_create):
        # Mock the Stripe checkout session response
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test-session"
        mock_session_create.return_value = mock_session

        # Test with a valid purchase amount
        response = self.client.post(reverse("bots:create-checkout-session", kwargs={"object_id": self.project.object_id}), {"purchase_amount": "50.0"})

        # Check that we got redirected to Stripe
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, "https://checkout.stripe.com/test-session")

        # Verify Stripe was called correctly
        mock_session_create.assert_called_once()
        call_kwargs = mock_session_create.call_args.kwargs

        # Check line items
        self.assertEqual(call_kwargs["line_items"][0]["price_data"]["unit_amount"], 5000)  # $50.00 in cents
        self.assertEqual(call_kwargs["line_items"][0]["price_data"]["currency"], "usd")

        # Check metadata
        self.assertEqual(call_kwargs["metadata"]["organization_id"], str(self.org.id))
        self.assertEqual(call_kwargs["metadata"]["user_id"], str(self.user.id))
        self.assertEqual(call_kwargs["metadata"]["credit_amount"], "100")  # $50 at $0.50 per credit = 100 credits

    @patch("stripe.checkout.Session.create")
    def test_create_checkout_session_invalid_amounts(self, mock_session_create):
        # Test with an invalid amount (too high)
        response = self.client.post(
            reverse("bots:create-checkout-session", kwargs={"object_id": self.project.object_id}),
            {"purchase_amount": "15000.0"},  # $15,000 exceeds the $10,000 limit
        )
        self.assertEqual(response.status_code, 400)
        mock_session_create.assert_not_called()
        mock_session_create.reset_mock()

        # Test with a negative amount (should be corrected to minimum)
        mock_session = MagicMock()
        mock_session.url = "https://checkout.stripe.com/test-session"
        mock_session_create.return_value = mock_session

        response = self.client.post(reverse("bots:create-checkout-session", kwargs={"object_id": self.project.object_id}), {"purchase_amount": "-10.0"})
        self.assertEqual(response.status_code, 302)
        mock_session_create.assert_called_once()

        # Check it was corrected to the minimum amount
        call_kwargs = mock_session_create.call_args.kwargs
        # Should be at least $1 ($1 / $0.50 per credit = 2 credits)
        self.assertGreaterEqual(int(call_kwargs["metadata"]["credit_amount"]), 1)

    @patch("stripe.checkout.Session.retrieve")
    def test_checkout_success(self, mock_retrieve):
        # Mock the Stripe session response
        mock_session = MagicMock()
        mock_session.payment_intent = "pi_test123"
        mock_session.amount_total = 5000  # $50.00 in cents
        mock_session.metadata = {"organization_id": str(self.org.id), "user_id": str(self.user.id), "credit_amount": "100"}
        mock_retrieve.return_value = mock_session

        # Record initial credit balance
        initial_credits = self.org.centicredits

        # Test the success callback
        response = self.client.get(reverse("bots:checkout-success", kwargs={"object_id": self.project.object_id}), {"session_id": "cs_test123"})

        mock_retrieve.assert_called_once_with("cs_test123", api_key=os.getenv("STRIPE_SECRET_KEY"))

        # Check that a credit transaction was created with the correct values
        self.org.refresh_from_db()
        transaction = CreditTransaction.objects.filter(organization=self.org, stripe_payment_intent_id="pi_test123").first()

        self.assertIsNotNone(transaction, "Credit transaction should be created")
        self.assertEqual(transaction.centicredits_delta, 10000, "Transaction should add 100 credits (10000 centicredits)")
        self.assertEqual(transaction.centicredits_before, initial_credits, "Before credits should match initial balance")
        self.assertEqual(transaction.centicredits_after, initial_credits + 10000, "After credits should be initial + 10000")

        # Check we got redirected to billing page
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("bots:project-billing", kwargs={"object_id": self.project.object_id}))

    @patch("stripe.checkout.Session.retrieve")
    def test_checkout_success_error_handling(self, mock_retrieve):
        # Test missing session ID
        response = self.client.get(reverse("bots:checkout-success", kwargs={"object_id": self.project.object_id}))
        self.assertEqual(response.status_code, 400)
        mock_retrieve.assert_not_called()

        # Test Stripe API error
        mock_retrieve.side_effect = stripe.error.StripeError("Test Stripe error")
        response = self.client.get(reverse("bots:checkout-success", kwargs={"object_id": self.project.object_id}), {"session_id": "cs_test123"})
        self.assertEqual(response.status_code, 400)

    def test_process_checkout_session_completed(self):
        # Test the actual credit processing function
        initial_credits = self.org.centicredits

        # Create a mock Stripe session
        checkout_session = MagicMock()
        checkout_session.metadata = {"organization_id": str(self.org.id), "user_id": str(self.user.id), "credit_amount": "100"}
        checkout_session.payment_intent = f"pi_test_{uuid4()}"
        checkout_session.amount_total = 5000  # $50.00 in cents

        # Process the session
        process_checkout_session_completed(checkout_session)

        # Refresh org from database
        self.org.refresh_from_db()

        # Check credits were added (100 credits = 10000 centicredits)
        self.assertEqual(self.org.centicredits, initial_credits + 10000)

        # Check transaction was created
        transaction = CreditTransaction.objects.filter(organization=self.org, stripe_payment_intent_id=checkout_session.payment_intent).first()

        self.assertIsNotNone(transaction)
        self.assertEqual(transaction.centicredits_delta, 10000)
        self.assertEqual(transaction.centicredits_before, initial_credits)
        self.assertEqual(transaction.centicredits_after, initial_credits + 10000)

    def test_process_checkout_session_idempotence(self):
        # Test that processing the same session twice doesn't double-credit
        # Create a test payment intent ID
        payment_intent_id = f"pi_test_{uuid4()}"

        # Create a mock Stripe session
        checkout_session = MagicMock()
        checkout_session.metadata = {"organization_id": str(self.org.id), "user_id": str(self.user.id), "credit_amount": "100"}
        checkout_session.payment_intent = payment_intent_id
        checkout_session.amount_total = 5000  # $50.00 in cents

        # Process the session
        process_checkout_session_completed(checkout_session)
        self.org.refresh_from_db()
        initial_credits_after_first_process = self.org.centicredits
        initial_transaction_count = CreditTransaction.objects.count()

        # Process the same session again
        process_checkout_session_completed(checkout_session)

        # Refresh org and check credits haven't changed
        self.org.refresh_from_db()
        self.assertEqual(self.org.centicredits, initial_credits_after_first_process)

        # Check no new transaction was created
        self.assertEqual(CreditTransaction.objects.count(), initial_transaction_count)

    @patch("stripe.Webhook.construct_event")
    def test_stripe_webhook(self, mock_construct_event):
        # Create a webhook client without CSRF protection
        webhook_client = Client(enforce_csrf_checks=False)

        # Create a proper MagicMock object instead of a dictionary
        mock_session = MagicMock()
        mock_session.id = "cs_test_webhook"
        mock_session.payment_intent = "pi_test_webhook"
        mock_session.metadata = {"organization_id": str(self.org.id), "user_id": str(self.user.id), "credit_amount": "100"}
        mock_session.amount_total = 5000  # $50.00 in cents

        # Mock the Stripe event
        mock_event = {"type": "checkout.session.completed", "data": {"object": mock_session}}

        mock_construct_event.return_value = mock_event

        # Record initial credit balance
        initial_credits = self.org.centicredits

        # Test the webhook endpoint
        response = webhook_client.post(
            reverse("external-webhook-stripe"),
            data=json.dumps({"type": "checkout.session.completed"}),  # Actual content not important due to mocking
            content_type="application/json",
            HTTP_STRIPE_SIGNATURE="test_signature",
        )

        # Check that the webhook processed successfully
        self.assertEqual(response.status_code, 200)
        mock_construct_event.assert_called_once()

        # Check that a credit transaction was created with the correct values
        self.org.refresh_from_db()
        transaction = CreditTransaction.objects.filter(organization=self.org, stripe_payment_intent_id="pi_test_webhook").first()

        self.assertIsNotNone(transaction, "Credit transaction should be created")
        self.assertEqual(transaction.centicredits_delta, 10000, "Transaction should add 100 credits (10000 centicredits)")
        self.assertEqual(transaction.centicredits_before, initial_credits, "Before credits should match initial balance")
        self.assertEqual(transaction.centicredits_after, initial_credits + 10000, "After credits should be initial + 10000")

    @patch("stripe.Webhook.construct_event")
    def test_stripe_webhook_error_handling(self, mock_construct_event):
        webhook_client = Client(enforce_csrf_checks=False)

        # Test missing signature header
        response = webhook_client.post(reverse("external-webhook-stripe"), data=json.dumps({"type": "test"}), content_type="application/json")
        self.assertEqual(response.status_code, 400)
        mock_construct_event.assert_not_called()

        # Test invalid signature
        mock_construct_event.side_effect = stripe.error.SignatureVerificationError("Invalid signature", "sig")
        response = webhook_client.post(reverse("external-webhook-stripe"), data=json.dumps({"type": "test"}), content_type="application/json", HTTP_STRIPE_SIGNATURE="invalid_signature")
        self.assertEqual(response.status_code, 400)

        # Test invalid payload
        mock_construct_event.side_effect = ValueError("Invalid payload")
        response = webhook_client.post(reverse("external-webhook-stripe"), data="invalid json", content_type="application/json", HTTP_STRIPE_SIGNATURE="test_signature")
        self.assertEqual(response.status_code, 400)
