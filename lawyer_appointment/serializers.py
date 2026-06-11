from datetime import timedelta

from django.utils import timezone
from rest_framework import serializers

from lawyer.models import LawyerProfile, OfferingType

from .models import (
    Appointment,
    AppointmentParticipant,
    AppointmentSession,
    AppointmentStatus,
    RefundStatus,
    SessionStatus,
)


class AppointmentCreateSerializer(serializers.Serializer):
    """Serializer for creating appointments with validation"""

    lawyer_id = serializers.UUIDField()
    offering_type_id = serializers.UUIDField()
    start_datetime = serializers.DateTimeField()
    duration_minutes = serializers.IntegerField()
    notes = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    idempotency_key = serializers.CharField(
        max_length=255,
        required=True,
        help_text="Unique key to prevent duplicate appointment creation",
    )

    def validate_lawyer_id(self, value):
        """Validate lawyer exists and is verified"""
        try:
            lawyer = LawyerProfile.objects.get(id=value)
            if lawyer.kyc_verification_status != "verified":
                raise serializers.ValidationError(
                    "This lawyer is not verified and cannot accept appointments"
                )
            return value
        except LawyerProfile.DoesNotExist:
            raise serializers.ValidationError("Lawyer not found")

    def validate_offering_type_id(self, value):
        """Validate offering type exists and is active"""
        try:
            offering_type = OfferingType.objects.select_related(
                "offering", "offering__lawyer_profile"
            ).get(id=value)

            if not offering_type.is_active:
                raise serializers.ValidationError("This offering type is not available")

            if not offering_type.offering.is_active:
                raise serializers.ValidationError("This offering is not available")

            return value
        except OfferingType.DoesNotExist:
            raise serializers.ValidationError("Offering type not found")

    def validate_start_datetime(self, value):
        """Validate start datetime is in the future"""
        if value <= timezone.now():
            raise serializers.ValidationError(
                "Appointment start time must be in the future"
            )

        # Validate not too far in the future (e.g., max 6 months)
        max_future_date = timezone.now() + timedelta(days=180)
        if value > max_future_date:
            raise serializers.ValidationError(
                "Cannot book appointments more than 6 months in advance"
            )

        # Validate minimum advance booking time (e.g., at least 1 hour ahead)
        min_advance_time = timezone.now() + timedelta(hours=1)
        if value < min_advance_time:
            raise serializers.ValidationError(
                "Appointments must be booked at least 1 hour in advance"
            )

        return value

    def validate_duration_minutes(self, value):
        """Validate duration is 30 or 60 minutes only"""
        if value not in [30, 60]:
            raise serializers.ValidationError(
                "Duration must be either 30 or 60 minutes"
            )
        return value

    def validate_idempotency_key(self, value):
        """Validate idempotency key format and uniqueness within reasonable time window"""
        if not value.strip():
            raise serializers.ValidationError("Idempotency key cannot be empty")

        # Check length
        if len(value) < 10:
            raise serializers.ValidationError(
                "Idempotency key must be at least 10 characters"
            )

        if len(value) > 255:
            raise serializers.ValidationError(
                "Idempotency key cannot exceed 255 characters"
            )

        return value.strip()

    def validate(self, attrs):
        """Cross-field validation"""
        lawyer_id = attrs["lawyer_id"]
        offering_type_id = attrs["offering_type_id"]
        start_datetime = attrs["start_datetime"]
        duration_minutes = attrs["duration_minutes"]

        # Calculate end_datetime for validation
        end_datetime = start_datetime + timedelta(minutes=duration_minutes)

        # Rule: Ensure end_datetime > start_datetime (explicit validation)
        if end_datetime <= start_datetime:
            raise serializers.ValidationError(
                {"duration_minutes": ["End time must be after start time"]}
            )

        # Validate lawyer consistency
        try:
            offering_type = OfferingType.objects.select_related(
                "offering", "offering__lawyer_profile"
            ).get(id=offering_type_id)

            if str(offering_type.offering.lawyer_profile.id) != str(lawyer_id):
                raise serializers.ValidationError(
                    {
                        "offering_type_id": [
                            "This offering type does not belong to the selected lawyer"
                        ]
                    }
                )
        except OfferingType.DoesNotExist:
            pass

        return attrs


