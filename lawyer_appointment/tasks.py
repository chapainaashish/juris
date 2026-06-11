import logging

from celery import shared_task
from django.db import transaction

from subscriptions.models import Notification

from .notification_utils import send_notification

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def delete_unpaid_appointment(self, appointment_id):
    """
    Delete appointment if payment hasn't been completed within the time limit
    """
    try:
        from lawyer_appointment.models import Appointment, AppointmentStatus
        from lawyer_wallet.models import Transaction, TransactionStatus, TransactionType

        with transaction.atomic():
            try:
                appointment = Appointment.objects.get(id=appointment_id)

                # Only delete if still pending (not paid)
                if appointment.status == AppointmentStatus.PENDING:
                    logger.info(f"Deleting unpaid appointment {appointment_id}")

                    # Cancel associated payment transaction
                    payment_transaction = Transaction.objects.filter(
                        appointment=appointment,
                        transaction_type=TransactionType.PAYMENT,
                        status=TransactionStatus.PENDING,
                    ).first()

                    if payment_transaction:
                        payment_transaction.status = TransactionStatus.CANCELLED
                        payment_transaction.save(update_fields=["status"])
                        logger.info(
                            f"Cancelled payment transaction for appointment {appointment_id}"
                        )

                    # Delete the appointment
                    appointment.delete()
                    logger.info(
                        f"Successfully deleted unpaid appointment {appointment_id}"
                    )
                else:
                    logger.info(f"Appointment {appointment_id} was paid, not deleting")

            except Appointment.DoesNotExist:
                logger.info(
                    f"Appointment {appointment_id} already deleted or doesn't exist"
                )

    except Exception as exc:
        logger.error(f"Error deleting unpaid appointment {appointment_id}: {str(exc)}")
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3)
def send_appointment_reminder(self, appointment_id):
    """
    Send reminder notifications 24 hours before appointment
    """
    try:
        from lawyer_appointment.models import Appointment, AppointmentStatus

        try:
            appointment = Appointment.objects.get(id=appointment_id)

            # Only send reminder for confirmed appointments
            if appointment.status == AppointmentStatus.CONFIRMED:
                logger.info(f"Sending reminder for appointment {appointment_id}")

                # Send reminder to client
                client_message = (
                    f"Reminder: You have an appointment with {appointment.lawyer.vendor_profile.business_name} "
                    f"tomorrow at {appointment.start_datetime.strftime('%H:%M')}. "
                    f"Please be on time for your {appointment.offering_type.get_type_display().lower()} consultation."
                )

                send_notification(
                    user=appointment.client,
                    notification_type=Notification.APPOINTMENT_REMINDER,
                    message=client_message,
                    email_subject="Appointment Reminder - Tomorrow",
                )

                # Send reminder to lawyer
                lawyer_message = (
                    f"Reminder: You have an appointment with {appointment.client.get_full_name()} "
                    f"tomorrow at {appointment.start_datetime.strftime('%H:%M')}. "
                    f"Type: {appointment.offering_type.get_type_display()}"
                )

                send_notification(
                    user=appointment.lawyer.vendor_profile.user,
                    notification_type=Notification.APPOINTMENT_REMINDER,
                    message=lawyer_message,
                    email_subject="Appointment Reminder - Tomorrow",
                )

                logger.info(
                    f"Successfully sent reminders for appointment {appointment_id}"
                )
            else:
                logger.info(
                    f"Appointment {appointment_id} status is {appointment.status}, not sending reminder"
                )

        except Appointment.DoesNotExist:
            logger.warning(f"Appointment {appointment_id} not found for reminder")

    except Exception as exc:
        logger.error(
            f"Error sending reminder for appointment {appointment_id}: {str(exc)}"
        )
        raise self.retry(exc=exc, countdown=300)


