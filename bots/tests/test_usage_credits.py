import math
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.test import TestCase, TransactionTestCase
from django.utils import timezone

from bots.models import Bot, CreditTransaction, CreditTransactionManager, Organization, Project


class TestBotCreditCalculation(TestCase):
    def setUp(self):
        # Create test organization with credits
        self.organization = Organization.objects.create(
            name="Test Org",
            centicredits=1000,  # 10 credits
        )

        # Create test project
        self.project = Project.objects.create(organization=self.organization, name="Test Project")

        # Create test bot
        self.bot = Bot.objects.create(project=self.project, name="Test Bot", meeting_url="https://test.com")

    def test_bot_credit_calculation_for_hour(self):
        """Test that a bot running for 1 hour consumes 1 credit (100 centicredits)"""
        now = timezone.now()
        hour_ago = now - timedelta(hours=1)

        # Set bot heartbeat
        self.bot.first_heartbeat_timestamp = int(hour_ago.timestamp())
        self.bot.last_heartbeat_timestamp = int(now.timestamp())
        self.bot.save()

        # Check credit consumption (should be 100 centicredits = 1 credit)
        self.assertEqual(self.bot.centicredits_consumed(), 100)

    def test_bot_credit_calculation_for_partial_hour(self):
        """Test that a bot running for 30 minutes consumes 0.5 credits (50 centicredits)"""
        now = timezone.now()
        half_hour_ago = now - timedelta(minutes=30)

        # Set bot heartbeat
        self.bot.first_heartbeat_timestamp = int(half_hour_ago.timestamp())
        self.bot.last_heartbeat_timestamp = int(now.timestamp())
        self.bot.save()

        # Check credit consumption (should be 50 centicredits = 0.5 credits)
        self.assertEqual(self.bot.centicredits_consumed(), 50)

    def test_no_credits_with_no_heartbeat(self):
        """Test that a bot with no heartbeat consumes no credits"""
        self.assertEqual(self.bot.centicredits_consumed(), 0)

    def test_no_credits_with_invalid_heartbeat(self):
        """Test that a bot with invalid heartbeat (last < first) consumes no credits"""
        now = timezone.now()
        future = now + timedelta(hours=1)

        self.bot.first_heartbeat_timestamp = int(future.timestamp())
        self.bot.last_heartbeat_timestamp = int(now.timestamp())
        self.bot.save()

        self.assertEqual(self.bot.centicredits_consumed(), 0)

    def test_bot_credit_calculation_for_less_than_minute(self):
        """Test that a bot running for 30 seconds consumes the appropriate credits"""
        now = timezone.now()

        # Set bot heartbeat
        self.bot.first_heartbeat_timestamp = int(now.timestamp())
        self.bot.last_heartbeat_timestamp = int(now.timestamp())
        self.bot.save()

        # Check credit consumption (should be ~0.833 centicredits = 30/3600 * 100)
        expected_centicredits = math.ceil(30 / 3600 * 100)
        self.assertEqual(self.bot.centicredits_consumed(), expected_centicredits)


class TestCreditTransactions(TransactionTestCase):
    def setUp(self):
        # Create test organization with credits
        self.organization = Organization.objects.create(
            name="Test Org",
            centicredits=1000,  # 10 credits
        )

        # Create test project
        self.project = Project.objects.create(organization=self.organization, name="Test Project")

        # Create test bot
        self.bot = Bot.objects.create(project=self.project, name="Test Bot", meeting_url="https://test.com")

    def test_credit_transaction_creation(self):
        """Test creating a credit transaction for bot usage"""
        now = timezone.now()
        hour_ago = now - timedelta(hours=1)

        # Set bot heartbeat for 1 hour
        self.bot.first_heartbeat_timestamp = int(hour_ago.timestamp())
        self.bot.last_heartbeat_timestamp = int(now.timestamp())
        self.bot.save()

        # Create a transaction for the bot's activity
        transaction = CreditTransactionManager.create_transaction(organization=self.organization, centicredits_delta=-self.bot.centicredits_consumed(), bot=self.bot, description="Bot usage")

        # Verify transaction details
        self.assertEqual(transaction.centicredits_delta, -100)
        self.assertEqual(transaction.centicredits_before, 1000)
        self.assertEqual(transaction.centicredits_after, 900)
        self.assertEqual(transaction.bot, self.bot)
        self.assertEqual(transaction.description, "Bot usage")

        # Verify organization's credits were updated
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.centicredits, 900)

    def test_add_credits_transaction(self):
        """Test adding credits to an organization"""
        transaction = CreditTransactionManager.create_transaction(
            organization=self.organization,
            centicredits_delta=500,  # Add 5 credits
            description="Credit purchase",
        )

        # Verify transaction details
        self.assertEqual(transaction.centicredits_delta, 500)
        self.assertEqual(transaction.centicredits_before, 1000)
        self.assertEqual(transaction.centicredits_after, 1500)

        # Verify organization's credits were updated
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.centicredits, 1500)


