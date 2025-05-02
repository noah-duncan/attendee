from django.test import TestCase

from bots.models import Bot, Organization, Project


class BotConfigurationTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(name="Test Organization")
        self.project = Project.objects.create(name="Test Project", organization=self.organization)

    def test_automatic_leave_configuration_default_values(self):
        """
        Ensure that the default values are being set.
        """
        bot = Bot.objects.create(project=self.project, meeting_url="https://example.com/meeting", settings={})

        # Get the automatic leave configuration
        config = bot.automatic_leave_configuration()

        # Assert default values are used
        self.assertEqual(config.silence_threshold_seconds, 600)
        self.assertEqual(config.only_participant_in_meeting_threshold_seconds, 60)
        self.assertEqual(config.wait_for_host_to_start_meeting_timeout_seconds, 600)
        self.assertEqual(config.silence_activate_after_seconds, 1200)

    def test_automatic_leave_configuration_custom_values(self):
        """
        Ensure that we can set custom values and that they are being used.
        """
        bot = Bot.objects.create(project=self.project, meeting_url="https://example.com/meeting", settings={"silence_threshold_seconds": 300, "only_participant_in_meeting_threshold_seconds": 30, "wait_for_host_to_start_meeting_timeout_seconds": 900, "silence_activate_after_seconds": 600})

        # Get the automatic leave configuration
        config = bot.automatic_leave_configuration()

        # Assert custom values are used
        self.assertEqual(config.silence_threshold_seconds, 300)
        self.assertEqual(config.only_participant_in_meeting_threshold_seconds, 30)
        self.assertEqual(config.wait_for_host_to_start_meeting_timeout_seconds, 900)
        self.assertEqual(config.silence_activate_after_seconds, 600)
