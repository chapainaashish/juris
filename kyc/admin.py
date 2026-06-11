from django.contrib import admin
from django.utils.html import format_html

from .models import KYCVerification


@admin.register(KYCVerification)
class KYCVerificationAdmin(admin.ModelAdmin):
    list_display = [
        "lawyer_name",
        "status_badge",
        "created_at",
        "stripe_link",
    ]
    list_filter = ["status", "created_at"]
    search_fields = [
        "lawyer_profile__vendor_profile__business_name",
    ]
    readonly_fields = [
        "stripe_verification_session_id",
        "status",
        "created_at",
        "updated_at",
    ]

    def lawyer_name(self, obj):
        if obj.lawyer_profile and obj.lawyer_profile.vendor_profile:
            return obj.lawyer_profile.vendor_profile.business_name
        return "N/A"

    lawyer_name.short_description = "Lawyer"

    def status_badge(self, obj):
        colors = {
            "verified": "#28a745",
            "processing": "#ffc107",
            "requires_input": "#007bff",
            "canceled": "#dc3545",
        }
        color = colors.get(obj.status, "#6c757d")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 8px; '
            'border-radius: 4px; font-size: 12px;">{}</span>',
            color,
            obj.status.title(),
        )

    status_badge.short_description = "Status"

    def stripe_link(self, obj):
        if obj.stripe_verification_session_id:
            url = f"https://dashboard.stripe.com/test/identity/verification-sessions/{obj.stripe_verification_session_id}"
            return format_html('<a href="{}" target="_blank">View in Stripe</a>', url)
        return "-"

    stripe_link.short_description = "Stripe"
