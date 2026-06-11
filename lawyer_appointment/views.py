from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

import stripe
from django.conf import settings
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.serializers import ValidationError

from lawyer.models import LawyerProfile, OfferingType
from lawyer_appointment.http_status import ConflictError
from lawyer_wallet.models import Transaction, TransactionStatus, TransactionType, Wallet

from .agora_utils import AgoraTokenGenerator
from .models import (
    Appointment,
    AppointmentParticipant,
    AppointmentSession,
    AppointmentStatus,
    ParticipantRole,
    RefundStatus,
    SessionStatus,
)
from .serializers import (
    AppointmentCreateSerializer,
    AppointmentListSerializer,
    AppointmentSerializer,
    AppointmentSessionSerializer,
    AppointmentStatsSerializer,
    CancelAppointmentSerializer,
    RefundStatusSerializer,
    RescheduleAppointmentSerializer,
    SessionEndSerializer,
    SessionJoinSerializer,
    SessionLeaveSerializer,
)
from .tasks import delete_unpaid_appointment, send_appointment_reminder


class CreateAppointmentView(generics.CreateAPIView):
    """Create a new appointment with comprehensive validation"""

    serializer_class = AppointmentCreateSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        """Create appointment with all validation rules and atomic transaction"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Extract idempotency key from request data
        idempotency_key = request.data.get("idempotency_key")
        if not idempotency_key:
            return Response(
                {"error": "idempotency_key is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Check if transaction already exists with this idempotency key
        existing_transaction = Transaction.objects.filter(
            idempotency_key=idempotency_key
        ).first()

        if existing_transaction:
            # Return existing appointment data if transaction already exists
            if existing_transaction.appointment:
                response_serializer = AppointmentSerializer(
                    existing_transaction.appointment
                )
                return Response(
                    {
                        "appointment": response_serializer.data,
                        "message": "Appointment already exists for this idempotency key",
                        "is_duplicate": True,
                    },
                    status=status.HTTP_200_OK,
                )

        try:
            with transaction.atomic():
                appointment = self.perform_create_with_validation(serializer)
                response_serializer = AppointmentSerializer(appointment)
                response_data = {
                    "appointment": response_serializer.data,
                    "message": "Appointment created successfully.",
                }

                if appointment.is_paid_appointment:
                    # Create pending payment transaction first
                    payment_transaction = self._create_payment_transaction(
                        appointment, idempotency_key
                    )

                    # Create Stripe Payment Intent
                    payment_intent = self._create_payment_intent(
                        appointment, payment_transaction, idempotency_key
                    )

                    # Schedule deletion task for 10 minutes
                    delete_task = delete_unpaid_appointment.apply_async(
                        args=[str(appointment.id)],
                        countdown=settings.APPOINTMENT_EXPIRATION_MINUTES * 60,
                    )

                    # Store task ID for potential cancellation
                    appointment.payment_task_id = delete_task.id
                    appointment.save(update_fields=["payment_task_id"])

                    response_data.update(
                        {
                            "client_secret": payment_intent.client_secret,
                            "payment_deadline": (
                                timezone.now()
                                + timedelta(
                                    minutes=settings.APPOINTMENT_EXPIRATION_MINUTES
                                )
                            ).isoformat(),
                            "requires_payment": True,
                            "transaction_id": str(payment_transaction.id),
                            "message": response_data["message"]
                            + f" Please complete payment within {settings.APPOINTMENT_EXPIRATION_MINUTES} minutes.",
                        }
                    )
                else:
                    # Physical appointment - no payment required
                    appointment.status = AppointmentStatus.CONFIRMED
                    appointment.save(update_fields=["status"])

                    # Schedule reminder for 24 hours before
                    self._schedule_appointment_reminder(appointment)

                    response_data.update(
                        {
                            "requires_payment": False,
                            "message": response_data["message"]
                            + " This is a physical appointment (no payment required).",
                        }
                    )

                return Response(response_data, status=status.HTTP_201_CREATED)

        except ValidationError as e:
            return Response(
                {"error": "Validation failed", "details": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            return Response(
                {"error": "Appointment creation failed", "details": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _create_payment_transaction(self, appointment, idempotency_key):
        """Create a pending payment transaction for the appointment"""
        # Get or create lawyer's wallet
        wallet, created = Wallet.objects.get_or_create(
            lawyer=appointment.lawyer, defaults={"balance": Decimal("0.00")}
        )

        payment_transaction = Transaction.objects.create(
            wallet=wallet,
            lawyer=appointment.lawyer,
            client=appointment.client,
            appointment=appointment,
            title=f"Payment for appointment with {appointment.lawyer.vendor_profile.business_name}",
            amount=appointment.total_price,
            transaction_type=TransactionType.PAYMENT,
            status=TransactionStatus.PENDING,
            idempotency_key=idempotency_key,
        )

        return payment_transaction

    def _create_payment_intent(self, appointment, payment_transaction, idempotency_key):
        """Create Stripe Payment Intent for the appointment"""
        try:
            stripe.api_key = settings.STRIPE_SECRET_KEY

            # Use currency from settings
            currency = getattr(settings, "STRIPE_CURRENCY", "usd")

            payment_intent = stripe.PaymentIntent.create(
                amount=int(appointment.total_price * 100),
                currency=currency,
                idempotency_key=idempotency_key,
                metadata={
                    "appointment_id": str(appointment.id),
                    "transaction_id": str(payment_transaction.id),
                    "client_id": str(appointment.client.id),
                    "lawyer_id": str(appointment.lawyer.id),
                },
                automatic_payment_methods={"enabled": True},
            )

            # Store payment intent ID in both appointment and transaction
            appointment.stripe_payment_intent_id = payment_intent.id
            appointment.save(update_fields=["stripe_payment_intent_id"])

            payment_transaction.stripe_transaction_id = payment_intent.id
            payment_transaction.save(update_fields=["stripe_transaction_id"])

            return payment_intent

        except stripe.error.StripeError as e:
            raise ValidationError(f"Payment setup failed: {str(e)}")

    def _schedule_appointment_reminder(self, appointment):
        """Schedule reminder task 24 hours before appointment"""
        reminder_time = appointment.start_datetime - timedelta(hours=24)

        # Only schedule if appointment is more than 24 hours away
        if reminder_time > timezone.now():
            reminder_task = send_appointment_reminder.apply_async(
                args=[str(appointment.id)], eta=reminder_time
            )

            # Store task ID for potential cancellation
            appointment.reminder_task_id = reminder_task.id
            appointment.save(update_fields=["reminder_task_id"])

    def perform_create_with_validation(self, serializer):
        """Perform appointment creation with all validation rules"""
        validated_data = serializer.validated_data

        # Extract data
        client = self.request.user
        lawyer_id = validated_data["lawyer_id"]
        offering_type_id = validated_data["offering_type_id"]
        start_datetime = validated_data["start_datetime"]
        duration_minutes = validated_data["duration_minutes"]
        notes = validated_data.get("notes", "")

        # Calculate end datetime
        end_datetime = start_datetime + timedelta(minutes=duration_minutes)

        # Get models with select_for_update to prevent race conditions
        lawyer = LawyerProfile.objects.select_for_update().get(id=lawyer_id)
        offering_type = (
            OfferingType.objects.select_for_update()
            .select_related("offering", "offering__lawyer_profile")
            .get(id=offering_type_id)
        )

        # Validate all booking rules
        self._validate_booking_rules(
            client=client,
            lawyer=lawyer,
            offering_type=offering_type,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            duration_minutes=duration_minutes,
        )

        # Calculate pricing
        price_breakdown = offering_type.get_price_breakdown(duration_minutes)

        # Round all decimal values to 2 places
        total_price = Decimal(str(price_breakdown["total_price"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        commission_amount = Decimal(str(price_breakdown["commission_amount"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        lawyer_amount = Decimal(str(price_breakdown["lawyer_amount"])).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Create the appointment
        appointment = Appointment.objects.create(
            client=client,
            lawyer=lawyer,
            offering_type=offering_type,
            notes=notes,
            start_datetime=start_datetime,
            end_datetime=end_datetime,
            status=AppointmentStatus.PENDING,
            total_price=total_price,
            commission_amount=commission_amount,
            lawyer_amount=lawyer_amount,
        )

        return appointment

    def _validate_booking_rules(
        self,
        client,
        lawyer,
        offering_type,
        start_datetime,
        end_datetime,
        duration_minutes,
    ):
        """Validate all appointment booking rules"""
        # Rule 1: Future appointments only
        if start_datetime <= timezone.now():
            raise ValidationError(
                {"start_datetime": ["Cannot book appointments in the past"]}
            )

        # Rule 2: Fixed durations only (30 or 60 minutes)
        if duration_minutes not in [30, 60]:
            raise ValidationError(
                {"duration_minutes": ["Only 30 or 60 minute appointments are allowed"]}
            )

        # Rule 3: Only available offering types
        if not offering_type.is_active:
            raise ValidationError(
                {"offering_type": ["This offering type is not available"]}
            )

        if not offering_type.offering.is_active:
            raise ValidationError({"offering": ["This offering is not available"]})

        # Rule 4: Verify offering type belongs to the specified lawyer
        if offering_type.offering.lawyer_profile.id != lawyer.id:
            raise ValidationError(
                {
                    "offering_type": [
                        "This offering type does not belong to the selected lawyer"
                    ]
                }
            )

        # Rule 5: Check lawyer availability
        appointment_date = start_datetime.date()
        appointment_start_time = start_datetime.time()
        appointment_end_time = end_datetime.time()

        if not lawyer.is_available_at_time_with_offering(
            appointment_date,
            appointment_start_time,
            appointment_end_time,
            offering_type.offering.id,
        ):
            raise ValidationError(
                {
                    "start_datetime": [
                        "Lawyer is not available at the requested time for this offering."
                    ]
                }
            )

        # Rule 6: No overlapping appointments (Lawyer)
        lawyer_conflicts = Appointment.objects.filter(
            lawyer=lawyer,
            start_datetime__lt=end_datetime,
            end_datetime__gt=start_datetime,
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        )

        if lawyer_conflicts.exists():
            conflicting_appointment = lawyer_conflicts.first()
            raise ConflictError(
                {
                    "start_datetime": [
                        f"Lawyer already has an appointment from "
                        f'{conflicting_appointment.start_datetime.strftime("%H:%M")} to '
                        f'{conflicting_appointment.end_datetime.strftime("%H:%M")} on this date'
                    ]
                }
            )

        # Rule 7: Client cannot double-book
        client_conflicts = Appointment.objects.filter(
            client=client,
            start_datetime__lt=end_datetime,
            end_datetime__gt=start_datetime,
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        )

        if client_conflicts.exists():
            conflicting_appointment = client_conflicts.first()
            raise ValidationError(
                {
                    "start_datetime": [
                        f"You already have an appointment from "
                        f'{conflicting_appointment.start_datetime.strftime("%H:%M")} to '
                        f'{conflicting_appointment.end_datetime.strftime("%H:%M")} on this date'
                    ]
                }
            )

        # Rule 8: Validate lawyer is verified and active
        if lawyer.kyc_verification_status != "verified":
            raise ValidationError(
                {
                    "lawyer": [
                        "This lawyer is not verified and cannot accept appointments"
                    ]
                }
            )

        # Rule 9: Lawyer cannot book appointments with themselves
        if hasattr(client, "lawyer_profile") and client.lawyer_profile.id == lawyer.id:
            raise ValidationError(
                {"lawyer": ["You cannot book an appointment with yourself"]}
            )

        # Alternative check if lawyer profile is linked differently
        try:
            client_lawyer_profile = LawyerProfile.objects.get(
                vendor_profile__user=client
            )
            if client_lawyer_profile.id == lawyer.id:
                raise ValidationError(
                    {"lawyer": ["You cannot book an appointment with yourself"]}
                )
        except LawyerProfile.DoesNotExist:
            pass


class CancelAppointmentView(generics.UpdateAPIView):
    """Cancel an existing appointment"""

    serializer_class = CancelAppointmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"
    lookup_url_kwarg = "appointment_id"

    def get_queryset(self):
        """Filter appointments that can be cancelled"""
        user = self.request.user
        return Appointment.objects.filter(
            Q(client=user) | Q(lawyer__vendor_profile__user=user),
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        ).select_related(
            "client",
            "lawyer",
            "lawyer__vendor_profile",
            "offering_type",
            "offering_type__offering",
        )

    def update(self, request, *args, **kwargs):
        """Cancel the appointment"""
        appointment = self.get_object()
        serializer = self.get_serializer(
            data=request.data,
            context={"appointment": appointment, "user": request.user},
        )
        serializer.is_valid(raise_exception=True)

        # Extract refund idempotency key from request if provided
        refund_idempotency_key = request.data.get("refund_idempotency_key")

        try:
            with transaction.atomic():
                cancelled_appointment = self.perform_cancellation(
                    appointment, serializer.validated_data
                )
                response_serializer = AppointmentSerializer(cancelled_appointment)
                response_data = {
                    "appointment": response_serializer.data,
                    "message": "Appointment cancelled successfully",
                }

                # Handle refund logic for paid appointments
                if cancelled_appointment.is_paid_appointment:
                    refund_eligible = self._check_refund_eligibility(
                        cancelled_appointment
                    )

                    if refund_eligible:
                        if not refund_idempotency_key:
                            return Response(
                                {
                                    "error": "refund_idempotency_key is required for refund eligible cancellations"
                                },
                                status=status.HTTP_400_BAD_REQUEST,
                            )

                        # Check for duplicate refund request
                        existing_refund = Transaction.objects.filter(
                            idempotency_key=refund_idempotency_key,
                            transaction_type=TransactionType.REFUND,
                        ).first()

                        if existing_refund:
                            response_data["refund_status"] = "already_requested"
                            response_data["refund_message"] = (
                                "Refund request already exists for this cancellation"
                            )
                        else:
                            response_data["refund_status"] = "eligible"
                            response_data["refund_message"] = (
                                "You are eligible for a full refund. A refund request has been automatically created and will be processed within 1-2 business days."
                            )
                            # Auto-create refund request and transaction
                            self._create_refund_request_and_transaction(
                                cancelled_appointment, refund_idempotency_key
                            )
                    else:
                        response_data["refund_status"] = "not_eligible"
                        response_data["refund_message"] = (
                            f"No refund available. Cancellations must be made at least {cancelled_appointment.lawyer.cancellation_threshold_hours} hours before the appointment time."
                        )
                        # Cancel the payment transaction (no refund)
                        self._cancel_payment_transaction(cancelled_appointment)
                else:
                    response_data["refund_status"] = "not_applicable"
                    response_data["refund_message"] = (
                        "This was a physical appointment (free), so no refund is applicable."
                    )

                return Response(response_data)

        except ValidationError as e:
            return Response(
                {"error": "Cancellation failed", "details": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def perform_cancellation(self, appointment, validated_data):
        """Perform the cancellation operation"""
        user = self.request.user
        cancellation_reason = validated_data.get("cancellation_reason", "")

        # Update appointment status
        appointment.status = AppointmentStatus.CANCELLED
        appointment.cancellation_reason = cancellation_reason
        appointment.cancelled_at = timezone.now()
        appointment.cancelled_by = user
        appointment.save()

        return appointment

    def _check_refund_eligibility(self, appointment):
        """Check if the cancelled appointment is eligible for refund"""
        if appointment.is_physical_appointment:
            return False

        if not appointment.cancelled_at or not appointment.start_datetime:
            return False

        threshold_hours = appointment.lawyer.cancellation_threshold_hours
        threshold_time = appointment.start_datetime - timedelta(hours=threshold_hours)
        return appointment.cancelled_at <= threshold_time

    def _cancel_payment_transaction(self, appointment):
        """Cancel the payment transaction without refund"""
        payment_transaction = Transaction.objects.filter(
            appointment=appointment, transaction_type=TransactionType.PAYMENT
        ).first()

        if payment_transaction:
            payment_transaction.status = TransactionStatus.CANCELLED
            payment_transaction.save(update_fields=["status"])

    def _create_refund_request_and_transaction(
        self, appointment, refund_idempotency_key
    ):
        """Create refund request and corresponding transaction"""
        # Update appointment refund status
        appointment.refund_status = RefundStatus.PENDING
        appointment.refund_reason = "Automatic refund request for timely cancellation"
        appointment.refund_requested_at = timezone.now()
        appointment.save(
            update_fields=["refund_status", "refund_reason", "refund_requested_at"]
        )

        # Cancel the original payment transaction
        self._cancel_payment_transaction(appointment)

        # Create refund transaction with provided idempotency key
        refund_transaction = Transaction.objects.create(
            wallet=None,
            lawyer=appointment.lawyer,
            client=appointment.client,
            appointment=appointment,
            title=f"Refund for cancelled appointment with {appointment.lawyer.vendor_profile.business_name}",
            amount=appointment.total_price,
            transaction_type=TransactionType.REFUND,
            status=TransactionStatus.PENDING,
            idempotency_key=refund_idempotency_key,
        )

        return refund_transaction


class AppointmentDetailView(generics.RetrieveAPIView):
    """Retrieve appointment details"""

    serializer_class = AppointmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"
    lookup_url_kwarg = "appointment_id"

    def get_queryset(self):
        """Filter appointments based on user role"""
        user = self.request.user
        return Appointment.objects.filter(
            Q(client=user) | Q(lawyer__vendor_profile__user=user)
        ).select_related(
            "client",
            "lawyer",
            "lawyer__vendor_profile",
            "offering_type",
            "offering_type__offering",
        )


class RescheduleAppointmentView(generics.UpdateAPIView):
    """Reschedule an existing appointment"""

    serializer_class = RescheduleAppointmentSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"
    lookup_url_kwarg = "appointment_id"

    def get_queryset(self):
        """Filter appointments that can be rescheduled"""
        user = self.request.user
        return Appointment.objects.filter(
            Q(client=user) | Q(lawyer__vendor_profile__user=user),
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        ).select_related(
            "client",
            "lawyer",
            "lawyer__vendor_profile",
            "offering_type",
            "offering_type__offering",
        )

    def update(self, request, *args, **kwargs):
        """Reschedule the appointment"""
        appointment = self.get_object()
        serializer = self.get_serializer(
            data=request.data,
            context={"appointment": appointment, "user": request.user},
        )
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                rescheduled_appointment = self.perform_reschedule(
                    appointment, serializer.validated_data
                )
                response_serializer = AppointmentSerializer(rescheduled_appointment)
                return Response(
                    {
                        "appointment": response_serializer.data,
                        "message": "Appointment rescheduled successfully",
                    }
                )
        except ValidationError as e:
            return Response(
                {"error": "Reschedule failed", "details": e.detail},
                status=status.HTTP_400_BAD_REQUEST,
            )

    def perform_reschedule(self, appointment, validated_data):
        """Perform the rescheduling operation"""
        user = self.request.user
        new_start = validated_data["new_start_datetime"]
        reschedule_reason = validated_data.get("reschedule_reason", "")

        # Calculate new end time
        duration = timedelta(minutes=appointment.duration_minutes)
        new_end = new_start + duration

        # Update appointment directly
        appointment.start_datetime = new_start
        appointment.end_datetime = new_end
        appointment.status = AppointmentStatus.CONFIRMED
        appointment.is_rescheduled = True
        appointment.last_rescheduled_at = timezone.now()
        appointment.rescheduled_by = user

        if reschedule_reason:
            appointment.notes = (
                f"{appointment.notes}\n\nRescheduled: {reschedule_reason}".strip()
            )

        appointment.save()

        return appointment


class RefundStatusView(generics.RetrieveAPIView):
    """Get refund status and information for an appointment"""

    serializer_class = RefundStatusSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"
    lookup_url_kwarg = "appointment_id"

    def get_queryset(self):
        """Filter appointments based on user role"""
        user = self.request.user
        return Appointment.objects.filter(
            Q(client=user) | Q(lawyer__vendor_profile__user=user)
        ).select_related(
            "client",
            "lawyer",
            "lawyer__vendor_profile",
            "offering_type",
            "offering_type__offering",
        )

    def retrieve(self, request, *args, **kwargs):
        """Get detailed refund information"""
        appointment = self.get_object()
        serializer = self.get_serializer(appointment)

        response_data = {
            "refund_info": serializer.data,
            "actions": self._get_available_actions(appointment, request.user),
        }

        return Response(response_data)

    def _get_available_actions(self, appointment, user):
        """Get available actions for the user regarding refunds"""
        actions = []

        # Only clients can request refunds for paid appointments
        if (
            user == appointment.client
            and appointment.is_paid_appointment
            and appointment.status == AppointmentStatus.CANCELLED
            and appointment.refund_status == RefundStatus.NONE
        ):
            # Check if still eligible for refund
            if appointment.cancelled_at and appointment.start_datetime:
                threshold_hours = appointment.lawyer.cancellation_threshold_hours
                threshold_time = appointment.start_datetime - timedelta(
                    hours=threshold_hours
                )
                if appointment.cancelled_at <= threshold_time:
                    actions.append(
                        {
                            "action": "request_refund",
                            "label": "Request Refund",
                            "description": "Submit a refund request for this cancelled appointment",
                        }
                    )

        # Admin actions (if user is staff/admin)
        if user.is_staff:
            if appointment.refund_status == RefundStatus.PENDING:
                actions.extend(
                    [
                        {
                            "action": "approve_refund",
                            "label": "Approve Refund",
                            "description": "Approve the refund request",
                        },
                        {
                            "action": "reject_refund",
                            "label": "Reject Refund",
                            "description": "Reject the refund request",
                        },
                    ]
                )

        return actions


class LawyerAppointmentListView(generics.ListAPIView):
    """List appointments for a lawyer"""

    serializer_class = AppointmentListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Get appointments for the lawyer"""
        user = self.request.user

        # Verify user is a lawyer
        try:
            lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=user)
        except LawyerProfile.DoesNotExist:
            return Appointment.objects.none()

        queryset = Appointment.objects.filter(lawyer=lawyer_profile)

        # Apply filters
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        date_from = self.request.query_params.get("date_from")
        if date_from:
            queryset = queryset.filter(start_datetime__date__gte=date_from)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            queryset = queryset.filter(start_datetime__date__lte=date_to)

        return queryset.select_related(
            "client", "offering_type", "offering_type__offering",
            "lawyer__vendor_profile",
        ).order_by("-start_datetime")


