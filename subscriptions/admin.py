from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django.utils.timezone import now

from .models import (
    Notification,
    PaymentMethod,
    SubscriptionInvoice,
    SubscriptionPlan,
    VendorSubscription,
    Voucher,
    VoucherUsage,
)


@admin.register(SubscriptionPlan)
class SubscriptionPlanAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "price_monthly", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("name", "category__name")


@admin.register(Voucher)
class VoucherAdmin(admin.ModelAdmin):
    list_display = (
        "code",
        "discount_type",
        "value",
        "duration_months",
        "stripe_coupon_id",
        "usage_count",
        "is_active",
        "expires_status",
    )
    list_filter = ("discount_type", "is_active")
    search_fields = ("code",)
    readonly_fields = ("used_count", "stripe_coupon_id")

    actions = ['create_stripe_coupon']
    
    def create_stripe_coupon(self, request, queryset):
        from .stripe_utils import get_or_create_stripe_coupon
        for voucher in queryset:
            try:
                coupon = get_or_create_stripe_coupon(voucher)
                self.message_user(request, f"Created/Retrieved Stripe coupon {coupon.id} for {voucher.code}")
            except Exception as e:
                self.message_user(request, f"Error for {voucher.code}: {str(e)}", level='ERROR')
    
    create_stripe_coupon.short_description = "Create/Sync Stripe Coupon"

    def usage_count(self, obj):
        return f"{obj.used_count}/{obj.usage_limit}"

    def expires_status(self, obj):
        if obj.expires_at < now():
            return format_html('<span style="color: red;">Expired</span>')
        return obj.expires_at.strftime("%Y-%m-%d")

    expires_status.short_description = "Expires"

@admin.register(VoucherUsage) 
class VoucherUsageAdmin(admin.ModelAdmin):
    list_display = ['voucher', 'subscription', 'applied_at', 'stripe_discount_id']
    list_filter = ['applied_at']
    search_fields = ['voucher__code', 'subscription__vendor__business_name']
    readonly_fields = ['applied_at']


@admin.register(VendorSubscription)
class VendorSubscriptionAdmin(admin.ModelAdmin):
    list_display = (
        "vendor_name",
        "category",
        "status",
        "trial_status",
        "current_period",
        "has_payment_method",
    )
    list_filter = ("status", "vendor__category")
    search_fields = ("vendor__business_name", "vendor__user__email")
    readonly_fields = ("created_at", "updated_at")

    def vendor_name(self, obj):
        return obj.vendor.business_name

    def category(self, obj):
        return obj.vendor.category.name

    def trial_status(self, obj):
        if not obj.trial_ends_at:
            return "No trial"

        if obj.trial_ends_at < now():
            return "Ended"

        days_left = (obj.trial_ends_at - now()).days
        return f"{days_left} days left"

    def current_period(self, obj):
        if not obj.current_period_end:
            return "-"
        return obj.current_period_end.strftime("%Y-%m-%d")

    def has_payment_method(self, obj):
        return PaymentMethod.objects.filter(vendor=obj.vendor).exists()

    has_payment_method.boolean = True


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ("vendor_name", "card_display", "is_default", "created_at")
    list_filter = ("is_default", "card_brand")
    search_fields = ("vendor__business_name", "last4")

    def vendor_name(self, obj):
        return obj.vendor.business_name

    def card_display(self, obj):
        return (
            f"{obj.card_brand} **** {obj.last4} (exp: {obj.exp_month}/{obj.exp_year})"
        )


@admin.register(SubscriptionInvoice)
class SubscriptionInvoiceAdmin(admin.ModelAdmin):
    list_display = (
        "vendor_name",
        "amount_paid",
        "status",
        "period",
        "created_at",
        "download_link",
    )
    list_filter = ("status",)
    search_fields = ("subscription__vendor__business_name", "stripe_invoice_id")

    def vendor_name(self, obj):
        return obj.subscription.vendor.business_name

    def period(self, obj):
        return f"{obj.period_start.strftime('%Y-%m-%d')} to {obj.period_end.strftime('%Y-%m-%d')}"

    def download_link(self, obj):
        if obj.invoice_pdf:
            return format_html('<a href="{}" target="_blank">PDF</a>', obj.invoice_pdf)
        return "-"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user_email", "type", "read_status", "created_at")
    list_filter = ("type", "read")
    search_fields = ("user__email", "message")

    def user_email(self, obj):
        return obj.user.email

    def read_status(self, obj):
        return "Read" if obj.read else "Unread"
