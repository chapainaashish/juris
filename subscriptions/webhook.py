import json
import logging

import stripe
from celery import current_app
from django.conf import settings
from django.db import transaction
from django.http import HttpResponse
from django.utils.timezone import now
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from kyc.models import KYCVerification
from lawyer_appointment.models import Appointment, AppointmentStatus, RefundStatus
from lawyer_appointment.tasks import (
    send_appointment_reminder,
)
from lawyer_wallet.models import Transaction, TransactionStatus

from .models import (
    SubscriptionInvoice,
    VendorSubscription,
)
from .notification_utils import (
    send_notification,
    send_payment_failed_notification,
    send_subscription_activated_notification,
    send_trial_ending_notification,
)
from .redis_utils import set_days_left, set_subscription_status
from .stripe_utils import parse_stripe_timestamp

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    payload = request.body
    sig_header = request.META.get("HTTP_STRIPE_SIGNATURE")

    # If in development, skip signature verification
    if settings.DEBUG:
        try:
            event = stripe.Event.construct_from(json.loads(payload), stripe.api_key)
        except ValueError:
            return HttpResponse(status=400)
    else:
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
            )
        except ValueError:
            return HttpResponse(status=400)
        except stripe.error.SignatureVerificationError:
            return HttpResponse(status=400)

    # Handle subscription events
    if event["type"] == "customer.subscription.created":
        handle_subscription_created(event)
    elif event["type"] == "customer.subscription.updated":
        handle_subscription_updated(event)
    elif event["type"] == "customer.subscription.deleted":
        handle_subscription_deleted(event)
    elif event["type"] == "invoice.payment_succeeded":
        handle_payment_succeeded(event)
    elif event["type"] == "invoice.payment_failed":
        handle_payment_failed(event)
    elif event["type"] == "customer.subscription.trial_will_end":
        handle_trial_will_end(event)

    # Handle appointment payment events
    elif event["type"] == "payment_intent.succeeded":
        handle_appointment_payment_succeeded(event)
    elif event["type"] == "payment_intent.payment_failed":
        handle_appointment_payment_failed(event)
    elif event["type"] == "payment_intent.canceled":
        handle_appointment_payment_canceled(event)

    # Handle refund events
    elif event["type"] == "charge.dispute.created":
        handle_charge_disputed(event)
    elif event["type"] == "refund.created":
        handle_refund_succeeded(event)
    elif event["type"] == "refund.failed":
        handle_refund_failed(event)

    # Handle KYC Identity events (simplified)
    elif event["type"] == "identity.verification_session.verified":
        handle_kyc_verified(event)
    elif event["type"] == "identity.verification_session.requires_input":
        handle_kyc_requires_input(event)
    elif event["type"] == "identity.verification_session.canceled":
        handle_kyc_canceled(event)
    elif event["type"] == "identity.verification_session.processing":
        handle_kyc_processing(event)
    else:
        logger.info(f"Unhandled webhook event type: {event['type']}")

    return HttpResponse(status=200)


# Appointment Payment Handlers
def handle_appointment_payment_succeeded(event):
    """Handle successful appointment payment"""
    payment_intent = event["data"]["object"]
    appointment_id = payment_intent["metadata"].get("appointment_id")
    transaction_id = payment_intent["metadata"].get("transaction_id")

    if not appointment_id:
        logger.warning("Payment succeeded but no appointment_id in metadata")
        return

    try:
        appointment = Appointment.objects.get(id=appointment_id)

        with transaction.atomic():
            # Cancel the deletion task since payment succeeded
            if appointment.payment_task_id:
                current_app.control.revoke(appointment.payment_task_id, terminate=True)

            # Update appointment status to confirmed
            appointment.status = AppointmentStatus.CONFIRMED
            appointment.stripe_payment_intent_id = payment_intent["id"]
            appointment.save()

            # Update the payment transaction - keep as PENDING until appointment completion
            if transaction_id:
                try:
                    payment_transaction = Transaction.objects.get(id=transaction_id)
                    payment_transaction.stripe_transaction_id = payment_intent["id"]
                    # Keep status as PENDING - funds are in escrow until appointment completion
                    payment_transaction.save(update_fields=["stripe_transaction_id"])

                    logger.info(
                        f"Payment transaction {transaction_id} updated with Stripe ID"
                    )
                except Transaction.DoesNotExist:
                    logger.warning(
                        f"Transaction {transaction_id} not found for appointment {appointment_id}"
                    )

            # Schedule reminder for 24 hours before appointment
            _schedule_appointment_reminder(appointment)

            logger.info(f"Appointment {appointment_id} payment succeeded and confirmed")

    except Appointment.DoesNotExist:
        logger.error(f"Appointment {appointment_id} not found for payment success")


