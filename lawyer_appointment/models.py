import uuid
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from lawyer.models import LawyerProfile, OfferingType
from users.models import User


class AppointmentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    CANCELLED = "cancelled", "Cancelled"
    COMPLETED = "completed", "Completed"
    RESCHEDULED = "rescheduled", "Rescheduled"
    INTERRUPTED = "interrupted", "Interrupted"
    FAILED = "failed", "Failed"
    NO_SHOW = "no_show", "No Show"


class RefundStatus(models.TextChoices):
    NONE = "none", "No Refund"
    PENDING = "pending", "Refund Pending"
    APPROVED = "approved", "Refund Approved"
    REJECTED = "rejected", "Refund Rejected"
    NOT_APPLICABLE = "not_applicable", "Not Applicable"


class FundsStatus(models.TextChoices):
    """Status of funds for an appointment"""

    NOT_APPLICABLE = "not_applicable", "Not Applicable"
    NO_PAYMENT = "no_payment", "No Payment"
    ESCROW = "escrow", "In Escrow"
    RELEASED = "released", "Released"
    CANCELLED = "cancelled", "Cancelled"
    UNKNOWN = "unknown", "Unknown"


class SessionStatus(models.TextChoices):
    NOT_STARTED = "not_started", "Not Started"
    ACTIVE = "active", "Active"
    ENDED = "ended", "Ended"


class ParticipantRole(models.TextChoices):
    LAWYER = "lawyer", "Lawyer"
    CLIENT = "client", "Client"


