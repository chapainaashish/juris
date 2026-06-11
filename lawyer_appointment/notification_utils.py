import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def create_notification(user, notification_type, message):
    """
    Create a notification in the database
    """
    from subscriptions.models import Notification

    notification = Notification.objects.create(
        user=user, type=notification_type, message=message
    )
    return notification


def send_email_notification(user, subject, message, html_message=None):
    """
    Send email notification to user
    """
    try:
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        logger.info(f"Email sent to {user.email}: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email to {user.email}: {str(e)}")


def send_websocket_notification(user, notification_data):
    """
    Send real-time notification via WebSocket
    """
    try:
        channel_layer = get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"user_{user.id}_notifications",
            {
                "type": "notification_message",
                "notification": notification_data,
            },
        )
        logger.info(f"WebSocket notification sent to user {user.id}")
    except Exception as e:
        logger.error(
            f"Failed to send WebSocket notification to user {user.id}: {str(e)}"
        )


def send_notification(
    user, notification_type, message, email_subject=None, email_html=None
):
    """
    Unified function to send notification via database, email, and WebSocket

    Args:
        user: User object
        notification_type: Type from Notification.TYPES
        message: Plain text message
        email_subject: Subject for email (optional, defaults to notification type)
        email_html: HTML version of email (optional)
    """
    # Create database notification
    notification = create_notification(user, notification_type, message)

    # Send email
    if not email_subject:
        email_subject = (
            f"Notification: {dict(notification.TYPES).get(notification_type, 'Update')}"
        )

    send_email_notification(user, email_subject, message, email_html)

    # Send WebSocket notification
    notification_data = {
        "id": notification.id,
        "type": notification_type,
        "message": message,
        "created_at": notification.created_at.isoformat(),
        "read": notification.read,
    }
    send_websocket_notification(user, notification_data)

    return notification