class CancelAppointmentSerializer(serializers.Serializer):
    """Serializer for cancelling appointments"""

    cancellation_reason = serializers.CharField(
        max_length=1000, required=False, allow_blank=True
    )
    refund_idempotency_key = serializers.CharField(
        max_length=255,
        required=False,
        help_text="Required for cancellations eligible for refund to prevent duplicate refund transactions",
    )

    def validate_refund_idempotency_key(self, value):
        """Validate refund idempotency key format if provided"""
        if value:
            if not value.strip():
                raise serializers.ValidationError(
                    "Refund idempotency key cannot be empty"
                )

            if len(value) < 10:
                raise serializers.ValidationError(
                    "Refund idempotency key must be at least 10 characters"
                )

            if len(value) > 255:
                raise serializers.ValidationError(
                    "Refund idempotency key cannot exceed 255 characters"
                )

            return value.strip()
        return value

    def validate(self, attrs):
        """Validate cancellation is allowed"""
        appointment = self.context.get("appointment")
        user = self.context.get("user")

        if not appointment:
            raise serializers.ValidationError("Appointment not found")

        # Check if appointment can be cancelled
        if not appointment.can_be_cancelled:
            raise serializers.ValidationError(
                f"Appointment cannot be cancelled. Modification deadline was "
                f"{appointment.modification_deadline.strftime('%Y-%m-%d %H:%M')}"
            )

        # Only clients can cancel paid appointments
        if appointment.is_paid_appointment and user != appointment.client:
            raise serializers.ValidationError(
                "Only clients can cancel paid appointments"
            )

        # Both client and lawyer can cancel physical appointments
        if appointment.is_physical_appointment:
            if (
                user != appointment.client
                and user != appointment.lawyer.vendor_profile.user
            ):
                raise serializers.ValidationError(
                    "You don't have permission to cancel this appointment"
                )

        # Check appointment status
        if appointment.status not in [
            AppointmentStatus.PENDING,
            AppointmentStatus.CONFIRMED,
        ]:
            raise serializers.ValidationError(
                f"Cannot cancel appointment with status: {appointment.get_status_display()}"
            )

        return attrs


class RescheduleAppointmentSerializer(serializers.Serializer):
    """Serializer for rescheduling appointments"""

    new_start_datetime = serializers.DateTimeField()
    reschedule_reason = serializers.CharField(
        max_length=1000, required=False, allow_blank=True
    )

    def validate_new_start_datetime(self, value):
        """Validate new start datetime"""
        if value <= timezone.now():
            raise serializers.ValidationError(
                "New appointment time must be in the future"
            )

        # Validate not too far in the future
        max_future_date = timezone.now() + timedelta(days=180)
        if value > max_future_date:
            raise serializers.ValidationError(
                "Cannot reschedule appointments more than 6 months in advance"
            )

        # Validate minimum advance booking time
        min_advance_time = timezone.now() + timedelta(hours=1)
        if value < min_advance_time:
            raise serializers.ValidationError(
                "Rescheduled appointments must be at least 1 hour in advance"
            )

        return value

    def validate(self, attrs):
        """Validate rescheduling is allowed"""
        appointment = self.context.get("appointment")
        user = self.context.get("user")

        if not appointment:
            raise serializers.ValidationError("Appointment not found")

        # Check if appointment can be rescheduled
        if not appointment.can_be_rescheduled:
            raise serializers.ValidationError(
                f"Appointment cannot be rescheduled. Modification deadline was "
                f"{appointment.modification_deadline.strftime('%Y-%m-%d %H:%M')}"
            )

        # Check if user has permission to reschedule
        if (
            user != appointment.client
            and user != appointment.lawyer.vendor_profile.user
        ):
            raise serializers.ValidationError(
                "You don't have permission to reschedule this appointment"
            )

        # Validate the new time doesn't conflict with existing appointments
        new_start = attrs["new_start_datetime"]
        duration = timedelta(minutes=appointment.duration_minutes)
        new_end = new_start + duration

        # Check lawyer availability
        appointment_date = new_start.date()
        appointment_start_time = new_start.time()
        appointment_end_time = new_end.time()

        if not appointment.lawyer.is_available_at_time_with_offering(
            appointment_date,
            appointment_start_time,
            appointment_end_time,
            appointment.offering_type.offering.id,
        ):
            raise serializers.ValidationError(
                "Lawyer is not available at the new requested time"
            )

        # Check for conflicts (excluding current appointment)
        lawyer_conflicts = Appointment.objects.filter(
            lawyer=appointment.lawyer,
            start_datetime__lt=new_end,
            end_datetime__gt=new_start,
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        ).exclude(id=appointment.id)

        if lawyer_conflicts.exists():
            raise serializers.ValidationError(
                "Lawyer already has another appointment at the requested time"
            )

        # Check client conflicts (excluding current appointment)
        client_conflicts = Appointment.objects.filter(
            client=appointment.client,
            start_datetime__lt=new_end,
            end_datetime__gt=new_start,
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        ).exclude(id=appointment.id)

        if client_conflicts.exists():
            raise serializers.ValidationError(
                "You already have another appointment at the requested time"
            )

        return attrs