@shared_task(bind=True, max_retries=3)
def send_appointment_starting_notification(self, appointment_id):
    """
    Send notification when appointment is about to start (5-10 minutes before)
    """
    try:
        from lawyer_appointment.models import Appointment, AppointmentStatus

        try:
            appointment = Appointment.objects.get(id=appointment_id)

            # Only send for confirmed appointments
            if appointment.status == AppointmentStatus.CONFIRMED:
                logger.info(
                    f"Sending start notification for appointment {appointment_id}"
                )

                # Notification to client
                client_message = (
                    f"Your appointment with {appointment.lawyer.vendor_profile.business_name} "
                    f"is starting soon at {appointment.start_datetime.strftime('%H:%M')}. "
                    f"Please join on time."
                )

                send_notification(
                    user=appointment.client,
                    notification_type=Notification.APPOINTMENT_STARTING,
                    message=client_message,
                    email_subject="Your Appointment is Starting Soon",
                )

                # Notification to lawyer
                lawyer_message = (
                    f"Your appointment with {appointment.client.get_full_name()} "
                    f"is starting soon at {appointment.start_datetime.strftime('%H:%M')}."
                )

                send_notification(
                    user=appointment.lawyer.vendor_profile.user,
                    notification_type=Notification.APPOINTMENT_STARTING,
                    message=lawyer_message,
                    email_subject="Your Appointment is Starting Soon",
                )

                logger.info(
                    f"Successfully sent start notifications for appointment {appointment_id}"
                )
            else:
                logger.info(
                    f"Appointment {appointment_id} status is {appointment.status}, not sending start notification"
                )

        except Appointment.DoesNotExist:
            logger.warning(
                f"Appointment {appointment_id} not found for start notification"
            )

    except Exception as exc:
        logger.error(
            f"Error sending start notification for appointment {appointment_id}: {str(exc)}"
        )
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=2)
def process_refund_via_stripe(self, appointment_id, admin_user_id=None):
    """
    Process refund through Stripe after admin approval
    """
    try:
        import stripe
        from django.conf import settings

        from lawyer_appointment.models import Appointment, RefundStatus
        from lawyer_wallet.models import Transaction, TransactionStatus, TransactionType
        from users.models import User

        stripe.api_key = settings.STRIPE_SECRET_KEY

        with transaction.atomic():
            appointment = Appointment.objects.get(id=appointment_id)

            if appointment.refund_status != RefundStatus.APPROVED:
                logger.error(f"Appointment {appointment_id} refund not approved")
                return

            # Get the refund transaction
            refund_transaction = Transaction.objects.filter(
                appointment=appointment,
                transaction_type=TransactionType.REFUND,
                status=TransactionStatus.PENDING,
            ).first()

            if not refund_transaction:
                logger.error(
                    f"No pending refund transaction found for appointment {appointment_id}"
                )
                return

            try:
                # Process Stripe refund
                refund = stripe.Refund.create(
                    payment_intent=appointment.stripe_payment_intent_id,
                    amount=int(appointment.total_price * 100),
                    metadata={
                        "appointment_id": str(appointment.id),
                        "transaction_id": str(refund_transaction.id),
                    },
                )

                # Update transaction
                refund_transaction.stripe_transaction_id = refund.id
                if admin_user_id:
                    refund_transaction.processed_by = User.objects.get(id=admin_user_id)
                refund_transaction.save()

                # Send refund approval notification to client
                refund_message = (
                    f"Your refund request for appointment with "
                    f"{appointment.lawyer.vendor_profile.business_name} has been approved. "
                    f"Amount: {appointment.total_price} USD. "
                    f"The refund will be processed within 1-2 business days."
                )

                send_notification(
                    user=appointment.client,
                    notification_type=Notification.REFUND_APPROVED,
                    message=refund_message,
                    email_subject="Refund Approved",
                )

                logger.info(
                    f"Stripe refund created successfully for appointment {appointment_id}: {refund.id}"
                )

                # Note: Transaction status will be updated to COMPLETED by webhook

            except stripe.error.StripeError as e:
                logger.error(
                    f"Stripe refund failed for appointment {appointment_id}: {str(e)}"
                )

                # Update refund status back to pending for manual review
                appointment.refund_status = RefundStatus.PENDING
                appointment.refund_response = f"Stripe refund failed: {str(e)}"
                appointment.save()

                # Mark transaction as failed
                refund_transaction.status = TransactionStatus.FAILED
                refund_transaction.save()

                raise self.retry(exc=e, countdown=600)  # Retry after 10 minutes

    except Exception as exc:
        logger.error(
            f"Error processing refund for appointment {appointment_id}: {str(exc)}"
        )
        raise self.retry(exc=exc, countdown=600)