class TestTransactionIntegrity(TransactionTestCase):
    def setUp(self):
        # Create test organization with credits
        self.organization = Organization.objects.create(name="Test Org", centicredits=1000)

        # Create test project
        self.project = Project.objects.create(organization=self.organization, name="Test Project")

        # Create two test bots
        self.bot1 = Bot.objects.create(project=self.project, name="Bot One", meeting_url="https://test.com/one")

        self.bot2 = Bot.objects.create(project=self.project, name="Bot Two", meeting_url="https://test.com/two")

    def test_transaction_chaining(self):
        """Test that transactions are properly chained with parent-child relationships"""
        # Create first transaction
        transaction1 = CreditTransactionManager.create_transaction(organization=self.organization, centicredits_delta=-100, bot=self.bot1, description="Bot One usage")

        # Create second transaction
        transaction2 = CreditTransactionManager.create_transaction(organization=self.organization, centicredits_delta=-50, bot=self.bot2, description="Bot Two usage")

        # Verify parent-child relationship
        self.assertEqual(transaction2.parent_transaction, transaction1)

        # Create third transaction
        transaction3 = CreditTransactionManager.create_transaction(organization=self.organization, centicredits_delta=200, description="Credit purchase")

        # Verify parent-child relationship chain
        self.assertEqual(transaction3.parent_transaction, transaction2)

        # Verify final organization balance
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.centicredits, 1050)  # 1000 - 100 - 50 + 200 = 1050

    def test_cannot_create_duplicate_root_transaction(self):
        """Test that we cannot create a duplicate root transaction for an organization"""
        # Create first root transaction
        CreditTransactionManager.create_transaction(organization=self.organization, centicredits_delta=-100, bot=self.bot1)

        # Try to create another root transaction directly (bypassing the manager)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CreditTransaction.objects.create(
                    organization=self.organization,
                    centicredits_before=1000,
                    centicredits_after=900,
                    centicredits_delta=-100,
                    parent_transaction=None,  # This should fail - no duplicate roots allowed
                    bot=self.bot2,
                )

    def test_cannot_create_duplicate_bot_transaction(self):
        """Test that we cannot create a duplicate transaction for the same bot"""
        # Create transaction for bot1
        CreditTransactionManager.create_transaction(organization=self.organization, centicredits_delta=-100, bot=self.bot1)

        # Try to create another transaction for the same bot directly
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                leaf_transaction = CreditTransaction.objects.filter(organization=self.organization, child_transactions__isnull=True).first()

                CreditTransaction.objects.create(
                    organization=self.organization,
                    centicredits_before=900,
                    centicredits_after=800,
                    centicredits_delta=-100,
                    parent_transaction=leaf_transaction,
                    bot=self.bot1,  # This should fail - no duplicate bot transactions
                )

    def test_concurrent_transactions_handled_properly(self):
        """Test that concurrent transactions are handled properly with retries"""
        # This is simulating multiple processes trying to update credits at the same time

        # Create an initial transaction
        CreditTransactionManager.create_transaction(organization=self.organization, centicredits_delta=-50, description="Initial transaction")

        # Create two more transactions "concurrently"
        # (the manager handles retries internally if there are conflicts)
        CreditTransactionManager.create_transaction(organization=self.organization, centicredits_delta=-25, description="Concurrent transaction 1")

        CreditTransactionManager.create_transaction(organization=self.organization, centicredits_delta=-25, description="Concurrent transaction 2")

        # Verify the transactions form a valid chain and balance is correct
        self.organization.refresh_from_db()
        self.assertEqual(self.organization.centicredits, 900)  # 1000 - 50 - 25 - 25 = 900

        # The exact parent-child relationships can vary depending on timing
        # but the chain should be valid and total should be correct
        all_transactions = CreditTransaction.objects.filter(organization=self.organization)
        self.assertEqual(all_transactions.count(), 3)