class RefundStatusSerializer(serializers.ModelSerializer):
    """Serializer for refund status information"""

    can_request_refund = serializers.SerializerMethodField()
    refund_deadline = serializers.SerializerMethodField()
    estimated_refund_amount = serializers.SerializerMethodField()
    refund_policy_message = serializers.SerializerMethodField()
    refund_status_display = serializers.CharField(
        source="get_refund_status_display", read_only=True
    )

    class Meta:
        model = Appointment
        fields = [
            "id",
            "status",
            "refund_status",
            "refund_status_display",
            "refund_reason",
            "refund_requested_at",
            "refund_response",
            "refund_processed_at",
            "total_price",
            "can_request_refund",
            "refund_deadline",
            "estimated_refund_amount",
            "refund_policy_message",
        ]

    def get_can_request_refund(self, obj):
        """Check if user can request a refund"""
        # Physical appointments cannot be refunded (always free)
        if obj.is_physical_appointment:
            return False

        # Only cancelled appointments can have refunds
        if obj.status != AppointmentStatus.CANCELLED:
            return False

        # Refund must not already be processed
        if obj.refund_status in [RefundStatus.APPROVED, RefundStatus.REJECTED]:
            return False

        # Check if cancellation was within threshold
        if obj.cancelled_at and obj.start_datetime:
            threshold_hours = obj.lawyer.cancellation_threshold_hours
            threshold_time = obj.start_datetime - timedelta(hours=threshold_hours)
            return obj.cancelled_at <= threshold_time

        return False

    def get_refund_deadline(self, obj):
        """Get the deadline for refund eligibility"""
        if obj.start_datetime:
            threshold_hours = obj.lawyer.cancellation_threshold_hours
            return obj.start_datetime - timedelta(hours=threshold_hours)
        return None

    def get_estimated_refund_amount(self, obj):
        """Get estimated refund amount"""
        if obj.is_physical_appointment:
            return 0.00

        if obj.status == AppointmentStatus.CANCELLED and self.get_can_request_refund(
            obj
        ):
            return float(obj.total_price)

        return 0.00

    def get_refund_policy_message(self, obj):
        """Get refund policy message"""
        if obj.is_physical_appointment:
            return "Physical appointments are free and do not require refunds."

        threshold_hours = obj.lawyer.cancellation_threshold_hours

        if obj.status != AppointmentStatus.CANCELLED:
            return f"Refunds are only available for cancelled appointments that are cancelled at least {threshold_hours} hours before the scheduled time."

        if obj.refund_status == RefundStatus.APPROVED:
            return "Your refund has been approved and will be processed within 1-2 business days."

        if obj.refund_status == RefundStatus.REJECTED:
            return f"Your refund request was rejected. Reason: {obj.refund_response or 'Not specified'}"

        if obj.refund_status == RefundStatus.PENDING:
            return "Your refund request is being reviewed by our team."

        if self.get_can_request_refund(obj):
            return f"You are eligible for a full refund since you cancelled at least {threshold_hours} hours before the appointment."

        return f"No refund available. Cancellations must be made at least {threshold_hours} hours before the appointment time."