def handle_appointment_payment_failed(event):
    """Handle failed appointment payment"""
    payment_intent = event["data"]["object"]
    appointment_id = payment_intent["metadata"].get("appointment_id")
    transaction_id = payment_intent["metadata"].get("transaction_id")

    if not appointment_id:
        logger.warning("Payment failed but no appointment_id in metadata")
        return

    try:
        appointment = Appointment.objects.get(id=appointment_id)

        with transaction.atomic():
            # Update transaction status to failed
            if transaction_id:
                try:
                    payment_transaction = Transaction.objects.get(id=transaction_id)
                    payment_transaction.status = TransactionStatus.FAILED
                    payment_transaction.save(update_fields=["status"])
                    logger.info(
                        f"Payment transaction {transaction_id} marked as failed"
                    )
                except Transaction.DoesNotExist:
                    logger.warning(
                        f"Transaction {transaction_id} not found for failed payment"
                    )

            # Delete the appointment since payment failed
            logger.info(f"Deleting appointment {appointment_id} due to payment failure")
            appointment.delete()

    except Appointment.DoesNotExist:
        logger.warning(f"Appointment {appointment_id} not found for payment failure")


def handle_appointment_payment_canceled(event):
    """Handle canceled appointment payment"""
    payment_intent = event["data"]["object"]
    appointment_id = payment_intent["metadata"].get("appointment_id")
    transaction_id = payment_intent["metadata"].get("transaction_id")

    if not appointment_id:
        logger.warning("Payment canceled but no appointment_id in metadata")
        return

    try:
        appointment = Appointment.objects.get(id=appointment_id)

        with transaction.atomic():
            # Update transaction status to cancelled
            if transaction_id:
                try:
                    payment_transaction = Transaction.objects.get(id=transaction_id)
                    payment_transaction.status = TransactionStatus.CANCELLED
                    payment_transaction.save(update_fields=["status"])
                    logger.info(f"Payment transaction {transaction_id} cancelled")
                except Transaction.DoesNotExist:
                    logger.warning(
                        f"Transaction {transaction_id} not found for cancelled payment"
                    )

            # Delete the appointment since payment was canceled
            logger.info(
                f"Deleting appointment {appointment_id} due to payment cancellation"
            )
            appointment.delete()

    except Appointment.DoesNotExist:
        logger.warning(
            f"Appointment {appointment_id} not found for payment cancellation"
        )


def _schedule_appointment_reminder(appointment):
    """Schedule reminder task 24 hours before appointment"""
    from datetime import timedelta

    reminder_time = appointment.start_datetime - timedelta(hours=24)

    # Only schedule if appointment is more than 24 hours away
    if reminder_time > now():
        reminder_task = send_appointment_reminder.apply_async(
            args=[str(appointment.id)], eta=reminder_time
        )

        # Store task ID for potential cancellation
        appointment.reminder_task_id = reminder_task.id
        appointment.save(update_fields=["reminder_task_id"])


# Existing subscription handlers (unchanged)
def handle_subscription_created(event):
    """Handle subscription creation webhook"""
    subscription = event["data"]["object"]

    # Check if we have a subscription with this ID
    try:
        vendor_sub = VendorSubscription.objects.get(
            stripe_subscription_id=subscription["id"]
        )

        # Update subscription details
        vendor_sub.status = subscription["status"]

        if subscription.get("trial_end"):
            vendor_sub.trial_ends_at = parse_stripe_timestamp(subscription["trial_end"])

        if subscription.get("current_period_end"):
            vendor_sub.current_period_end = parse_stripe_timestamp(
                subscription["current_period_end"]
            )

        vendor_sub.save()

        # Update cache
        set_subscription_status(vendor_sub.vendor.id, subscription["status"])

        # Update days left cache if trialing
        if subscription["status"] == "trialing" and subscription.get("trial_end"):
            trial_end = parse_stripe_timestamp(subscription["trial_end"])
            days_left = (trial_end - now()).days
            set_days_left(vendor_sub.vendor.id, max(0, days_left))

        logger.info(
            f"Subscription created for vendor {vendor_sub.vendor.business_name}"
        )

    except VendorSubscription.DoesNotExist:
        # If we don't have this subscription, it might have been created outside our system
        logger.warning(
            f"Subscription created webhook for unknown subscription: {subscription['id']}"
        )


