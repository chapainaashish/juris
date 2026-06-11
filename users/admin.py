from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import PasswordResetToken
from .redis_otp_service import RedisOTPService

User = get_user_model()


class UserAdmin(BaseUserAdmin):
    # List view configuration
    list_display = (
        "email",
        "username",
        "first_name",
        "last_name",
        "phone_number",
        "is_staff",
        "is_active",
        "email_verified_badge",
        "two_fa_badge",
        "otp_status_badge",
        "date_joined",
    )

    list_filter = (
        "is_staff",
        "is_superuser",
        "is_active",
        "is_email_verified",
        "is_2fa_enabled",
        "date_joined",
        "groups",
    )

    search_fields = ("username", "first_name", "last_name", "email", "phone_number")
    ordering = ("-date_joined",)

    # Detail view configuration - Updated for Redis system
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        (
            _("Personal info"),
            {"fields": ("first_name", "last_name", "email", "phone_number")},
        ),
        (
            _("Verification & Security"),
            {
                "fields": (
                    "is_email_verified",
                    "email_verification_valid_until",
                    "is_2fa_enabled",
                    "has_initiate_login",
                )
            },
        ),
        (
            _("Security Tracking"),
            {
                "fields": ("password_attempt",),
                "classes": ("collapse",),  # Collapsible section
            },
        ),
        (
            _("Redis OTP Status"),
            {
                "fields": ("redis_otp_info",),
                "classes": ("collapse",),
            },
        ),
        (
            _("Permissions"),
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                ),
            },
        ),
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    # Add form configuration (when creating new users)
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": (
                    "username",
                    "email",
                    "phone_number",
                    "password1",
                    "password2",
                ),
            },
        ),
        (_("Personal info"), {"fields": ("first_name", "last_name")}),
        (_("Verification"), {"fields": ("is_email_verified",)}),
    )

    # Read-only fields for security
    readonly_fields = (
        "date_joined",
        "last_login",
        "password_attempt",
        "email_verification_valid_until",
        "redis_otp_info",
    )

    # Custom display methods
    def email_verified_badge(self, obj):
        if obj.is_email_verified:
            return format_html(
                '<span style="background-color: #28a745; color: white; padding: 4px 8px; '
                'border-radius: 4px; font-size: 12px;">✓ Verified</span>'
            )
        else:
            return format_html(
                '<span style="background-color: #dc3545; color: white; padding: 4px 8px; '
                'border-radius: 4px; font-size: 12px;">✗ Not Verified</span>'
            )

    email_verified_badge.short_description = "Email Status"

    def two_fa_badge(self, obj):
        if obj.is_2fa_enabled:
            return format_html(
                '<span style="background-color: #007bff; color: white; padding: 4px 8px; '
                'border-radius: 4px; font-size: 12px;">🔒 Enabled</span>'
            )
        else:
            return format_html(
                '<span style="background-color: #6c757d; color: white; padding: 4px 8px; '
                'border-radius: 4px; font-size: 12px;">🔓 Disabled</span>'
            )

    two_fa_badge.short_description = "2FA Status"

    def otp_status_badge(self, obj):
        """Show active OTP status from Redis"""
        try:
            otp_status = RedisOTPService.get_user_otp_status(obj.id)

            active_otps = []
            if otp_status.get("sms_otp", {}).get("active"):
                active_otps.append("SMS")
            if otp_status.get("email_change", {}).get("active"):
                active_otps.append("Email")
            if otp_status.get("password_reset", {}).get("active"):
                active_otps.append("Reset")

            if active_otps:
                return format_html(
                    '<span style="background-color: #ffc107; color: black; padding: 4px 8px; '
                    'border-radius: 4px; font-size: 12px;">📱 {}</span>',
                    ", ".join(active_otps),
                )
            else:
                return format_html(
                    '<span style="background-color: #6c757d; color: white; padding: 4px 8px; '
                    'border-radius: 4px; font-size: 12px;">💤 None</span>'
                )
        except Exception:
            return format_html(
                '<span style="background-color: #dc3545; color: white; padding: 4px 8px; '
                'border-radius: 4px; font-size: 12px;">❌ Error</span>'
            )

    otp_status_badge.short_description = "Active OTPs"

    def redis_otp_info(self, obj):
        """Display detailed Redis OTP information"""
        try:
            otp_status = RedisOTPService.get_user_otp_status(obj.id)

            info_html = "<div style='font-family: monospace; font-size: 12px;'>"

            # SMS OTP Info
            sms_info = otp_status.get("sms_otp", {})
            info_html += f"<strong>SMS OTP:</strong><br>"
            info_html += (
                f"&nbsp;&nbsp;Active: {'Yes' if sms_info.get('active') else 'No'}<br>"
            )
            info_html += (
                f"&nbsp;&nbsp;Attempts Left: {sms_info.get('attempts_left', 'N/A')}<br>"
            )
            if sms_info.get("expires_at"):
                info_html += f"&nbsp;&nbsp;Expires: {sms_info.get('expires_at')}<br>"
            info_html += "<br>"

            # Email Change Info
            email_info = otp_status.get("email_change", {})
            info_html += f"<strong>Email Change:</strong><br>"
            info_html += (
                f"&nbsp;&nbsp;Active: {'Yes' if email_info.get('active') else 'No'}<br>"
            )
            if email_info.get("new_email"):
                info_html += f"&nbsp;&nbsp;New Email: {email_info.get('new_email')}<br>"
            if email_info.get("expires_at"):
                info_html += f"&nbsp;&nbsp;Expires: {email_info.get('expires_at')}<br>"
            info_html += "<br>"

            # Password Reset Info
            reset_info = otp_status.get("password_reset", {})
            info_html += f"<strong>Password Reset:</strong><br>"
            info_html += (
                f"&nbsp;&nbsp;Active: {'Yes' if reset_info.get('active') else 'No'}<br>"
            )
            if reset_info.get("expires_at"):
                info_html += f"&nbsp;&nbsp;Expires: {reset_info.get('expires_at')}<br>"

            info_html += "</div>"

            return format_html(info_html)

        except Exception as e:
            return format_html(
                '<span style="color: red;">Error loading OTP info: {}</span>', str(e)
            )

    redis_otp_info.short_description = "Redis OTP Details"

    # Add actions for OTP management
    actions = ["clear_user_otps", "reset_failed_login_attempts"]

    def clear_user_otps(self, request, queryset):
        """Admin action to clear all OTPs for selected users"""
        cleared_count = 0
        for user in queryset:
            try:
                # Clear all OTP types
                RedisOTPService._delete_otp_data(
                    user.id, RedisOTPService.SMS_OTP_PREFIX
                )
                RedisOTPService._delete_otp_data(
                    user.id, RedisOTPService.EMAIL_CHANGE_PREFIX
                )
                RedisOTPService._delete_otp_data(
                    user.id, RedisOTPService.PASSWORD_RESET_PREFIX
                )
                cleared_count += 1
            except Exception:
                pass

        self.message_user(request, f"Cleared OTPs for {cleared_count} user(s).")

    clear_user_otps.short_description = "Clear all OTPs for selected users"

    def reset_failed_login_attempts(self, request, queryset):
        """Admin action to reset failed login attempts"""
        reset_count = 0
        for user in queryset:
            user.password_attempt = 0
            user.save(update_fields=["password_attempt"])
            reset_count += 1

        self.message_user(
            request, f"Reset failed login attempts for {reset_count} user(s)."
        )

    reset_failed_login_attempts.short_description = "Reset failed login attempts"


