from rest_framework import serializers

from .models import (
    Notification,
    PaymentMethod,
    SubscriptionInvoice,
    SubscriptionPlan,
    VendorSubscription,
    Voucher,
)


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = SubscriptionPlan
        fields = [
            "id",
            "name",
            "description",
            "price_monthly",
            "category",
            "category_name",
            "is_active",
        ]
        read_only_fields = ["id", "category_name"]


class VoucherSerializer(serializers.ModelSerializer):
    class Meta:
        model = Voucher
        fields = [
            "id",
            "code",
            "discount_type",
            "value",
            "usage_limit",
            "used_count",
            "expires_at",
            "is_active",
        ]
        read_only_fields = ["id", "used_count"]


class VoucherValidateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)


class VendorSubscriptionSerializer(serializers.ModelSerializer):
    vendor_name = serializers.CharField(source="vendor.business_name", read_only=True)
    plan_name = serializers.CharField(source="plan.name", read_only=True)
    category_name = serializers.CharField(source="vendor.category.name", read_only=True)
    days_left = serializers.SerializerMethodField()
    active = serializers.SerializerMethodField()
    voucher = VoucherSerializer(read_only=True) 

    class Meta:
        model = VendorSubscription
        fields = [
            "id",
            "vendor",
            "vendor_name",
            "plan",
            "plan_name",
            "status",
            "trial_ends_at",
            "current_period_end",
            "canceled_at",
            "days_left",
            "active",
            "category_name",
            'voucher',
        ]
        read_only_fields = ["id", "vendor_name", "plan_name", "days_left", "active"]

    def get_days_left(self, obj):
        if obj.status == "trialing":
            return obj.days_until_trial_ends
        elif obj.status == "active":
            return obj.days_until_renewal
        return 0

    def get_active(self, obj):
        return obj.is_active


class SubscriptionActivateSerializer(serializers.Serializer):
    payment_method_id = serializers.CharField(max_length=100)
    voucher_code = serializers.CharField(
        max_length=20, required=False, allow_blank=True
    )


class PaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PaymentMethod
        fields = [
            "id",
            "card_brand",
            "last4",
            "exp_month",
            "exp_year",
            "is_default",
            "created_at",
        ]
        read_only_fields = [
            "id",
            "card_brand",
            "last4",
            "exp_month",
            "exp_year",
            "created_at",
        ]


class SubscriptionInvoiceSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubscriptionInvoice
        fields = [
            "id",
            "subscription",
            "stripe_invoice_id",
            "amount_paid",
            "invoice_pdf",
            "period_start",
            "period_end",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "type", "message", "read", "created_at"]
        read_only_fields = ["id", "type", "message", "created_at"]