def handle_subscription_updated(event):
    """Handle subscription update webhook - IMPROVED VERSION"""
    subscription = event["data"]["object"]
    previous_attributes = event.get("data", {}).get("previous_attributes", {})

    try:
        vendor_sub = VendorSubscription.objects.get(
            stripe_subscription_id=subscription["id"]
        )

        old_status = vendor_sub.status
        old_trial_end = vendor_sub.trial_ends_at

        # Update subscription fields
        vendor_sub.status = subscription["status"]

        if subscription.get("trial_end"):
            vendor_sub.trial_ends_at = parse_stripe_timestamp(subscription["trial_end"])

        if subscription.get("current_period_end"):
            vendor_sub.current_period_end = parse_stripe_timestamp(
                subscription["current_period_end"]
            )

        if subscription.get("canceled_at"):
            vendor_sub.canceled_at = parse_stripe_timestamp(subscription["canceled_at"])

        vendor_sub.save()

        # Update cache
        set_subscription_status(vendor_sub.vendor.id, subscription["status"])

        # CRITICAL: Detect trial-to-paid transition
        trial_just_ended = detect_trial_end_transition(
            old_status, subscription["status"], old_trial_end, subscription
        )

        if trial_just_ended:
            logger.info(
                f"Trial just ended for vendor {vendor_sub.vendor.business_name}"
            )
            handle_trial_to_paid_transition(vendor_sub, subscription)

        # Handle other status-based listing management
        elif subscription["status"] == "active" and old_status != "active":
            # Subscription became active (not from trial)
            vendor_sub.vendor.activate_listing()
            logger.info(
                f"Activated listing for vendor {vendor_sub.vendor.business_name}"
            )

        elif subscription["status"] in [
            "canceled",
            "past_due",
            "unpaid",
        ] and old_status not in ["canceled", "past_due", "unpaid"]:
            # Subscription became inactive
            vendor_sub.vendor.deactivate_listing()
            logger.info(
                f"Deactivated listing for vendor {vendor_sub.vendor.business_name}"
            )

        # Update days left cache for active subscriptions
        if subscription["status"] == "active" and subscription.get(
            "current_period_end"
        ):
            period_end = parse_stripe_timestamp(subscription["current_period_end"])
            days_left = (period_end - now()).days
            set_days_left(vendor_sub.vendor.id, max(0, days_left))

    except VendorSubscription.DoesNotExist:
        logger.warning(
            f"Subscription updated webhook for unknown subscription: {subscription['id']}"
        )


def detect_trial_end_transition(old_status, new_status, old_trial_end, subscription):
    """
    Detect if this subscription update represents a trial ending
    Returns True if trial just ended, False otherwise
    """
    # Method 1: Status changed from trialing to something else
    status_changed_from_trial = old_status == "trialing" and new_status != "trialing"

    # Method 2: Trial end date is in the past (backup check)
    trial_end_passed = False
    if subscription.get("trial_end"):
        trial_end = parse_stripe_timestamp(subscription["trial_end"])
        trial_end_passed = trial_end <= now()

    # Method 3: Check if trial_end was updated to null (trial completed)
    trial_end_cleared = old_trial_end is not None and not subscription.get("trial_end")

    return (
        status_changed_from_trial
        or (trial_end_passed and old_status == "trialing")
        or trial_end_cleared
    )