class Appointment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    client = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="appointments"
    )
    lawyer = models.ForeignKey(
        LawyerProfile, on_delete=models.CASCADE, related_name="appointments"
    )
    offering_type = models.ForeignKey(OfferingType, on_delete=models.CASCADE)

    # Appointment details
    notes = models.TextField(blank=True, null=True)
    start_datetime = models.DateTimeField(db_index=True)
    end_datetime = models.DateTimeField()

    # Status tracking
    status = models.CharField(
        max_length=20,
        choices=AppointmentStatus.choices,
        default=AppointmentStatus.PENDING,
        db_index=True,
    )

    # Cancellation tracking
    cancellation_reason = models.TextField(blank=True, null=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cancelled_appointments",
    )

    # Rescheduling tracking
    is_rescheduled = models.BooleanField(default=False)
    last_rescheduled_at = models.DateTimeField(null=True, blank=True)
    rescheduled_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rescheduled_appointments",
    )

    # Refunds (only applicable for paid appointments)
    refund_status = models.CharField(
        max_length=20,
        choices=RefundStatus.choices,
        default=RefundStatus.NONE,
        db_index=True,
    )
    refund_reason = models.TextField(blank=True, null=True)
    refund_requested_at = models.DateTimeField(null=True, blank=True)
    refund_response = models.TextField(blank=True, null=True)
    refund_processed_at = models.DateTimeField(null=True, blank=True)

    # Pricing information (stored for historical purposes)
    total_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Total price paid for this appointment",
    )
    commission_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Platform commission amount",
    )
    lawyer_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        help_text="Amount lawyer receives",
    )

    # Stripe payment integration
    stripe_payment_intent_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Stripe Payment Intent ID for paid appointments",
    )

    # Celery task management
    payment_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Celery task ID for payment timeout deletion",
    )

    reminder_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Celery task ID for appointment reminder",
    )

    auto_complete_task_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Celery task ID for auto-completion",
    )

    # Lifecycle timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["lawyer", "start_datetime", "status"]),
            models.Index(fields=["client", "start_datetime"]),
            models.Index(fields=["refund_status"]),
            models.Index(fields=["status", "start_datetime"]),
        ]
        ordering = ["-start_datetime"]

    def __str__(self):
        return f"Appointment {self.id} - {self.client} with {self.lawyer}"

    @property
    def duration_minutes(self):
        """Calculate duration in minutes"""
        if self.start_datetime and self.end_datetime:
            duration = self.end_datetime - self.start_datetime
            return int(duration.total_seconds() / 60)
        return 0

    @property
    def is_physical_appointment(self):
        """Check if this is a physical appointment (always free)"""
        return self.offering_type.type == OfferingType.PHYSICAL

    @property
    def is_paid_appointment(self):
        """Check if this is a paid appointment"""
        return not self.is_physical_appointment

    @property
    def can_be_rescheduled(self):
        """Check if appointment can be rescheduled"""
        if self.status not in [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]:
            return False

        # Check if we're past the lawyer's modification threshold
        threshold_hours = self.lawyer.cancellation_threshold_hours
        threshold_time = self.start_datetime - timedelta(hours=threshold_hours)

        return timezone.now() < threshold_time

    @property
    def can_be_cancelled(self):
        """Check if appointment can be cancelled"""
        if self.status not in [AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED]:
            return False

        # Check if we're past the lawyer's modification threshold
        threshold_hours = self.lawyer.cancellation_threshold_hours
        threshold_time = self.start_datetime - timedelta(hours=threshold_hours)

        return timezone.now() < threshold_time

    @property
    def time_until_appointment(self):
        """Get time remaining until appointment"""
        if self.start_datetime > timezone.now():
            return self.start_datetime - timezone.now()
        return timedelta(0)

    @property
    def modification_deadline(self):
        """Get the deadline for modifications (rescheduling/cancellation)"""
        threshold_hours = self.lawyer.cancellation_threshold_hours
        return self.start_datetime - timedelta(hours=threshold_hours)

    def get_reschedule_info(self):
        """Get basic reschedule information"""
        return {
            "is_rescheduled": self.is_rescheduled,
            "last_rescheduled_at": self.last_rescheduled_at,
            "rescheduled_by": self.rescheduled_by,
        }

    def calculate_refund_amount(self):
        """Calculate refund amount based on appointment type and timing"""
        if self.is_physical_appointment:
            return Decimal("0.00")

        # For paid appointments, calculate refund after deducting commission
        lawyer_amount = Decimal(str(self.lawyer_amount))
        commission_amount = (
            lawyer_amount
            * Decimal(str(settings.REFUND_COMMISSION_PERCENTAGE))
            / Decimal("100")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        refund_amount = lawyer_amount - commission_amount

        refund_amount = refund_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        return refund_amount

    def get_payment_transaction(self):
        """Get the payment transaction for this appointment"""
        from lawyer_wallet.models import Transaction, TransactionType

        return Transaction.objects.filter(
            appointment=self, transaction_type=TransactionType.PAYMENT
        ).first()

    def get_refund_transaction(self):
        """Get the refund transaction for this appointment"""
        from lawyer_wallet.models import Transaction, TransactionType

        return Transaction.objects.filter(
            appointment=self, transaction_type=TransactionType.REFUND
        ).first()

    def has_completed_payment(self):
        """Check if payment has been completed for this appointment"""
        if self.is_physical_appointment:
            return True  # Physical appointments don't require payment

        payment_transaction = self.get_payment_transaction()
        return (
            payment_transaction
            and payment_transaction.stripe_transaction_id is not None
        )

    def can_be_marked_completed(self):
        """Check if appointment can be marked as completed"""
        return (
            self.status == AppointmentStatus.CONFIRMED
            and self.end_datetime <= timezone.now()
            and self.has_completed_payment()
        )

    def get_funds_status(self):
        """Get the current status of funds for this appointment"""
        if self.is_physical_appointment:
            return FundsStatus.NOT_APPLICABLE

        payment_transaction = self.get_payment_transaction()
        if not payment_transaction:
            return FundsStatus.NO_PAYMENT

        from lawyer_wallet.models import TransactionStatus

        if payment_transaction.status == TransactionStatus.PENDING:
            if self.status == AppointmentStatus.COMPLETED:
                return FundsStatus.RELEASED
            else:
                return FundsStatus.ESCROW
        elif payment_transaction.status == TransactionStatus.COMPLETED:
            return FundsStatus.RELEASED
        elif payment_transaction.status == TransactionStatus.CANCELLED:
            return FundsStatus.CANCELLED
        else:
            return FundsStatus.UNKNOWN

    def get_funds_status_display(self):
        """Get the human-readable display name for funds status"""
        funds_status = self.get_funds_status()
        return dict(FundsStatus.choices).get(funds_status, funds_status)

    def mark_as_completed(self):
        """Mark appointment as completed and release funds"""
        if not self.can_be_marked_completed():
            raise ValidationError("Appointment cannot be marked as completed")

        from django.db import transaction

        from lawyer_wallet.models import TransactionStatus

        with transaction.atomic():
            self.status = AppointmentStatus.COMPLETED
            self.save(update_fields=["status", "updated_at"])

            # Release funds to lawyer if this is a paid appointment
            if self.is_paid_appointment:
                payment_transaction = self.get_payment_transaction()
                if (
                    payment_transaction
                    and payment_transaction.status == TransactionStatus.PENDING
                ):
                    payment_transaction.status = TransactionStatus.COMPLETED
                    payment_transaction.processed_at = timezone.now()
                    payment_transaction.save()

                    # Add funds to lawyer's wallet
                    if payment_transaction.wallet:
                        from lawyer_wallet.models import Wallet
                        wallet = Wallet.objects.select_for_update().get(
                            pk=payment_transaction.wallet.pk
                        )
                        wallet.balance += self.lawyer_amount
                        wallet.save(update_fields=["balance"])

    def mark_as_no_show(self):
        """Mark appointment as no show"""
        self.status = AppointmentStatus.NO_SHOW
        self.save(update_fields=["status", "updated_at"])

    def clean(self):
        """Validate appointment data"""
        if self.start_datetime and self.end_datetime:
            if self.end_datetime <= self.start_datetime:
                raise ValidationError("End time must be after start time")

        if self.is_physical_appointment:
            # Physical appointments should have zero prices
            if self.total_price != 0:
                raise ValidationError("Physical appointments must have zero price")

    def save(self, *args, **kwargs):
        # Set refund status for physical appointments
        if self.is_physical_appointment and self.refund_status == RefundStatus.NONE:
            self.refund_status = RefundStatus.NOT_APPLICABLE

        self.full_clean()
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Override delete to cancel related transactions"""
        from lawyer_wallet.models import Transaction, TransactionStatus, TransactionType

        # Cancel any pending transactions related to this appointment
        pending_transactions = Transaction.objects.filter(
            appointment=self, status=TransactionStatus.PENDING
        )

        for transaction in pending_transactions:
            transaction.status = TransactionStatus.CANCELLED
            transaction.save(update_fields=["status"])

        super().delete(*args, **kwargs)


class AppointmentSession(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    appointment = models.OneToOneField(
        Appointment, on_delete=models.CASCADE, related_name="session"
    )

    # Video/Audio session details (only for online appointments)
    agora_channel_name = models.CharField(
        max_length=255, unique=True, null=True, blank=True
    )
    agora_token = models.CharField(max_length=512, null=True, blank=True)

    # Session status
    status = models.CharField(
        max_length=20, choices=SessionStatus.choices, default=SessionStatus.NOT_STARTED
    )

    # Session timing
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    actual_duration_minutes = models.IntegerField(null=True, blank=True)

    # Session notes
    session_notes = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Session for {self.appointment.id} - {self.status}"

    @property
    def is_physical_session(self):
        """Check if this is a physical appointment session"""
        return self.appointment.is_physical_appointment

    @property
    def requires_video_setup(self):
        """Check if this session requires video/audio setup"""
        return not self.is_physical_session

    def calculate_actual_duration(self):
        """Calculate actual session duration"""
        if self.started_at and self.ended_at:
            duration = self.ended_at - self.started_at
            self.actual_duration_minutes = int(duration.total_seconds() / 60)
            self.save(update_fields=["actual_duration_minutes"])
        return self.actual_duration_minutes

    def generate_agora_channel_name(self):
        """Generate unique Agora channel name"""
        if not self.agora_channel_name:
            self.agora_channel_name = (
                f"appointment_{str(self.appointment.id).replace('-', '_')}"
            )
            self.save(update_fields=["agora_channel_name"])
        return self.agora_channel_name

    def get_session_info(self):
        """Get session information for API responses"""
        return {
            "id": str(self.id),
            "appointment_id": str(self.appointment.id),
            "status": self.status,
            "agora_channel_name": self.agora_channel_name,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "actual_duration_minutes": self.actual_duration_minutes,
            "is_physical_session": self.is_physical_session,
            "requires_video_setup": self.requires_video_setup,
        }


class AppointmentParticipant(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session = models.ForeignKey(
        AppointmentSession, on_delete=models.CASCADE, related_name="participants"
    )
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ParticipantRole.choices)

    # Participation tracking
    attended = models.BooleanField(default=False)
    joined_at = models.DateTimeField(null=True, blank=True)
    left_at = models.DateTimeField(null=True, blank=True)

    # Notes
    participant_notes = models.TextField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "user"], name="unique_session_user"
            ),
        ]

    def __str__(self):
        return f"{self.user} as {self.role} in session {self.session.id}"

    @property
    def session_duration_minutes(self):
        """Calculate how long this participant was in the session"""
        if self.joined_at and self.left_at:
            duration = self.left_at - self.joined_at
            return int(duration.total_seconds() / 60)
        return 0

    def get_participant_info(self):
        """Get participant information for API responses"""
        return {
            "id": str(self.id),
            "user_id": str(self.user.id),
            "role": self.role,
            "attended": self.attended,
            "joined_at": self.joined_at,
            "left_at": self.left_at,
            "session_duration_minutes": self.session_duration_minutes,
            "is_online": self.joined_at is not None and self.left_at is None,
        }