class ClientAppointmentListView(generics.ListAPIView):
    """List appointments for a client"""

    serializer_class = AppointmentListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Get appointments for the client"""
        user = self.request.user
        queryset = Appointment.objects.filter(client=user)

        # Apply filters
        status_filter = self.request.query_params.get("status")
        if status_filter:
            queryset = queryset.filter(status=status_filter)

        date_from = self.request.query_params.get("date_from")
        if date_from:
            queryset = queryset.filter(start_datetime__date__gte=date_from)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            queryset = queryset.filter(start_datetime__date__lte=date_to)

        return queryset.select_related(
            "lawyer",
            "lawyer__vendor_profile",
            "offering_type",
            "offering_type__offering",
        ).order_by("-start_datetime")


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def appointment_stats(request):
    """Get appointment statistics for the authenticated user"""
    user = request.user

    # Check if user is a lawyer
    try:
        lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=user)
        appointments = Appointment.objects.filter(lawyer=lawyer_profile)
        user_type = "lawyer"
    except LawyerProfile.DoesNotExist:
        # User is a client
        appointments = Appointment.objects.filter(client=user)
        user_type = "client"

    # Calculate stats
    now = timezone.now()
    today = now.date()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    stats = {
        "total_appointments": appointments.count(),
        "pending_appointments": appointments.filter(
            status=AppointmentStatus.PENDING
        ).count(),
        "confirmed_appointments": appointments.filter(
            status=AppointmentStatus.CONFIRMED
        ).count(),
        "completed_appointments": appointments.filter(
            status=AppointmentStatus.COMPLETED
        ).count(),
        "cancelled_appointments": appointments.filter(
            status=AppointmentStatus.CANCELLED
        ).count(),
        "rescheduled_appointments": appointments.filter(is_rescheduled=True).count(),
        "physical_appointments": appointments.filter(
            offering_type__type="physical"
        ).count(),
        "audio_appointments": appointments.filter(offering_type__type="audio").count(),
        "video_appointments": appointments.filter(offering_type__type="video").count(),
        "upcoming_appointments": appointments.filter(
            start_datetime__gt=now,
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        ).count(),
        "appointments_today": appointments.filter(start_datetime__date=today).count(),
        "appointments_this_week": appointments.filter(
            start_datetime__date__gte=week_start
        ).count(),
        "appointments_this_month": appointments.filter(
            start_datetime__date__gte=month_start
        ).count(),
    }

    # Add revenue stats for lawyers
    if user_type == "lawyer":
        revenue_data = appointments.filter(
            status__in=[AppointmentStatus.COMPLETED, AppointmentStatus.CONFIRMED]
        ).aggregate(
            total_revenue=Sum("total_price"), total_commission=Sum("commission_amount")
        )
        stats.update(
            {
                "total_revenue": revenue_data["total_revenue"] or 0,
                "total_commission": revenue_data["total_commission"] or 0,
            }
        )
    else:
        stats.update(
            {
                "total_revenue": 0,
                "total_commission": 0,
            }
        )

    serializer = AppointmentStatsSerializer(stats)
    return Response(serializer.data)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def mark_appointment_completed(request, appointment_id):
    """Mark an appointment as completed (triggers fund release to lawyer)"""
    try:
        appointment = Appointment.objects.get(
            id=appointment_id, status=AppointmentStatus.CONFIRMED
        )

        # Verify user has permission (lawyer or client)
        user = request.user
        if (
            user != appointment.client
            and user != appointment.lawyer.vendor_profile.user
        ):
            return Response(
                {
                    "error": "You don't have permission to mark this appointment as completed"
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if timezone.now() < appointment.end_datetime:
            return Response(
                {"error": "Appointment has not ended yet"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        with transaction.atomic():
            # Update appointment status
            appointment.status = AppointmentStatus.COMPLETED
            appointment.save()

            # Complete the payment transaction and release funds to lawyer
            payment_transaction = Transaction.objects.filter(
                appointment=appointment,
                transaction_type=TransactionType.PAYMENT,
                status=TransactionStatus.PENDING,
            ).first()

            if payment_transaction:
                payment_transaction.status = TransactionStatus.COMPLETED
                payment_transaction.processed_at = timezone.now()
                payment_transaction.save()

                # Add funds to lawyer's wallet
                if payment_transaction.wallet:
                    payment_transaction.wallet.balance += appointment.lawyer_amount
                    payment_transaction.wallet.save()

        return Response(
            {
                "message": "Appointment marked as completed and funds released to lawyer",
                "appointment_status": "completed",
            }
        )

    except Appointment.DoesNotExist:
        return Response(
            {"error": "Appointment not found or not eligible for completion"},
            status=status.HTTP_404_NOT_FOUND,
        )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def get_session_details(request, appointment_id):
    """Get session details for an appointment"""
    try:
        # Get appointment and verify user has access
        appointment = get_object_or_404(
            Appointment.objects.select_related("client", "lawyer__vendor_profile"),
            Q(client=request.user) | Q(lawyer__vendor_profile__user=request.user),
            id=appointment_id,
            status__in=[AppointmentStatus.PENDING, AppointmentStatus.CONFIRMED],
        )

        # Don't create session for physical appointments
        if appointment.is_physical_appointment:
            return Response(
                {"error": "Physical appointments do not require video sessions"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Get or create session
        session, created = AppointmentSession.objects.get_or_create(
            appointment=appointment,
            defaults={
                "agora_channel_name": f"appointment_{str(appointment.id).replace('-', '_')}",
                "status": SessionStatus.NOT_STARTED,
            },
        )

        # Get or create participants if they don't exist
        if created or not session.participants.exists():
            # Create client participant
            AppointmentParticipant.objects.get_or_create(
                session=session,
                user=appointment.client,
                defaults={"role": ParticipantRole.CLIENT},
            )

            # Create lawyer participant
            AppointmentParticipant.objects.get_or_create(
                session=session,
                user=appointment.lawyer.vendor_profile.user,
                defaults={"role": ParticipantRole.LAWYER},
            )

        serializer = AppointmentSessionSerializer(session)
        return Response(serializer.data)

    except Appointment.DoesNotExist:
        return Response(
            {"error": "Appointment not found or access denied"},
            status=status.HTTP_404_NOT_FOUND,
        )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def join_session(request, appointment_id):
    """Generate token and join session"""
    try:
        # Get appointment and verify access
        appointment = get_object_or_404(
            Appointment.objects.select_related("client", "lawyer__vendor_profile"),
            Q(client=request.user) | Q(lawyer__vendor_profile__user=request.user),
            id=appointment_id,
            status=AppointmentStatus.CONFIRMED,
        )

        # Physical appointments don't need sessions
        if appointment.is_physical_appointment:
            return Response(
                {"error": "Physical appointments do not require video sessions"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Validate request data
        serializer = SessionJoinSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user_role = serializer.validated_data["user_role"]

        # Verify user role matches their actual role
        if user_role == "client" and request.user != appointment.client:
            return Response(
                {"error": "You are not the client for this appointment"},
                status=status.HTTP_403_FORBIDDEN,
            )
        elif (
            user_role == "lawyer"
            and request.user != appointment.lawyer.vendor_profile.user
        ):
            return Response(
                {"error": "You are not the lawyer for this appointment"},
                status=status.HTTP_403_FORBIDDEN,
            )

        # Get or create session
        session, _ = AppointmentSession.objects.get_or_create(
            appointment=appointment, defaults={"status": SessionStatus.NOT_STARTED}
        )

        # Generate channel name if not exists
        if not session.agora_channel_name:
            session.generate_agora_channel_name()

        # Get or create participant
        participant_role = (
            ParticipantRole.CLIENT if user_role == "client" else ParticipantRole.LAWYER
        )
        participant, _ = AppointmentParticipant.objects.get_or_create(
            session=session, user=request.user, defaults={"role": participant_role}
        )

        # Update session status to ACTIVE if first participant
        if session.status == SessionStatus.NOT_STARTED:
            session.status = SessionStatus.ACTIVE
            session.started_at = timezone.now()
            session.save(update_fields=["status", "started_at"])

        # Update participant join info
        participant.attended = True
        participant.joined_at = timezone.now()
        participant.left_at = None  # Reset in case they're rejoining
        participant.save(update_fields=["attended", "joined_at", "left_at"])

        # Generate Agora token
        uid = AgoraTokenGenerator.generate_uid_for_user(request.user.id)
        token, expires_at = AgoraTokenGenerator.generate_rtc_token(
            session.agora_channel_name, uid, role="publisher", expire_time_hours=24
        )

        return Response(
            {
                "success": True,
                "agora_token": token,
                "agora_app_id": getattr(settings, "AGORA_APP_ID", "agora-app-id"),
                "channel_name": session.agora_channel_name,
                "uid": uid,
                "token_expires_at": timezone.datetime.fromtimestamp(
                    expires_at, tz=timezone.get_current_timezone()
                ).isoformat(),
                "session_status": session.status,
                "participant": {
                    "id": str(participant.id),
                    "joined_at": participant.joined_at.isoformat(),
                    "attended": participant.attended,
                },
            }
        )

    except Appointment.DoesNotExist:
        return Response(
            {"error": "Appointment not found, not confirmed, or access denied"},
            status=status.HTTP_404_NOT_FOUND,
        )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def leave_session(request, appointment_id):
    """Handle participant leaving session"""
    try:
        # Get appointment and session
        appointment = get_object_or_404(
            Appointment.objects.select_related("client", "lawyer__vendor_profile"),
            Q(client=request.user) | Q(lawyer__vendor_profile__user=request.user),
            id=appointment_id,
        )

        session = get_object_or_404(AppointmentSession, appointment=appointment)

        # Validate request data
        serializer = SessionLeaveSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Get participant
        participant = get_object_or_404(
            AppointmentParticipant, session=session, user=request.user
        )

        # Update participant leave time
        participant.left_at = timezone.now()
        participant.save(update_fields=["left_at"])

        # Check if all participants have left
        active_participants = session.participants.filter(
            joined_at__isnull=False, left_at__isnull=True
        )

        session_ended = False
        if not active_participants.exists():
            session.status = SessionStatus.ENDED
            session.ended_at = timezone.now()
            session.calculate_actual_duration()
            session.save(
                update_fields=["status", "ended_at", "actual_duration_minutes"]
            )
            session_ended = True

        return Response(
            {
                "success": True,
                "session_status": session.status,
                "session_ended": session_ended,
                "participant": {
                    "id": str(participant.id),
                    "left_at": participant.left_at.isoformat(),
                    "session_duration_minutes": participant.session_duration_minutes,
                },
            }
        )

    except (
        Appointment.DoesNotExist,
        AppointmentSession.DoesNotExist,
        AppointmentParticipant.DoesNotExist,
    ):
        return Response(
            {"error": "Session or participant not found"},
            status=status.HTTP_404_NOT_FOUND,
        )


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def end_session(request, appointment_id):
    """End session manually"""
    try:
        # Get appointment and session
        appointment = get_object_or_404(
            Appointment.objects.select_related("client", "lawyer__vendor_profile"),
            Q(client=request.user) | Q(lawyer__vendor_profile__user=request.user),
            id=appointment_id,
        )

        session = get_object_or_404(
            AppointmentSession,
            appointment=appointment,
            status__in=[SessionStatus.NOT_STARTED, SessionStatus.ACTIVE],
        )

        # Validate request data
        serializer = SessionEndSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # Verify user role
        ended_by = serializer.validated_data["ended_by"]
        if ended_by == "client" and request.user != appointment.client:
            return Response(
                {"error": "You are not the client for this appointment"},
                status=status.HTTP_403_FORBIDDEN,
            )
        elif (
            ended_by == "lawyer"
            and request.user != appointment.lawyer.vendor_profile.user
        ):
            return Response(
                {"error": "You are not the lawyer for this appointment"},
                status=status.HTTP_403_FORBIDDEN,
            )

        with transaction.atomic():
            # End session
            session.status = SessionStatus.ENDED
            session.ended_at = timezone.now()
            session.calculate_actual_duration()
            session.save(
                update_fields=["status", "ended_at", "actual_duration_minutes"]
            )

            # Update any participants still "active"
            active_participants = session.participants.filter(left_at__isnull=True)
            for participant in active_participants:
                participant.left_at = session.ended_at
                participant.save(update_fields=["left_at"])

            # Mark appointment as completed if conditions are met
            appointment_updated = False
            if appointment.can_be_marked_completed():
                appointment.mark_as_completed()
                appointment_updated = True

        return Response(
            {
                "success": True,
                "session": {
                    "id": str(session.id),
                    "status": session.status,
                    "started_at": (
                        session.started_at.isoformat() if session.started_at else None
                    ),
                    "ended_at": session.ended_at.isoformat(),
                    "actual_duration_minutes": session.actual_duration_minutes,
                },
                "appointment_updated": appointment_updated,
                "appointment_status": (
                    appointment.status if appointment_updated else None
                ),
            }
        )

    except (Appointment.DoesNotExist, AppointmentSession.DoesNotExist):
        return Response(
            {"error": "Session not found or already ended"},
            status=status.HTTP_404_NOT_FOUND,
        )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def session_status(request, appointment_id):
    """Get real-time session status"""
    try:
        # Get appointment and session
        appointment = get_object_or_404(
            Appointment.objects.select_related("client", "lawyer__vendor_profile"),
            Q(client=request.user) | Q(lawyer__vendor_profile__user=request.user),
            id=appointment_id,
        )

        session = get_object_or_404(AppointmentSession, appointment=appointment)

        # Get participants info
        participants = session.participants.all()
        participants_data = []

        for participant in participants:
            participants_data.append(
                {
                    "user_id": str(participant.user.id),
                    "role": participant.role,
                    "is_online": participant.joined_at is not None
                    and participant.left_at is None,
                    "joined_at": (
                        participant.joined_at.isoformat()
                        if participant.joined_at
                        else None
                    ),
                }
            )

        # Calculate session duration
        session_duration_minutes = None
        if session.status == SessionStatus.ACTIVE and session.started_at:
            duration = timezone.now() - session.started_at
            session_duration_minutes = int(duration.total_seconds() / 60)
        elif session.status == SessionStatus.ENDED:
            session_duration_minutes = session.actual_duration_minutes

        participants_online = len([p for p in participants_data if p["is_online"]])

        return Response(
            {
                "session_status": session.status,
                "participants_online": participants_online,
                "participants": participants_data,
                "session_duration_minutes": session_duration_minutes,
                "last_updated": timezone.now().isoformat(),
            }
        )

    except (Appointment.DoesNotExist, AppointmentSession.DoesNotExist):
        return Response(
            {"error": "Session not found"}, status=status.HTTP_404_NOT_FOUND
        )
