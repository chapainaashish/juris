import logging

from celery import shared_task

from subscriptions.models import Notification

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3)
def send_withdrawal_approved_notification(self, transaction_id):
    """
    Send notification when withdrawal is approved
    """
    try:
        from lawyer_appointment.notification_utils import send_notification
        from lawyer_wallet.models import Transaction, TransactionType

        try:
            txn = Transaction.objects.select_related(
                "lawyer__vendor_profile__user"
            ).get(id=transaction_id)

            # Only send for payout transactions
            if txn.transaction_type == TransactionType.PAYOUT:
                logger.info(
                    f"Sending withdrawal approval notification for transaction {transaction_id}"
                )

                message = (
                    f"Your withdrawal request of {txn.amount} USD has been approved. "
                    f"The funds will be transferred to your account shortly."
                )

                send_notification(
                    user=txn.lawyer.vendor_profile.user,
                    notification_type=Notification.WITHDRAWAL_APPROVED,
                    message=message,
                    email_subject="Withdrawal Approved",
                )

                logger.info(
                    f"Successfully sent withdrawal approval notification for transaction {transaction_id}"
                )

        except Transaction.DoesNotExist:
            logger.warning(
                f"Transaction {transaction_id} not found for withdrawal notification"
            )

    except Exception as exc:
        logger.error(
            f"Error sending withdrawal notification for transaction {transaction_id}: {str(exc)}"
        )
        raise self.retry(exc=exc, countdown=60)
