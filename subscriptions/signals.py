from datetime import timedelta

from django.conf import settings
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver
from django.utils.timezone import now

from profiles.models import VendorProfile

from .models import PaymentMethod, VendorSubscription
from .notification_utils import send_subscription_activated_notification
from .redis_utils import (
    clear_vendor_cache,
    set_card_info,
    set_days_left,
    set_has_card,
    set_payment_method_id,
    set_subscription_status,
)
from .stripe_utils import create_stripe_customer, create_trial_subscription


@receiver(post_save, sender=VendorProfile)
def create_vendor_trial_subscription(sender, instance, created, **kwargs):
    """
    Signal to create a trial subscription when a vendor profile is completed
    """
    # Only proceed if the profile was just marked as completed
    if instance.is_completed and not hasattr(instance, "subscription"):
        # Check if there's a subscription plan for this category
        if not hasattr(instance.category, "subscription_plan"):
            return

        # Create Stripe customer
        customer_id = create_stripe_customer(instance)

        # Create trial subscription
        stripe_sub, trial_end = create_trial_subscription(instance, customer_id)

        # Create local subscription record
        subscription = VendorSubscription.objects.create(
            vendor=instance,
            plan=instance.category.subscription_plan,
            stripe_customer_id=customer_id,
            stripe_subscription_id=stripe_sub.id,
            trial_ends_at=trial_end,
            status="trialing",
        )

        # Cache trial days left
        days_left = (trial_end - now()).days
        set_days_left(instance.id, days_left)
        set_subscription_status(instance.id, "trialing")


@receiver(post_save, sender=PaymentMethod)
def handle_payment_method_saved(sender, instance, created, **kwargs):
    """
    Signal to update cache when a payment method is saved
    """
    if created:
        # Update cache
        set_card_info(
            instance.vendor.id,
            {
                "brand": instance.card_brand,
                "last4": instance.last4,
                "exp_month": instance.exp_month,
                "exp_year": instance.exp_year,
            },
        )
        set_has_card(instance.vendor.id, True)

        # If this is the default payment method, update that cache
        if instance.is_default:
            set_payment_method_id(
                instance.vendor.id, instance.stripe_payment_method_id, permanent=True
            )

    # If this payment method was set as default, ensure others are not default
    if instance.is_default:
        PaymentMethod.objects.filter(vendor=instance.vendor).exclude(
            id=instance.id
        ).update(is_default=False)


@receiver(post_delete, sender=PaymentMethod)
def handle_payment_method_deleted(sender, instance, **kwargs):
    """
    Signal to update cache when a payment method is deleted
    """
    # If the vendor has other payment methods, find the new default
    try:
        new_default = PaymentMethod.objects.filter(vendor=instance.vendor).first()
        if new_default:
            new_default.is_default = True
            new_default.save()

            # Update cache for the new default
            set_card_info(
                instance.vendor.id,
                {
                    "brand": new_default.card_brand,
                    "last4": new_default.last4,
                    "exp_month": new_default.exp_month,
                    "exp_year": new_default.exp_year,
                },
            )
            set_payment_method_id(
                instance.vendor.id, new_default.stripe_payment_method_id, permanent=True
            )
        else:
            # No payment methods left, update cache
            set_has_card(instance.vendor.id, False)
    except Exception as e:
        # Log the error
        print(f"Error updating payment method cache: {e}")
