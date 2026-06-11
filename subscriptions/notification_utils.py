from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

from .models import Notification, PaymentMethod


def send_notification(user, notification_type, message, related_data=None):
    """
    Send a notification to a user via both email and in-app channels

    Parameters:
    - user: User object to receive the notification
    - notification_type: Type of notification (see Notification.TYPES)
    - message: Notification message
    - related_data: Optional dictionary with additional data
    """
    # 1. Create in-app notification
    notification = Notification.objects.create(
        user=user, type=notification_type, message=message
    )

    # 2. Send real-time update via WebSocket
    notification_data = {
        "id": notification.id,
        "type": notification.type,
        "message": notification.message,
        "created_at": notification.created_at.isoformat(),
        "read": notification.read,
    }

    if related_data:
        notification_data.update(related_data)

    channel_layer = get_channel_layer()
    room_group_name = f"notifications_{user.id}"

    try:
        async_to_sync(channel_layer.group_send)(
            room_group_name,
            {"type": "notification_message", "notification": notification_data},
        )
    except Exception as e:
        # Log the error but continue with email notification
        print(f"WebSocket notification error: {e}")

    # 3. Send email notification
    send_email_notification(user, notification_type, message, related_data)

    return notification


def send_email_notification(user, notification_type, message, related_data=None):
    """Send an email notification"""
    subject_templates = {
        "trial_ending": "Your trial period is ending soon",
        "free_period_ending": "Your free period is ending soon",
        "subscription_renewing": "Your subscription will renew soon",
        "payment_failed": "Payment failed for your subscription",
        "subscription_canceled": "Your subscription has been canceled",
        "subscription_activated": "Your subscription has been activated",
    }

    subject = subject_templates.get(
        notification_type, "Important notification about your subscription"
    )

    # Prepare context for email template
    context = {
        "user": user,
        "message": message,
        "notification_type": notification_type,
    }

    if related_data:
        context.update(related_data)

    # Render email content from template
    email_html = render_to_string(
        f"subscriptions/emails/{notification_type}.html", context
    )
    email_text = render_to_string(
        f"subscriptions/emails/{notification_type}.txt", context
    )

    # Send the email
    send_mail(
        subject=subject,
        message=email_text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[user.email],
        html_message=email_html,
        fail_silently=False,
    )


def send_trial_ending_notification(subscription):
    """Send notification for trial ending in 3 days"""
    vendor = subscription.vendor
    user = vendor.user

    message = f"Your 15-day free trial for {vendor.category.name} subscription will end in 3 days. Please ensure you have a payment method added to continue your subscription."

    related_data = {
        "subscription_id": subscription.id,
        "days_left": 3,
        "category": vendor.category.name,
        "has_payment_method": PaymentMethod.objects.filter(
            vendor=vendor, is_default=True
        ).exists(),
    }

    return send_notification(user, "trial_ending", message, related_data)


def send_subscription_renewing_notification(subscription):
    """Send notification for subscription renewal"""
    vendor = subscription.vendor
    user = vendor.user

    message = f"Your {vendor.category.name} subscription will automatically renew in {subscription.days_until_renewal} days."

    related_data = {
        "subscription_id": subscription.id,
        "days_left": subscription.days_until_renewal,
        "category": vendor.category.name,
        "renewal_date": subscription.current_period_end.strftime("%Y-%m-%d"),
    }

    return send_notification(user, "subscription_renewing", message, related_data)


def send_free_period_ending_notification(subscription):
    """Send notification for free period ending"""
    vendor = subscription.vendor
    user = vendor.user

    message = f"Your free period for {vendor.category.name} subscription will end in {subscription.days_until_renewal} days."

    related_data = {
        "subscription_id": subscription.id,
        "days_left": subscription.days_until_renewal,
        "category": vendor.category.name,
        "end_date": subscription.current_period_end.strftime("%Y-%m-%d"),
    }

    return send_notification(user, "free_period_ending", message, related_data)


def send_payment_failed_notification(subscription):
    """Send notification for payment failure"""
    vendor = subscription.vendor
    user = vendor.user

    message = f"We were unable to process your payment for your {vendor.category.name} subscription. Please update your payment method."

    related_data = {
        "subscription_id": subscription.id,
        "category": vendor.category.name,
        "retry_link": f"/vendor/dashboard/payment",
    }

    return send_notification(user, "payment_failed", message, related_data)


def send_subscription_canceled_notification(subscription):
    """Send notification for canceled subscription"""
    vendor = subscription.vendor
    user = vendor.user

    message = f"Your {vendor.category.name} subscription has been canceled."

    related_data = {
        "subscription_id": subscription.id,
        "category": vendor.category.name,
        "end_date": (
            subscription.current_period_end.strftime("%Y-%m-%d")
            if subscription.current_period_end
            else None
        ),
    }

    return send_notification(user, "subscription_canceled", message, related_data)


def send_subscription_activated_notification(subscription):
    """Send notification for activated subscription"""
    vendor = subscription.vendor
    user = vendor.user

    message = (
        f"Your {vendor.category.name} subscription has been activated successfully."
    )

    related_data = {
        "subscription_id": subscription.id,
        "category": vendor.category.name,
        "next_billing_date": (
            subscription.current_period_end.strftime("%Y-%m-%d")
            if subscription.current_period_end
            else None
        ),
    }

    return send_notification(user, "subscription_activated", message, related_data)