def handle_trial_to_paid_transition(vendor_sub, subscription):
    """
    Handle the transition from trial to paid subscription
    This is called when a trial period has just ended
    """
    vendor = vendor_sub.vendor
    new_status = subscription["status"]

    if new_status == "active":
        # Trial ended and subscription is active (payment succeeded)
        vendor.activate_listing()
        send_subscription_activated_notification(vendor_sub)

        # Clear trial days cache, set renewal days
        if subscription.get("current_period_end"):
            period_end = parse_stripe_timestamp(subscription["current_period_end"])
            days_left = (period_end - now()).days
            set_days_left(vendor.id, max(0, days_left))

        logger.info(
            f"Successfully activated subscription for vendor {vendor.business_name}"
        )

    elif new_status in ["past_due", "unpaid"]:
        # Trial ended but payment failed
        vendor.deactivate_listing()
        send_payment_failed_notification(vendor_sub)

        # Clear days left cache
        set_days_left(vendor.id, 0)

        logger.warning(
            f"Trial ended with payment failure for vendor {vendor.business_name}"
        )

    elif new_status == "incomplete" or new_status == "incomplete_expired":
        # Trial ended but no payment method or payment incomplete
        vendor.deactivate_listing()

        from .notification_utils import send_notification

        send_notification(
            vendor.user,
            "general",
            "Your trial has ended. Please add a payment method to continue your subscription and reactivate your listing.",
        )

        # Clear days left cache
        set_days_left(vendor.id, 0)

        logger.info(
            f"Trial ended - no payment method for vendor {vendor.business_name}"
        )

    else:
        # Handle any other edge cases
        vendor.deactivate_listing()
        logger.warning(
            f"Trial ended with unexpected status '{new_status}' for vendor {vendor.business_name}"
        )


def handle_subscription_deleted(event):
    """Handle subscription deletion webhook"""
    subscription = event["data"]["object"]

    try:
        vendor_sub = VendorSubscription.objects.get(
            stripe_subscription_id=subscription["id"]
        )

        # Mark subscription as canceled
        vendor_sub.status = "canceled"
        vendor_sub.canceled_at = now()
        vendor_sub.save()

        # Update cache
        set_subscription_status(vendor_sub.vendor.id, "canceled")
        set_days_left(vendor_sub.vendor.id, 0)

        # Deactivate vendor listing
        vendor_sub.vendor.deactivate_listing()

        logger.info(
            f"Subscription deleted for vendor {vendor_sub.vendor.business_name}"
        )

    except VendorSubscription.DoesNotExist:
        logger.warning(
            f"Subscription deleted webhook for unknown subscription: {subscription['id']}"
        )


def handle_payment_succeeded(event):
    """Handle successful payment webhook"""
    invoice = event["data"]["object"]
    subscription_id = invoice.get("subscription")

    if not subscription_id:
        # Not a subscription invoice
        return

    try:
        # Find the relevant subscription
        vendor_sub = VendorSubscription.objects.get(
            stripe_subscription_id=subscription_id
        )

        # Update subscription status to active if it wasn't already
        old_status = vendor_sub.status
        if vendor_sub.status != "active":
            vendor_sub.status = "active"
            vendor_sub.save()
            set_subscription_status(vendor_sub.vendor.id, "active")

            # Activate vendor listing
            vendor_sub.vendor.activate_listing()

        # Create an invoice record
        SubscriptionInvoice.objects.create(
            subscription=vendor_sub,
            stripe_invoice_id=invoice["id"],
            amount_paid=invoice["amount_paid"] / 100.0,
            invoice_pdf=invoice.get("invoice_pdf"),
            period_start=parse_stripe_timestamp(invoice["period_start"]),
            period_end=parse_stripe_timestamp(invoice["period_end"]),
            status=invoice["status"],
        )

        # Update current_period_end and cache
        if invoice.get("lines", {}).get("data"):
            for line in invoice["lines"]["data"]:
                if line.get("period") and line["period"].get("end"):
                    period_end = parse_stripe_timestamp(line["period"]["end"])
                    vendor_sub.current_period_end = period_end
                    vendor_sub.save()

                    # Update days left cache
                    days_left = (period_end - now()).days
                    set_days_left(vendor_sub.vendor.id, max(0, days_left))
                    break

        # Send notification if this is recovery from past_due
        if old_status == "past_due":
            send_subscription_activated_notification(vendor_sub)

        logger.info(f"Payment succeeded for vendor {vendor_sub.vendor.business_name}")

    except VendorSubscription.DoesNotExist:
        logger.warning(
            f"Payment succeeded webhook for unknown subscription: {subscription_id}"
        )


