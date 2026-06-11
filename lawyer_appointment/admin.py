import stripe
from django.conf import settings
from django.contrib import admin, messages
from django.db import models, transaction
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from lawyer_wallet.models import Transaction, TransactionStatus, TransactionType

from .models import (
    Appointment,
    AppointmentParticipant,
    AppointmentSession,
    FundsStatus,
    RefundStatus,
)


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "client",
        "lawyer_name",
        "status",
        "start_datetime",
        "end_datetime",
        "total_price",
        "refund_status",
        "funds_status_display",
        "refund_actions",
    ]
    list_filter = [
        "status",
        "refund_status",
        "start_datetime",
        "offering_type__type",
        "is_rescheduled",
    ]
    search_fields = [
        "id",
        "client__email",
        "client__first_name",
        "client__last_name",
        "lawyer__vendor_profile__business_name",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "stripe_payment_intent_id",
        "payment_task_id",
        "reminder_task_id",
        "auto_complete_task_id",
        "funds_status_display",
        "payment_transaction_info",
        "refund_transaction_info",
    ]

    fieldsets = (
        (
            "Appointment Details",
            {
                "fields": (
                    "id",
                    "client",
                    "lawyer",
                    "offering_type",
                    "start_datetime",
                    "end_datetime",
                    "notes",
                    "status",
                )
            },
        ),
        (
            "Pricing Information",
            {
                "fields": (
                    "total_price",
                    "commission_amount",
                    "lawyer_amount",
                    "funds_status_display",
                )
            },
        ),
        (
            "Payment Information",
            {
                "fields": (
                    "stripe_payment_intent_id",
                    "payment_transaction_info",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Refund Information",
            {
                "fields": (
                    "refund_status",
                    "refund_reason",
                    "refund_requested_at",
                    "refund_response",
                    "refund_processed_at",
                    "refund_transaction_info",
                )
            },
        ),
        (
            "Cancellation/Rescheduling",
            {
                "fields": (
                    "is_rescheduled",
                    "last_rescheduled_at",
                    "rescheduled_by",
                    "cancellation_reason",
                    "cancelled_at",
                    "cancelled_by",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "System Information",
            {
                "fields": (
                    "payment_task_id",
                    "reminder_task_id",
                    "auto_complete_task_id",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    actions = [
        "approve_selected_refunds",
        "reject_selected_refunds",
        "mark_as_completed",
        "mark_as_no_show",
    ]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "client",
                "lawyer",
                "lawyer__vendor_profile",
                "offering_type",
                "cancelled_by",
                "rescheduled_by",
            )
        )

    def lawyer_name(self, obj):
        """Display lawyer's business name"""
        return obj.lawyer.vendor_profile.business_name

    lawyer_name.short_description = "Lawyer"

    def funds_status_display(self, obj):
        """Display current funds status with color coding"""
        status = obj.get_funds_status()
        display_name = obj.get_funds_status_display()

        color_map = {
            FundsStatus.ESCROW: "#ff9800",  # Orange
            FundsStatus.RELEASED: "#4caf50",  # Green
            FundsStatus.CANCELLED: "#f44336",  # Red
            FundsStatus.NOT_APPLICABLE: "#9e9e9e",  # Grey
            FundsStatus.NO_PAYMENT: "#9e9e9e",  # Grey
            FundsStatus.UNKNOWN: "#f44336",  # Red
        }

        color = color_map.get(status, "#000000")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>', color, display_name
        )

    funds_status_display.short_description = "Funds Status"

    def payment_transaction_info(self, obj):
        """Display payment transaction details"""
        payment_transaction = obj.get_payment_transaction()
        if not payment_transaction:
            return "No payment transaction"

        info = f"""
        <strong>ID:</strong> {payment_transaction.id}<br>
        <strong>Status:</strong> {payment_transaction.get_status_display()}<br>
        <strong>Amount:</strong> {payment_transaction.amount} USD<br>
        <strong>Stripe ID:</strong> {payment_transaction.stripe_transaction_id or 'N/A'}<br>
        <strong>Created:</strong> {payment_transaction.created_at}<br>
        """
        if payment_transaction.processed_at:
            info += (
                f"<strong>Processed:</strong> {payment_transaction.processed_at}<br>"
            )

        return mark_safe(info)

    payment_transaction_info.short_description = "Payment Transaction"

    def refund_transaction_info(self, obj):
        """Display refund transaction details"""
        refund_transaction = obj.get_refund_transaction()
        if not refund_transaction:
            return "No refund transaction"

        info = f"""
        <strong>ID:</strong> {refund_transaction.id}<br>
        <strong>Status:</strong> {refund_transaction.get_status_display()}<br>
        <strong>Amount:</strong> {refund_transaction.amount} USD<br>
        <strong>Stripe ID:</strong> {refund_transaction.stripe_transaction_id or 'N/A'}<br>
        <strong>Created:</strong> {refund_transaction.created_at}<br>
        """
        if refund_transaction.processed_at:
            info += f"<strong>Processed:</strong> {refund_transaction.processed_at}<br>"

        return mark_safe(info)

    refund_transaction_info.short_description = "Refund Transaction"

    def refund_actions(self, obj):
        """Display refund action buttons"""
        if obj.refund_status == RefundStatus.PENDING:
            approve_url = reverse("admin:appointment_approve_refund", args=[obj.pk])
            reject_url = reverse("admin:appointment_reject_refund", args=[obj.pk])

            return format_html(
                '<a class="button" href="{}" style="background-color: #4caf50; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; margin-right: 5px;">Approve</a>'
                '<a class="button" href="{}" style="background-color: #f44336; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px;">Reject</a>',
                approve_url,
                reject_url,
            )
        elif obj.refund_status == RefundStatus.APPROVED:
            return format_html(
                '<span style="color: #4caf50; font-weight: bold;">✓ Approved</span>'
            )
        elif obj.refund_status == RefundStatus.REJECTED:
            return format_html(
                '<span style="color: #f44336; font-weight: bold;">✗ Rejected</span>'
            )
        else:
            return "No refund requested"

    refund_actions.short_description = "Refund Actions"
    refund_actions.allow_tags = True

    # Custom URLs for refund actions
    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/approve-refund/",
                self.admin_site.admin_view(self.approve_refund_view),
                name="appointment_approve_refund",
            ),
            path(
                "<path:object_id>/reject-refund/",
                self.admin_site.admin_view(self.reject_refund_view),
                name="appointment_reject_refund",
            ),
        ]
        return custom_urls + urls

    def approve_refund_view(self, request, object_id):
        """Individual refund approval view"""
        try:
            appointment = Appointment.objects.get(pk=object_id)
            success = self._approve_refund(appointment, request.user)

            if success:
                messages.success(
                    request,
                    f"Refund for appointment {appointment.id} has been approved and processed.",
                )
            else:
                messages.error(
                    request,
                    f"Failed to process refund for appointment {appointment.id}. Check the logs for details.",
                )
        except Appointment.DoesNotExist:
            messages.error(request, "Appointment not found.")

        return HttpResponseRedirect(
            reverse("admin:lawyer_appointment_appointment_changelist")
        )

    def reject_refund_view(self, request, object_id):
        """Individual refund rejection view"""
        try:
            appointment = Appointment.objects.get(pk=object_id)
            rejection_reason = request.GET.get(
                "reason", "Refund request rejected by admin"
            )

            success = self._reject_refund(appointment, request.user, rejection_reason)

            if success:
                messages.success(
                    request,
                    f"Refund for appointment {appointment.id} has been rejected.",
                )
            else:
                messages.error(
                    request,
                    f"Failed to reject refund for appointment {appointment.id}.",
                )
        except Appointment.DoesNotExist:
            messages.error(request, "Appointment not found.")

        return HttpResponseRedirect(
            reverse("admin:lawyer_appointment_appointment_changelist")
        )

    # Bulk Actions
    def approve_selected_refunds(self, request, queryset):
        """Bulk approve refunds"""
        pending_refunds = queryset.filter(refund_status=RefundStatus.PENDING)
        approved_count = 0
        failed_count = 0

        for appointment in pending_refunds:
            if self._approve_refund(appointment, request.user):
                approved_count += 1
            else:
                failed_count += 1

        if approved_count > 0:
            messages.success(
                request, f"Successfully approved {approved_count} refund(s)."
            )

        if failed_count > 0:
            messages.error(
                request,
                f"Failed to approve {failed_count} refund(s). Check the logs for details.",
            )

    approve_selected_refunds.short_description = "Approve selected refund requests"

    def reject_selected_refunds(self, request, queryset):
        """Bulk reject refunds"""
        pending_refunds = queryset.filter(refund_status=RefundStatus.PENDING)
        rejected_count = 0

        for appointment in pending_refunds:
            if self._reject_refund(
                appointment, request.user, "Bulk rejection by admin"
            ):
                rejected_count += 1

        messages.success(
            request, f"Successfully rejected {rejected_count} refund request(s)."
        )

    reject_selected_refunds.short_description = "Reject selected refund requests"

    def mark_as_completed(self, request, queryset):
        """Mark appointments as completed"""
        completed_count = 0

        for appointment in queryset:
            if appointment.can_be_marked_completed():
                try:
                    appointment.mark_as_completed()
                    completed_count += 1
                except Exception as e:
                    messages.error(
                        request,
                        f"Failed to complete appointment {appointment.id}: {str(e)}",
                    )

        if completed_count > 0:
            messages.success(
                request,
                f"Successfully marked {completed_count} appointment(s) as completed.",
            )

    mark_as_completed.short_description = "Mark selected appointments as completed"

    def mark_as_no_show(self, request, queryset):
        """Mark appointments as no show"""
        no_show_count = 0

        for appointment in queryset:
            if appointment.status in ["confirmed", "pending"]:
                appointment.mark_as_no_show()
                no_show_count += 1

        messages.success(
            request, f"Successfully marked {no_show_count} appointment(s) as no show."
        )

    mark_as_no_show.short_description = "Mark selected appointments as no show"

    # Helper methods for refund processing
    def _approve_refund(self, appointment, admin_user):
        """Approve refund and process with Stripe"""
        if appointment.refund_status != RefundStatus.PENDING:
            return False

        try:
            with transaction.atomic():
                # Update appointment
                appointment.refund_status = RefundStatus.APPROVED
                appointment.refund_response = f"Refund approved by {admin_user.get_full_name() or admin_user.username}"
                appointment.refund_processed_at = timezone.now()
                appointment.save()

                # Get the refund transaction
                refund_transaction = Transaction.objects.filter(
                    appointment=appointment,
                    transaction_type=TransactionType.REFUND,
                    status=TransactionStatus.PENDING,
                ).first()

                if refund_transaction:
                    # Process Stripe refund
                    try:
                        stripe.api_key = settings.STRIPE_SECRET_KEY

                        # Create Stripe refund
                        refund = stripe.Refund.create(
                            payment_intent=appointment.stripe_payment_intent_id,
                            amount=int(appointment.total_price * 100),
                            idempotency_key=refund_transaction.idempotency_key,
                            metadata={
                                "appointment_id": str(appointment.id),
                                "transaction_id": str(refund_transaction.id),
                            },
                        )

                        # Update transaction with Stripe refund ID
                        refund_transaction.stripe_transaction_id = refund.id
                        refund_transaction.processed_by = admin_user
                        refund_transaction.save()

                        return True

                    except stripe.error.StripeError as e:
                        # Rollback appointment status if Stripe fails
                        appointment.refund_status = RefundStatus.PENDING
                        appointment.refund_response = f"Stripe error: {str(e)}"
                        appointment.refund_processed_at = None
                        appointment.save()
                        return False
                else:
                    return False

        except Exception as e:
            return False

    def _reject_refund(self, appointment, admin_user, rejection_reason):
        """Reject refund and complete payment transaction"""
        if appointment.refund_status != RefundStatus.PENDING:
            return False

        try:
            with transaction.atomic():
                # Update appointment
                appointment.refund_status = RefundStatus.REJECTED
                appointment.refund_response = rejection_reason
                appointment.refund_processed_at = timezone.now()
                appointment.save()

                # Cancel the refund transaction
                refund_transaction = Transaction.objects.filter(
                    appointment=appointment,
                    transaction_type=TransactionType.REFUND,
                    status=TransactionStatus.PENDING,
                ).first()

                if refund_transaction:
                    refund_transaction.status = TransactionStatus.CANCELLED
                    refund_transaction.save()

                # Complete the original payment transaction since no refund
                payment_transaction = Transaction.objects.filter(
                    appointment=appointment,
                    transaction_type=TransactionType.PAYMENT,
                    status=TransactionStatus.PENDING,
                ).first()

                if payment_transaction:
                    payment_transaction.status = TransactionStatus.COMPLETED
                    payment_transaction.processed_at = timezone.now()
                    payment_transaction.processed_by = admin_user
                    payment_transaction.save()

                    # Add funds to lawyer's wallet
                    if payment_transaction.wallet:
                        payment_transaction.wallet.balance += appointment.lawyer_amount
                        payment_transaction.wallet.save()

                return True

        except Exception as e:
            return False

    # Custom list filters
    def get_list_filter(self, request):
        filters = list(self.list_filter)

        # Add custom filter for pending refunds
        if request.user.is_superuser:
            filters.append(PendingRefundFilter)

        return filters


class PendingRefundFilter(admin.SimpleListFilter):
    title = "Refund Status Filter"
    parameter_name = "refund_filter"

    def lookups(self, request, model_admin):
        return (
            ("pending_refunds", "Pending Refunds Only"),
            ("needs_attention", "Needs Admin Attention"),
        )

    def queryset(self, request, queryset):
        if self.value() == "pending_refunds":
            return queryset.filter(refund_status=RefundStatus.PENDING)
        elif self.value() == "needs_attention":
            return queryset.filter(
                models.Q(refund_status=RefundStatus.PENDING) | models.Q(status="failed")
            )


@admin.register(AppointmentSession)
class AppointmentSessionAdmin(admin.ModelAdmin):
    list_display = [
        "appointment",
        "status",
        "started_at",
        "ended_at",
        "actual_duration_minutes",
    ]
    list_filter = ["status"]
    search_fields = ["appointment__id", "appointment__client__email"]
    readonly_fields = ["created_at", "actual_duration_minutes"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("appointment", "appointment__client")
        )


@admin.register(AppointmentParticipant)
class AppointmentParticipantAdmin(admin.ModelAdmin):
    list_display = ["user", "session", "role", "attended", "joined_at", "left_at"]
    list_filter = ["role", "attended"]
    search_fields = ["user__email", "session__appointment__id"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("user", "session", "session__appointment")
        )
