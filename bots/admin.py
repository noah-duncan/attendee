import os

from django.contrib import admin
from django.utils.html import format_html

from .models import Bot, BotEvent, Utterance, WebhookDeliveryAttempt, WebhookSubscription


# Create an inline for BotEvent to show on the Bot admin page
class BotEventInline(admin.TabularInline):
    model = BotEvent
    extra = 0
    readonly_fields = ("created_at", "event_type", "event_sub_type", "old_state", "new_state", "metadata")
    can_delete = False
    max_num = 0  # Don't allow adding new events through admin
    ordering = ("created_at",)  # Show most recent events first

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Bot)
class BotAdmin(admin.ModelAdmin):
    actions = None
    list_display = ("object_id", "name", "project", "state", "created_at", "updated_at", "view_logs_link")
    list_filter = ("state", "project")
    search_fields = ("object_id",)
    readonly_fields = ("object_id", "created_at", "updated_at", "state", "view_logs_link")
    inlines = [BotEventInline]  # Add the inline to the admin

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return True

    def view_logs_link(self, obj):
        pod_name = obj.k8s_pod_name()
        link_formatting_str = os.getenv("CLOUD_LOGS_LINK_FORMATTING_STR")
        if not link_formatting_str:
            return None
        try:
            url = link_formatting_str.format(pod_name=pod_name)
            return format_html('<a href="{}" target="_blank">View Logs</a>', url)
        except Exception:
            return None

    view_logs_link.short_description = "Cloud Logs"

    # Optional: if you want to organize the fields in the detail view
    fieldsets = (
        ("Basic Information", {"fields": ("object_id", "name", "project")}),
        ("Meeting Details", {"fields": ("meeting_url", "meeting_uuid")}),
        ("Status", {"fields": ("state", "view_logs_link")}),
        ("Settings", {"fields": ("settings",)}),
        ("Metadata", {"fields": ("created_at", "updated_at", "version")}),
    )

@admin.register(Utterance)
class UtteranceAdmin(admin.ModelAdmin):
    actions = None
    list_display = ("id", "participant_id", "recording_id", "audio_format", "source", "duration_ms", "created_at", "updated_at")
    list_filter = ("source", "recording_id")

@admin.register(WebhookDeliveryAttempt)
class WebhookDeliveryAdmin(admin.ModelAdmin):
    actions = None

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.filter(succeeded_at__isnull=False)
    
    def webhook_url(self, obj):
        return obj.webhook_subscription.url
    webhook_url.short_description = "Webhook URL"

    def duration(self, obj):
        if obj.succeeded_at and obj.last_attempt_at:
            duration = obj.succeeded_at - obj.last_attempt_at
            return f"{duration.total_seconds():.2f}s"
        return "-"
    duration.short_description = "Duration"

    def event_type(self, obj):
        if obj.payload and isinstance(obj.payload, dict):
            return obj.payload.get('event_type', '-')
        return '-'
    event_type.short_description = "Bot Event"

    def response_statuses(self, obj):
        if not obj.response_body_list:
            return '-'
        status_codes = []
        for response in obj.response_body_list:
            if isinstance(response, dict):
                status = response.get('status_code')
                if status is not None:
                    status_codes.append(str(status))
        return ', '.join(status_codes) if status_codes else '-'
    response_statuses.short_description = "Response Status Codes"

    def changelist_view(self, request, extra_context=None):
        # Get successful deliveries in last 30 days
        from django.utils import timezone
        from django.db.models import Avg, F, ExpressionWrapper, fields
        from django.db.models.functions import TruncDay

        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        
        # Calculate average duration per day
        duration_data = (
            self.get_queryset(request)
            .filter(created_at__gte=thirty_days_ago)
            .annotate(
                date=TruncDay('created_at'),
                duration=ExpressionWrapper(
                    F('succeeded_at') - F('created_at'),
                    output_field=fields.DurationField()
                )
            )
            .values('date')
            .annotate(avg_duration=Avg('duration'))
            .order_by('date')
        )

        # Format data for chart
        dates = [d['date'].strftime('%Y-%m-%d') for d in duration_data]
        durations = [d['avg_duration'].total_seconds() for d in duration_data]

        extra_context = extra_context or {}
        extra_context['duration_chart_data'] = {
            'labels': dates,
            'data': durations
        }

        return super().changelist_view(request, extra_context)

    list_display = ("idempotency_key", "webhook_url", "status", "created_at", "last_attempt_at", "succeeded_at", "event_type", "response_statuses", "attempt_count", "duration",)
    list_filter = ("status",)
    # change_list_template = 'admin/webhook_delivery_changelist.html'