def handle_payment_failed(event):
    """Handle failed payment webhook"""
    invoice = event["data"]["object"]
    subscription_id = invoice.get("subscription")

    if not subscription_id:
        # Not a subscription invoice
        return

    try:
        # Find the relevant subscription
        vendor_sub = VendorSubscription.objects.get(
            stripe_subscription_id=subscription_id
        )

        # Update subscription status
        vendor_sub.status = "past_due"
        vendor_sub.save()

        # Update cache
        set_subscription_status(vendor_sub.vendor.id, "past_due")
        set_days_left(vendor_sub.vendor.id, 0)  # No access during past_due

        # Deactivate vendor listing for past_due status
        vendor_sub.vendor.deactivate_listing()

        # Send notification to vendor
        send_payment_failed_notification(vendor_sub)

        logger.warning(f"Payment failed for vendor {vendor_sub.vendor.business_name}")

    except VendorSubscription.DoesNotExist:
        logger.warning(
            f"Payment failed webhook for unknown subscription: {subscription_id}"
        )


def handle_trial_will_end(event):
    """Handle trial ending webhook - 3 days before"""
    subscription = event["data"]["object"]

    try:
        # Find the relevant subscription
        vendor_sub = VendorSubscription.objects.get(
            stripe_subscription_id=subscription["id"]
        )

        # Only send notification if still in trial
        if vendor_sub.status == "trialing":
            # Send notification about trial ending
            send_trial_ending_notification(vendor_sub)
            logger.info(
                f"Sent trial ending notification for vendor {vendor_sub.vendor.business_name}"
            )

    except VendorSubscription.DoesNotExist:
        logger.warning(
            f"Trial will end webhook for unknown subscription: {subscription['id']}"
        )


# KYC webhook handlers
def handle_kyc_verified(event):
    """Handle verified KYC verification"""
    verification_session = event["data"]["object"]
    try:
        kyc = KYCVerification.objects.get(
            stripe_verification_session_id=verification_session["id"]
        )
        kyc.update_from_stripe_data(verification_session)
        kyc.save()
        logger.info(
            f"KYC verified for {kyc.lawyer_profile.vendor_profile.business_name}"
        )
    except KYCVerification.DoesNotExist:
        logger.error(f"KYC not found for session {verification_session['id']}")


def handle_kyc_requires_input(event):
    """Handle KYC requiring input"""
    verification_session = event["data"]["object"]
    try:
        kyc = KYCVerification.objects.get(
            stripe_verification_session_id=verification_session["id"]
        )
        kyc.update_from_stripe_data(verification_session)
        kyc.save()
        logger.info(
            f"KYC requires input for {kyc.lawyer_profile.vendor_profile.business_name}"
        )
    except KYCVerification.DoesNotExist:
        logger.error(f"KYC not found for session {verification_session['id']}")


def handle_kyc_canceled(event):
    """Handle canceled KYC verification"""
    verification_session = event["data"]["object"]
    try:
        kyc = KYCVerification.objects.get(
            stripe_verification_session_id=verification_session["id"]
        )
        kyc.update_from_stripe_data(verification_session)
        kyc.save()
        logger.info(
            f"KYC canceled for {kyc.lawyer_profile.vendor_profile.business_name}"
        )
    except KYCVerification.DoesNotExist:
        logger.error(f"KYC not found for session {verification_session['id']}")


def handle_kyc_processing(event):
    """Handle processing KYC verification"""
    verification_session = event["data"]["object"]
    try:
        kyc = KYCVerification.objects.get(
            stripe_verification_session_id=verification_session["id"]
        )
        kyc.update_from_stripe_data(verification_session)
        kyc.save()
        logger.info(
            f"KYC processing for {kyc.lawyer_profile.vendor_profile.business_name}"
        )
    except KYCVerification.DoesNotExist:
        logger.error(f"KYC not found for session {verification_session['id']}")


def handle_refund_succeeded(event):
    """Handle successful refund processing"""
    refund_data = event["data"]["object"]

    # Handle refund.created events
    if event["type"] == "refund.created":
        appointment_id = refund_data["metadata"].get("appointment_id")
        transaction_id = refund_data["metadata"].get("transaction_id")
        refund_id = refund_data["id"]
    else:
        logger.warning(
            f"Unexpected event type in handle_refund_succeeded: {event['type']}"
        )
        return

    if not appointment_id:
        logger.warning("Refund succeeded but no appointment_id in metadata")
        return

    try:
        appointment = Appointment.objects.get(id=appointment_id)

        with transaction.atomic():
            # Update refund transaction status to completed
            if transaction_id:
                try:
                    refund_transaction = Transaction.objects.get(id=transaction_id)
                    refund_transaction.status = TransactionStatus.COMPLETED
                    refund_transaction.processed_at = now()
                    refund_transaction.stripe_transaction_id = refund_id
                    refund_transaction.save()

                    logger.info(
                        f"Refund transaction {transaction_id} completed successfully"
                    )

                    send_notification(
                        appointment.client,
                        "refund_approved",
                        f"Your refund of {appointment.total_price} USD for the cancelled appointment with {appointment.lawyer.vendor_profile.business_name} has been processed successfully.",
                    )

                except Transaction.DoesNotExist:
                    logger.warning(f"Refund transaction {transaction_id} not found")

            logger.info(
                f"Refund processed successfully for appointment {appointment_id}"
            )

    except Appointment.DoesNotExist:
        logger.error(f"Appointment {appointment_id} not found for refund success")


