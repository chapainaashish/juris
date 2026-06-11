from django.conf import settings
from django.db import models
from django.utils.timezone import now

from profiles.models import Category, VendorProfile


# SUBSCRIPTION
class SubscriptionPlan(models.Model):
    """Model representing different subscription plans based on vendor categories"""

    category = models.OneToOneField(
        Category, on_delete=models.CASCADE, related_name="subscription_plan"
    )
    name = models.CharField(max_length=100)
    description = models.TextField()
    price_monthly = models.DecimalField(max_digits=10, decimal_places=2)
    stripe_price_id = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.category.name}"


class Voucher(models.Model):
    PERCENTAGE = "percentage"
    FREE_PERIOD = "free_period"
    FIXED_AMOUNT = "fixed_amount"  # New

    DISCOUNT_TYPE_CHOICES = [
        (PERCENTAGE, "Percentage Discount"),
        (FREE_PERIOD, "Free Period"),  # kept but will be deprecated
        (FIXED_AMOUNT, "Fixed Amount Discount"),
    ]

    code = models.CharField(max_length=20, unique=True)
    discount_type = models.CharField(max_length=20, choices=DISCOUNT_TYPE_CHOICES)
    value = models.PositiveIntegerField(help_text="Percentage, USD amount, or months")
    usage_limit = models.PositiveIntegerField(default=1)
    used_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    # New
    stripe_coupon_id = models.CharField(max_length=100, blank=True, null=True)
    duration_months = models.PositiveIntegerField(
        null=True, blank=True, help_text="For repeating discounts"
    )
    restricted_to_email = models.EmailField(blank=True, null=True)

    def __str__(self):
        if self.discount_type == self.PERCENTAGE:
            return f"{self.code} - {self.value}% off"
        return f"{self.code} - {self.value} months free"

    @property
    def is_expired(self):
        return self.expires_at < now()

    @property
    def is_valid(self):
        return (
            self.is_active
            and not self.is_expired
            and self.used_count < self.usage_limit
        )


class VoucherUsage(models.Model):
    voucher = models.ForeignKey(Voucher, on_delete=models.CASCADE)
    subscription = models.ForeignKey("VendorSubscription", on_delete=models.CASCADE)
    applied_at = models.DateTimeField(auto_now_add=True)
    stripe_discount_id = models.CharField(max_length=100, blank=True)


class VendorSubscription(models.Model):
    """Model representing a vendor's subscription"""

    STATUS_CHOICES = [
        ("trialing", "Trialing"),
        ("active", "Active"),
        ("past_due", "Past Due"),
        ("canceled", "Canceled"),
        ("unpaid", "Unpaid"),
    ]

    vendor = models.OneToOneField(
        VendorProfile, on_delete=models.CASCADE, related_name="subscription"
    )
    plan = models.ForeignKey(SubscriptionPlan, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="trialing")
    stripe_customer_id = models.CharField(max_length=100, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=100, blank=True, null=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    canceled_at = models.DateTimeField(null=True, blank=True)
    voucher = models.ForeignKey(
        Voucher, on_delete=models.SET_NULL, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.vendor.business_name} - {self.status}"

    @property
    def is_active(self):
        return self.status in ["trialing", "active"]

    @property
    def days_until_trial_ends(self):
        if not self.trial_ends_at:
            return 0
        delta = self.trial_ends_at - now()
        return max(0, delta.days)

    @property
    def days_until_renewal(self):
        if not self.current_period_end:
            return 0
        delta = self.current_period_end - now()
        return max(0, delta.days)


class SubscriptionInvoice(models.Model):
    """Model for tracking subscription invoices"""

    subscription = models.ForeignKey(
        VendorSubscription, on_delete=models.CASCADE, related_name="invoices"
    )
    stripe_invoice_id = models.CharField(max_length=100)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2)
    invoice_pdf = models.URLField(max_length=255, null=True, blank=True)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    status = models.CharField(max_length=20)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Invoice {self.stripe_invoice_id} for {self.subscription.vendor.business_name}"


class PaymentMethod(models.Model):
    """Model for storing vendor payment method details"""

    vendor = models.ForeignKey(
        VendorProfile, on_delete=models.CASCADE, related_name="payment_methods"
    )
    stripe_payment_method_id = models.CharField(max_length=100)
    card_brand = models.CharField(max_length=20)
    last4 = models.CharField(max_length=4)
    exp_month = models.PositiveSmallIntegerField()
    exp_year = models.PositiveSmallIntegerField()
    is_default = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.vendor.business_name} - {self.card_brand} **** {self.last4}"


# NOTIFICATION
class Notification(models.Model):
    """Model for storing in-app notifications"""

    # Notification type constants
    TRIAL_ENDING = "trial_ending"
    FREE_PERIOD_ENDING = "free_period_ending"
    SUBSCRIPTION_RENEWING = "subscription_renewing"
    PAYMENT_FAILED = "payment_failed"
    SUBSCRIPTION_CANCELED = "subscription_canceled"
    SUBSCRIPTION_ACTIVATED = "subscription_activated"
    APPOINTMENT_STARTING = "appointment_starting"
    APPOINTMENT_REMINDER = "appointment_reminder"
    REFUND_APPROVED = "refund_approved"
    WITHDRAWAL_APPROVED = "withdrawal_approved"
    GENERAL = "general"

    TYPES = [
        # Subscription notifications
        (TRIAL_ENDING, "Trial Ending"),
        (FREE_PERIOD_ENDING, "Free Period Ending"),
        (SUBSCRIPTION_RENEWING, "Subscription Renewing"),
        (PAYMENT_FAILED, "Payment Failed"),
        (SUBSCRIPTION_CANCELED, "Subscription Canceled"),
        (SUBSCRIPTION_ACTIVATED, "Subscription Activated"),
        # Appointment notifications
        (APPOINTMENT_STARTING, "Appointment Starting"),
        (APPOINTMENT_REMINDER, "Appointment Reminder"),
        (REFUND_APPROVED, "Refund Approved"),
        # Wallet notifications
        (WITHDRAWAL_APPROVED, "Withdrawal Approved"),
        # General
        (GENERAL, "General Notification"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications"
    )
    type = models.CharField(max_length=30, choices=TYPES)
    message = models.TextField()
    read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "read", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.type} notification for {self.user.email}"
