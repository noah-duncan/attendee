# Register your models here.

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.http import HttpResponseRedirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import Organization, User


class UserInline(admin.TabularInline):
    model = User
    extra = 0
    fields = ("email", "first_name", "last_name", "is_active", "is_staff")
    readonly_fields = ("email", "first_name", "last_name", "is_active", "is_staff")
    can_delete = False


class CreditTransactionForm(forms.Form):
    amount = forms.DecimalField(label="Credit Amount", max_digits=10, decimal_places=2, help_text="Positive values add credits, negative values subtract credits")
    description = forms.CharField(label="Description", max_length=255, required=True, widget=forms.Textarea(attrs={"rows": 3}))


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "display_credits", "is_webhooks_enabled", "created_at", "updated_at")
    list_filter = ("is_webhooks_enabled",)
    search_fields = ("name",)
    readonly_fields = ("name", "centicredits", "is_webhooks_enabled", "created_at", "updated_at", "version", "add_credit_transaction_button")
    inlines = [UserInline]

    def display_credits(self, obj):
        return f"{obj.credits():.2f}"

    display_credits.short_description = "Credits"

    def add_credit_transaction_button(self, obj):
        url = reverse("admin:add-credit-transaction", args=[obj.pk])
        return format_html('<a class="button" href="{}">Add Credit Transaction</a>', url)

    add_credit_transaction_button.short_description = "Add Credits"

    fieldsets = (
        ("Organization Information", {"fields": ("name", "centicredits", "is_webhooks_enabled", "add_credit_transaction_button")}),
        ("Metadata", {"fields": ("created_at", "updated_at", "version")}),
    )

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<int:org_id>/add-credit-transaction/",
                self.admin_site.admin_view(self.add_credit_transaction_view),
                name="add-credit-transaction",
            ),
        ]
        return custom_urls + urls

    def add_credit_transaction_view(self, request, org_id):
        org = Organization.objects.get(pk=org_id)

        if request.method == "POST":
            form = CreditTransactionForm(request.POST)
            if form.is_valid():
                amount = form.cleaned_data["amount"]
                description = form.cleaned_data["description"]

                # Convert decimal amount to centicredits (integer)
                centicredits = int(amount * 100)

                # Import here to avoid circular import
                from bots.models import CreditTransactionManager

                # Create the transaction
                CreditTransactionManager.create_transaction(organization=org, centicredits_delta=centicredits, description=description)

                self.message_user(request, f"Successfully added {amount} credits to {org.name}")
                return HttpResponseRedirect(reverse("admin:accounts_organization_change", args=[org_id]))
        else:
            form = CreditTransactionForm()

        context = {
            "title": f"Add Credit Transaction for {org.name}",
            "form": form,
            "opts": self.model._meta,
            "original": org,
        }
        return TemplateResponse(request, "admin/add_credit_transaction.html", context)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # Allow viewing but fields will be read-only

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ("email", "first_name", "last_name", "organization", "is_staff")
    list_filter = ("is_staff", "is_superuser", "is_active", "organization")
    search_fields = ("email", "first_name", "last_name")
    ordering = ("email",)
    readonly_fields = ("email", "first_name", "last_name", "is_active", "is_staff", "is_superuser", "groups", "user_permissions", "organization", "last_login", "date_joined")

    fieldsets = (
        (None, {"fields": ("email",)}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Permissions", {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")}),
        ("Organization", {"fields": ("organization",)}),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )

    # Since all fields are read-only, we don't need add_fieldsets
    add_fieldsets = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False  # Allow viewing but fields will be read-only

    def has_delete_permission(self, request, obj=None):
        return False
