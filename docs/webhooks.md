# Webhooks

Attendee provides a webhook system that allows you to receive real-time notifications about important events in your Attendee bots and meetings.

## Overview

Webhooks allow your application to receive notifications when events occur in Attendee. Instead of constantly polling Attendee's API for updates, webhooks deliver information to your application in real-time as events occur.

## Key Benefits

- **Real-time updates**: Get notified immediately when an event occurs
- **Reduced API calls**: No need to poll for status changes
- **Automation**: Trigger workflows based on Attendee events

## Enabling Webhooks

Webhooks feature is managed at the organization level. To use webhooks:

1. If you are using the hosted Attendee instance, contact the Attendee support team and they will enable it for you.
2. If you are self-hosting, you can enable it by setting the `is_webhooks_enabled` column to "true" in the `accounts_organization` table:

```bash
# Connect to the postgres database
docker compose -f dev.docker-compose.yaml exec postgres psql -U attendee_development_user -d attendee_development

# Run this SQL command once connected
UPDATE accounts_organization SET is_webhooks_enabled = 't';
```

Once webhooks are enabled for your organization, the webhook management UI will be accessible from your project sidebar.

## Creating a Webhook

To create a webhook:

1. Navigate to your project and click on the "Webhooks" section in the sidebar
2. Click "Create Webhook" 
3. Provide an HTTPS URL that will receive webhook events
4. Select the events you want to receive notifications for (we currently have one event type: `bot.state_change`)
5. Click "Create" to save your subscription