def handle_refund_failed(event):
    """Handle failed refund processing"""
    refund_data = event["data"]["object"]
    appointment_id = refund_data["metadata"].get("appointment_id")
    transaction_id = refund_data["metadata"].get("transaction_id")

    if not appointment_id:
        logger.warning("Refund failed but no appointment_id in metadata")
        return

    try:
        appointment = Appointment.objects.get(id=appointment_id)

        with transaction.atomic():
            # Update refund transaction status to failed
            if transaction_id:
                try:
                    refund_transaction = Transaction.objects.get(id=transaction_id)
                    refund_transaction.status = TransactionStatus.FAILED
                    refund_transaction.save(update_fields=["status"])

                    logger.error(f"Refund transaction {transaction_id} failed")

                    # Update appointment refund status back to pending for manual review
                    appointment.refund_status = RefundStatus.PENDING
                    appointment.refund_response = f"Automatic refund failed: {refund_data.get('failure_reason', 'Unknown error')}"
                    appointment.save(update_fields=["refund_status", "refund_response"])

                    # Send notification to admin about failed refund
                    logger.critical(
                        f"MANUAL INTERVENTION REQUIRED: Refund failed for appointment {appointment_id}"
                    )

                except Transaction.DoesNotExist:
                    logger.warning(f"Refund transaction {transaction_id} not found")

            logger.error(f"Refund failed for appointment {appointment_id}")

    except Appointment.DoesNotExist:
        logger.error(f"Appointment {appointment_id} not found for refund failure")


def handle_charge_disputed(event):
    """Handle charge dispute (chargeback) created by a customer"""
    dispute = event["data"]["object"]
    charge_id = dispute.get("charge")
    dispute_id = dispute.get("id")
    dispute_amount = dispute.get("amount", 0) / 100  # Convert cents to dollars

    logger.critical(
        f"DISPUTE OPENED: dispute {dispute_id} on charge {charge_id}, "
        f"amount ${dispute_amount:.2f}"
    )

    try:
        # Locate the appointment via the payment intent on the charge
        appointment = None
        if charge_id:
            try:
                charge = stripe.Charge.retrieve(charge_id)
                payment_intent_id = charge.get("payment_intent")
                if payment_intent_id:
                    appointment = Appointment.objects.filter(
                        stripe_payment_intent_id=payment_intent_id
                    ).first()
            except stripe.error.StripeError as e:
                logger.error(f"Could not retrieve charge {charge_id}: {e}")

        if appointment:
            with transaction.atomic():
                # Freeze any pending payment transaction to prevent fund release
                payment_transaction = Transaction.objects.filter(
                    appointment=appointment,
                    status=TransactionStatus.PENDING,
                ).first()
                if payment_transaction:
                    payment_transaction.status = TransactionStatus.FAILED
                    payment_transaction.save(update_fields=["status"])

            send_notification(
                appointment.lawyer.vendor_profile.user,
                "general",
                f"A dispute has been opened for appointment #{appointment.id}. "
                f"The disputed amount is ${dispute_amount:.2f} USD. "
                "Our team will review the case and contact you.",
            )
            send_notification(
                appointment.client,
                "general",
                f"Your dispute (ID: {dispute_id}) has been received and is under review.",
            )
            logger.critical(
                f"DISPUTE: linked to appointment {appointment.id}. "
                "Manual review required."
            )
        else:
            logger.critical(
                f"DISPUTE: could not link dispute {dispute_id} to an appointment. "
                "Manual review required."
            )

    except Exception as e:
        logger.error(f"Error handling dispute {dispute_id}: {e}")