# Register the custom User admin
admin.site.register(User, UserAdmin)


# Password Reset Token Admin (kept from original system)
@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "token_preview",
        "is_used",
        "is_valid_status",
        "created_at",
        "expires_at",
    )

    list_filter = ("is_used", "created_at", "expires_at")
    search_fields = ("user__email", "user__username")
    readonly_fields = ("token", "created_at")

    fieldsets = (
        (None, {"fields": ("user", "token", "is_used")}),
        (_("Timestamps"), {"fields": ("created_at", "expires_at")}),
    )

    def token_preview(self, obj):
        """Show a preview of the token for security"""
        if obj.token:
            return f"{obj.token[:8]}...{obj.token[-8:]}"
        return "No token"

    token_preview.short_description = "Token Preview"

    def is_valid_status(self, obj):
        if obj.is_valid():
            return format_html('<span style="color: green;">✓ Valid</span>')
        else:
            return format_html('<span style="color: red;">✗ Invalid/Expired</span>')

    is_valid_status.short_description = "Status"

    # Admin actions
    actions = ["mark_as_used", "cleanup_expired"]

    def mark_as_used(self, request, queryset):
        """Mark selected tokens as used"""
        updated = queryset.update(is_used=True)
        self.message_user(request, f"Marked {updated} token(s) as used.")

    mark_as_used.short_description = "Mark selected tokens as used"

    def cleanup_expired(self, request, queryset):
        """Delete expired tokens"""
        expired_tokens = queryset.filter(expires_at__lt=timezone.now())
        count = expired_tokens.count()
        expired_tokens.delete()

        self.message_user(request, f"Deleted {count} expired token(s).")

    cleanup_expired.short_description = "Delete expired tokens"


# Custom admin site configuration
admin.site.site_header = "User Management Admin"
admin.site.site_title = "User Admin"
admin.site.index_title = "Welcome to User Management"


# Add Redis OTP monitoring view (optional)
class RedisOTPMonitorAdmin(admin.ModelAdmin):
    """
    Virtual admin for monitoring Redis OTP status.
    This doesn't correspond to a model but provides useful info.
    """

    change_list_template = "admin/redis_otp_monitor.html"

    def changelist_view(self, request, extra_context=None):
        try:
            # Get Redis connection info
            from django_redis import get_redis_connection

            redis_client = get_redis_connection("default")

            # Get Redis info
            redis_info = redis_client.info()

            # Get OTP statistics
            otp_stats = {
                "sms_otp_keys": len(
                    redis_client.keys(f"{RedisOTPService.SMS_OTP_PREFIX}:*")
                ),
                "email_change_keys": len(
                    redis_client.keys(f"{RedisOTPService.EMAIL_CHANGE_PREFIX}:*")
                ),
                "password_reset_keys": len(
                    redis_client.keys(f"{RedisOTPService.PASSWORD_RESET_PREFIX}:*")
                ),
                "total_memory_used": redis_info.get("used_memory_human", "N/A"),
                "connected_clients": redis_info.get("connected_clients", "N/A"),
            }

            extra_context = extra_context or {}
            extra_context.update(
                {
                    "redis_info": redis_info,
                    "otp_stats": otp_stats,
                    "redis_available": True,
                }
            )

        except Exception as e:
            extra_context = extra_context or {}
            extra_context.update(
                {
                    "redis_available": False,
                    "redis_error": str(e),
                }
            )

        return super().changelist_view(request, extra_context)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