class AppointmentSerializer(serializers.ModelSerializer):
    """Complete serializer for appointment responses"""

    # Related data
    lawyer_name = serializers.CharField(
        source="lawyer.vendor_profile.business_name", read_only=True
    )
    lawyer_id = serializers.UUIDField(source="lawyer.id", read_only=True)
    client_name = serializers.CharField(source="client.get_full_name", read_only=True)
    client_email = serializers.CharField(source="client.email", read_only=True)

    # Offering details
    offering_name = serializers.CharField(
        source="offering_type.offering.name", read_only=True
    )
    offering_type_display = serializers.CharField(
        source="offering_type.get_type_display", read_only=True
    )
    offering_type_name = serializers.CharField(
        source="offering_type.type", read_only=True
    )

    # Calculated fields
    duration_minutes = serializers.ReadOnlyField()
    is_physical_appointment = serializers.ReadOnlyField()
    is_paid_appointment = serializers.ReadOnlyField()
    can_be_rescheduled = serializers.ReadOnlyField()
    can_be_cancelled = serializers.ReadOnlyField()
    modification_deadline = serializers.ReadOnlyField()
    time_until_appointment = serializers.ReadOnlyField()

    # Pricing info
    calculated_price = serializers.SerializerMethodField()
    price_breakdown = serializers.SerializerMethodField()

    # Transaction info
    funds_status = serializers.SerializerMethodField()
    payment_transaction_id = serializers.SerializerMethodField()
    refund_transaction_id = serializers.SerializerMethodField()

    # Reschedule info
    is_rescheduled = serializers.ReadOnlyField()
    rescheduled_by_name = serializers.CharField(
        source="rescheduled_by.get_full_name", read_only=True
    )

    # Cancellation info
    cancelled_by_name = serializers.CharField(
        source="cancelled_by.get_full_name", read_only=True
    )
    refund_status_display = serializers.CharField(
        source="get_refund_status_display", read_only=True
    )

    class Meta:
        model = Appointment
        fields = [
            "id",
            "client",
            "client_name",
            "client_email",
            "lawyer",
            "lawyer_id",
            "lawyer_name",
            "offering_type",
            "offering_name",
            "offering_type_display",
            "offering_type_name",
            "notes",
            "start_datetime",
            "end_datetime",
            "duration_minutes",
            "status",
            "is_physical_appointment",
            "is_paid_appointment",
            "can_be_rescheduled",
            "can_be_cancelled",
            "modification_deadline",
            "time_until_appointment",
            "calculated_price",
            "price_breakdown",
            "total_price",
            "commission_amount",
            "lawyer_amount",
            "cancellation_reason",
            "cancelled_at",
            "cancelled_by",
            "cancelled_by_name",
            "refund_status",
            "refund_status_display",
            "refund_reason",
            "refund_requested_at",
            "refund_response",
            "refund_processed_at",
            "is_rescheduled",
            "last_rescheduled_at",
            "rescheduled_by",
            "rescheduled_by_name",
            "funds_status",
            "payment_transaction_id",
            "refund_transaction_id",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "cancelled_at",
            "refund_requested_at",
            "refund_processed_at",
            "last_rescheduled_at",
        ]

    def get_calculated_price(self, obj):
        """Get the calculated price for this appointment"""
        return obj.offering_type.get_price_for_duration(obj.duration_minutes)

    def get_price_breakdown(self, obj):
        """Get complete price breakdown for this appointment"""
        return obj.offering_type.get_price_breakdown(obj.duration_minutes)

    def get_funds_status(self, obj):
        """Get the current status of funds for this appointment"""
        return obj.get_funds_status()

    def get_payment_transaction_id(self, obj):
        """Get payment transaction ID if exists"""
        payment_transaction = obj.get_payment_transaction()
        return str(payment_transaction.id) if payment_transaction else None

    def get_refund_transaction_id(self, obj):
        """Get refund transaction ID if exists"""
        refund_transaction = obj.get_refund_transaction()
        return str(refund_transaction.id) if refund_transaction else None


class AppointmentListSerializer(serializers.ModelSerializer):
    """Simplified serializer for appointment lists"""

    lawyer_name = serializers.CharField(
        source="lawyer.vendor_profile.business_name", read_only=True
    )
    client_name = serializers.CharField(source="client.get_full_name", read_only=True)
    offering_type_display = serializers.CharField(
        source="offering_type.get_type_display", read_only=True
    )
    duration_minutes = serializers.ReadOnlyField()
    is_physical_appointment = serializers.ReadOnlyField()
    is_rescheduled = serializers.ReadOnlyField()
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    funds_status = serializers.SerializerMethodField()

    class Meta:
        model = Appointment
        fields = [
            "id",
            "lawyer_name",
            "client_name",
            "offering_type_display",
            "start_datetime",
            "end_datetime",
            "duration_minutes",
            "status",
            "status_display",
            "is_physical_appointment",
            "is_rescheduled",
            "total_price",
            "funds_status",
            "created_at",
        ]

    def get_funds_status(self, obj):
        """Get the current status of funds for this appointment"""
        return obj.get_funds_status()


