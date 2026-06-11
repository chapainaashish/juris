from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.timezone import now

from subscriptions.models import VendorSubscription
from subscriptions.notification_utils import (
    send_free_period_ending_notification,
    send_subscription_renewing_notification,
    send_trial_ending_notification,
)


class Command(BaseCommand):
    help = "Check subscription trial and renewal dates and send notifications"

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Checking subscription dates..."))

        # Get current date
        current_date = now()

        # Calculate the date for notification threshold (default 2 days before)
        notification_date = current_date + timedelta(days=settings.NOTIFY_BEFORE_DAYS)

        # Check for trial ending
        self.check_trial_ending(notification_date)

        # Check for subscription renewals
        self.check_subscription_renewals(notification_date)

        # Check for free period ending
        self.check_free_period_ending(notification_date)

        self.stdout.write(self.style.SUCCESS("Subscription check completed"))

    def check_trial_ending(self, notification_date):
        """Check for trials that are ending soon"""
        # Find subscriptions that are in trial and ending near the notification date
        trial_ending_subscriptions = VendorSubscription.objects.filter(
            status="trialing", trial_ends_at__date=notification_date.date()
        )

        self.stdout.write(
            f"Found {trial_ending_subscriptions.count()} trials ending soon"
        )

        # Send notifications
        for subscription in trial_ending_subscriptions:
            try:
                send_trial_ending_notification(subscription)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Sent trial ending notification to {subscription.vendor.user.email}"
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Error sending trial ending notification: {str(e)}"
                    )
                )

    def check_subscription_renewals(self, notification_date):
        """Check for subscriptions that are renewing soon"""
        # Find active subscriptions renewing near the notification date
        renewing_subscriptions = VendorSubscription.objects.filter(
            status="active", current_period_end__date=notification_date.date()
        )

        self.stdout.write(
            f"Found {renewing_subscriptions.count()} subscriptions renewing soon"
        )

        # Send notifications
        for subscription in renewing_subscriptions:
            try:
                send_subscription_renewing_notification(subscription)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Sent renewal notification to {subscription.vendor.user.email}"
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(f"Error sending renewal notification: {str(e)}")
                )

    def check_free_period_ending(self, notification_date):
        """Check for free periods that are ending soon"""
        # This is for cases where a voucher added free months
        # These subscriptions have status=active but are still in a trial period
        free_ending_subscriptions = VendorSubscription.objects.filter(
            status="active",
            trial_ends_at__date=notification_date.date(),
            voucher__isnull=False,
        )

        self.stdout.write(
            f"Found {free_ending_subscriptions.count()} free periods ending soon"
        )

        # Send notifications
        for subscription in free_ending_subscriptions:
            try:
                send_free_period_ending_notification(subscription)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Sent free period ending notification to {subscription.vendor.user.email}"
                    )
                )
            except Exception as e:
                self.stdout.write(
                    self.style.ERROR(
                        f"Error sending free period ending notification: {str(e)}"
                    )
                )