# Stats and Analytics Serializers
class AppointmentStatsSerializer(serializers.Serializer):
    """Serializer for appointment statistics"""

    total_appointments = serializers.IntegerField()
    pending_appointments = serializers.IntegerField()
    confirmed_appointments = serializers.IntegerField()
    completed_appointments = serializers.IntegerField()
    cancelled_appointments = serializers.IntegerField()
    rescheduled_appointments = serializers.IntegerField()

    physical_appointments = serializers.IntegerField()
    audio_appointments = serializers.IntegerField()
    video_appointments = serializers.IntegerField()

    total_revenue = serializers.DecimalField(max_digits=10, decimal_places=2)
    total_commission = serializers.DecimalField(max_digits=10, decimal_places=2)

    upcoming_appointments = serializers.IntegerField()
    appointments_today = serializers.IntegerField()
    appointments_this_week = serializers.IntegerField()
    appointments_this_month = serializers.IntegerField()


class SessionJoinSerializer(serializers.Serializer):
    """Serializer for joining a session"""

    user_role = serializers.ChoiceField(
        choices=[("client", "Client"), ("lawyer", "Lawyer")]
    )


class SessionLeaveSerializer(serializers.Serializer):
    """Serializer for leaving a session"""

    reason = serializers.ChoiceField(
        choices=[
            ("user_left", "User Left"),
            ("connection_lost", "Connection Lost"),
            ("ended_call", "Ended Call"),
        ],
        default="user_left",
    )


class SessionEndSerializer(serializers.Serializer):
    """Serializer for ending a session"""

    ended_by = serializers.ChoiceField(
        choices=[("lawyer", "Lawyer"), ("client", "Client"), ("system", "System")]
    )
    reason = serializers.ChoiceField(
        choices=[
            ("completed", "Completed"),
            ("cancelled", "Cancelled"),
            ("technical_issue", "Technical Issue"),
        ],
        default="completed",
    )


class AppointmentParticipantSerializer(serializers.ModelSerializer):
    """Serializer for appointment participants"""

    user_name = serializers.CharField(source="user.get_full_name", read_only=True)
    is_online = serializers.SerializerMethodField()

    class Meta:
        model = AppointmentParticipant
        fields = [
            "id",
            "user_id",
            "user_name",
            "role",
            "attended",
            "joined_at",
            "left_at",
            "session_duration_minutes",
            "is_online",
        ]

    def get_is_online(self, obj):
        """Check if participant is currently online"""
        return obj.joined_at is not None and obj.left_at is None


class AppointmentSessionSerializer(serializers.ModelSerializer):
    """Serializer for appointment sessions"""

    participants = AppointmentParticipantSerializer(many=True, read_only=True)
    appointment_details = serializers.SerializerMethodField()
    participants_online = serializers.SerializerMethodField()
    session_duration_minutes = serializers.SerializerMethodField()

    class Meta:
        model = AppointmentSession
        fields = [
            "id",
            "appointment",
            "agora_channel_name",
            "status",
            "started_at",
            "ended_at",
            "actual_duration_minutes",
            "is_physical_session",
            "requires_video_setup",
            "participants",
            "appointment_details",
            "participants_online",
            "session_duration_minutes",
        ]

    def get_appointment_details(self, obj):
        """Get relevant appointment details"""
        return {
            "start_datetime": obj.appointment.start_datetime,
            "end_datetime": obj.appointment.end_datetime,
            "status": obj.appointment.status,
            "duration_minutes": obj.appointment.duration_minutes,
        }

    def get_participants_online(self, obj):
        """Count online participants"""
        return obj.participants.filter(
            joined_at__isnull=False, left_at__isnull=True
        ).count()

    def get_session_duration_minutes(self, obj):
        """Calculate current session duration"""
        if obj.started_at and obj.status == SessionStatus.ACTIVE:
            from django.utils import timezone

            duration = timezone.now() - obj.started_at
            return int(duration.total_seconds() / 60)
        return obj.actual_duration_minutes


class SessionStatusSerializer(serializers.Serializer):
    """Serializer for session status response"""

    session_status = serializers.CharField()
    participants_online = serializers.IntegerField()
    participants = AppointmentParticipantSerializer(many=True)
    session_duration_minutes = serializers.IntegerField(allow_null=True)
    last_updated = serializers.DateTimeField()
