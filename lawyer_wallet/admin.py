from django.contrib import admin, messages
from django.db import transaction
from django.db.models import Sum
from django.http import HttpResponseRedirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    Transaction,
    TransactionStatus,
    TransactionType,
    Wallet,
)


class PendingWithdrawalFilter(admin.SimpleListFilter):
    """Custom filter for pending withdrawals"""

    title = "Withdrawal Status"
    parameter_name = "withdrawal_filter"

    def lookups(self, request, model_admin):
        return (
            ("pending_withdrawals", "Pending Withdrawals"),
            ("completed_withdrawals", "Completed Withdrawals"),
            ("rejected_withdrawals", "Rejected Withdrawals"),
            ("all_withdrawals", "All Withdrawals"),
        )

    def queryset(self, request, queryset):
        if self.value() == "pending_withdrawals":
            return queryset.filter(
                transaction_type=TransactionType.PAYOUT,
                status=TransactionStatus.PENDING,
            )
        elif self.value() == "completed_withdrawals":
            return queryset.filter(
                transaction_type=TransactionType.PAYOUT,
                status=TransactionStatus.COMPLETED,
            )
        elif self.value() == "rejected_withdrawals":
            return queryset.filter(
                transaction_type=TransactionType.PAYOUT, status=TransactionStatus.FAILED
            )
        elif self.value() == "all_withdrawals":
            return queryset.filter(transaction_type=TransactionType.PAYOUT)


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "lawyer_name",
        "balance",
        "pending_amount",
        "total_amount",
        "is_locked",
        "transaction_count",
        "updated_at",
    ]
    list_filter = ["is_locked", "updated_at"]
    search_fields = [
        "id",
        "lawyer__vendor_profile__business_name",
        "lawyer__vendor_profile__user__email",
    ]
    readonly_fields = ["id", "updated_at", "transaction_summary", "recent_transactions"]

    fieldsets = (
        (
            "Wallet Information",
            {"fields": ("id", "lawyer", "balance", "is_locked", "updated_at")},
        ),
        (
            "Transaction Summary",
            {
                "fields": ("transaction_summary", "recent_transactions"),
                "classes": ("collapse",),
            },
        ),
    )

    actions = ["lock_wallets", "unlock_wallets"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "lawyer", "lawyer__vendor_profile", "lawyer__vendor_profile__user"
            )
            .prefetch_related("transactions")
        )

    def lawyer_name(self, obj):
        """Display lawyer's business name and email"""
        return f"{obj.lawyer.vendor_profile.business_name} ({obj.lawyer.vendor_profile.user.email})"

    lawyer_name.short_description = "Lawyer"

    def pending_amount(self, obj):
        """Display pending transaction amount"""
        pending = (
            obj.transactions.filter(
                transaction_type=TransactionType.PAYMENT,
                status=TransactionStatus.PENDING,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        return f"{pending} USD"

    pending_amount.short_description = "Pending"

    def total_amount(self, obj):
        """Display total amount (available + pending)"""
        pending = (
            obj.transactions.filter(
                transaction_type=TransactionType.PAYMENT,
                status=TransactionStatus.PENDING,
            ).aggregate(total=Sum("amount"))["total"]
            or 0
        )
        total = obj.balance + pending
        return f"{total} USD"

    total_amount.short_description = "Total"

    def transaction_count(self, obj):
        """Display number of transactions"""
        return obj.transactions.count()

    transaction_count.short_description = "Transactions"

    def transaction_summary(self, obj):
        """Display transaction summary"""
        transactions = obj.transactions.all()

        # Payment stats
        completed_payments = transactions.filter(
            transaction_type=TransactionType.PAYMENT, status=TransactionStatus.COMPLETED
        )
        pending_payments = transactions.filter(
            transaction_type=TransactionType.PAYMENT, status=TransactionStatus.PENDING
        )

        # Withdrawal stats
        completed_withdrawals = transactions.filter(
            transaction_type=TransactionType.PAYOUT, status=TransactionStatus.COMPLETED
        )
        pending_withdrawals = transactions.filter(
            transaction_type=TransactionType.PAYOUT, status=TransactionStatus.PENDING
        )

        # Calculate amounts
        total_earned = completed_payments.aggregate(total=Sum("amount"))["total"] or 0
        total_withdrawn = (
            completed_withdrawals.aggregate(total=Sum("amount"))["total"] or 0
        )
        pending_earnings = pending_payments.aggregate(total=Sum("amount"))["total"] or 0
        pending_withdrawal = (
            pending_withdrawals.aggregate(total=Sum("amount"))["total"] or 0
        )

        summary = f"""
        <div style="font-family: monospace;">
        <strong>PAYMENTS:</strong><br>
        Completed: {completed_payments.count()} ({total_earned} USD)<br>
        Pending: {pending_payments.count()} ({pending_earnings} USD)<br>
        <br>
        <strong>WITHDRAWALS:</strong><br>
        Completed: {completed_withdrawals.count()} ({total_withdrawn} USD)<br>
        Pending: {pending_withdrawals.count()} ({pending_withdrawal} USD)<br>
        </div>
        """

        return mark_safe(summary)

    transaction_summary.short_description = "Transaction Summary"

    def recent_transactions(self, obj):
        """Display recent transactions"""
        recent = obj.transactions.order_by("-created_at")[:5]

        if not recent.exists():
            return "No transactions"

        transaction_list = "<div style='font-family: monospace;'>"
        for txn in recent:
            status_color = {
                TransactionStatus.COMPLETED: "#4caf50",
                TransactionStatus.PENDING: "#ff9800",
                TransactionStatus.FAILED: "#f44336",
                TransactionStatus.CANCELLED: "#9e9e9e",
            }.get(txn.status, "#000000")

            transaction_list += f"""
            <div style="margin-bottom: 8px; padding: 5px; border-left: 3px solid {status_color};">
                <strong>{txn.get_transaction_type_display()}</strong> - {txn.amount} USD<br>
                <span style="color: {status_color}; font-weight: bold;">({txn.get_status_display()})</span><br>
                <small style="color: #666;">{txn.created_at.strftime('%Y-%m-%d %H:%M')}</small>
            </div>
            """

        transaction_list += "</div>"
        return mark_safe(transaction_list)

    recent_transactions.short_description = "Recent Transactions"

    def lock_wallets(self, request, queryset):
        """Lock selected wallets"""
        updated = queryset.update(is_locked=True)
        messages.success(request, f"Successfully locked {updated} wallet(s).")

    lock_wallets.short_description = "Lock selected wallets"

    def unlock_wallets(self, request, queryset):
        """Unlock selected wallets"""
        updated = queryset.update(is_locked=False)
        messages.success(request, f"Successfully unlocked {updated} wallet(s).")

    unlock_wallets.short_description = "Unlock selected wallets"


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "lawyer_name",
        "client_name",
        "amount",
        "status_display",
        "withdrawal_actions",
        "created_at",
    ]
    list_filter = [
        "transaction_type",
        "status",
        ("created_at", admin.DateFieldListFilter),
        ("processed_at", admin.DateFieldListFilter),
        PendingWithdrawalFilter,
    ]
    search_fields = [
        "id",
        "lawyer__vendor_profile__business_name",
        "client__email",
        "title",
        "stripe_transaction_id",
        "idempotency_key",
    ]
    readonly_fields = [
        "id",
        "created_at",
        "updated_at",
        "appointment_details",
        "stripe_info",
    ]

    fieldsets = (
        (
            "Transaction Information",
            {
                "fields": (
                    "id",
                    "wallet",
                    "lawyer",
                    "client",
                    "appointment",
                    "title",
                    "amount",
                    "transaction_type",
                    "status",
                )
            },
        ),
        (
            "Processing Information",
            {"fields": ("processed_at", "processed_by", "rejection_reason")},
        ),
        (
            "Technical Details",
            {
                "fields": (
                    "stripe_transaction_id",
                    "idempotency_key",
                    "appointment_details",
                    "stripe_info",
                ),
                "classes": ("collapse",),
            },
        ),
        (
            "Timestamps",
            {"fields": ("created_at", "updated_at"), "classes": ("collapse",)},
        ),
    )

    actions = ["approve_selected_withdrawals", "reject_selected_withdrawals"]

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related(
                "wallet",
                "lawyer",
                "lawyer__vendor_profile",
                "client",
                "appointment",
                "processed_by",
            )
        )

    def lawyer_name(self, obj):
        """Display lawyer's business name"""
        return obj.lawyer.vendor_profile.business_name

    lawyer_name.short_description = "Lawyer"

    def client_name(self, obj):
        """Display client's name"""
        if obj.client:
            return obj.client.get_full_name() or obj.client.email
        return "N/A"

    client_name.short_description = "Client"

    def status_display(self, obj):
        """Display status with color coding"""
        colors = {
            TransactionStatus.COMPLETED: "#4caf50",
            TransactionStatus.PENDING: "#ff9800",
            TransactionStatus.FAILED: "#f44336",
            TransactionStatus.CANCELLED: "#9e9e9e",
        }
        color = colors.get(obj.status, "#000000")
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_display.short_description = "Status"

    def appointment_details(self, obj):
        """Display appointment information"""
        if not obj.appointment:
            return "No appointment"

        appt = obj.appointment
        details = f"""
        <strong>ID:</strong> {appt.id}<br>
        <strong>Date:</strong> {appt.start_datetime.strftime('%Y-%m-%d %H:%M')}<br>
        <strong>Status:</strong> {appt.get_status_display()}<br>
        <strong>Type:</strong> {appt.offering_type.get_type_display()}<br>
        """
        return mark_safe(details)

    appointment_details.short_description = "Appointment Details"

    def stripe_info(self, obj):
        """Display Stripe information"""
        if not obj.stripe_transaction_id:
            return "No Stripe transaction"

        return f"Stripe ID: {obj.stripe_transaction_id}"

    stripe_info.short_description = "Stripe Information"

    def withdrawal_actions(self, obj):
        """Display withdrawal action buttons"""
        if (
            obj.transaction_type == TransactionType.PAYOUT
            and obj.status == TransactionStatus.PENDING
        ):
            approve_url = reverse("admin:transaction_approve_withdrawal", args=[obj.pk])
            reject_url = reverse("admin:transaction_reject_withdrawal", args=[obj.pk])

            return format_html(
                '<a class="button" href="{}" style="background-color: #4caf50; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px; margin-right: 5px;">✅ Approve</a>'
                '<a class="button" href="{}" style="background-color: #f44336; color: white; padding: 5px 10px; text-decoration: none; border-radius: 3px;">❌ Reject</a>',
                approve_url,
                reject_url,
            )
        elif obj.transaction_type == TransactionType.PAYOUT:
            if obj.status == TransactionStatus.COMPLETED:
                return format_html(
                    '<span style="color: #4caf50; font-weight: bold;">Approved</span>'
                )
            elif obj.status == TransactionStatus.FAILED:
                return format_html(
                    '<span style="color: #f44336; font-weight: bold;">Rejected</span>'
                )
        return "N/A"

    withdrawal_actions.short_description = "Actions"
    withdrawal_actions.allow_tags = True

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "<path:object_id>/approve-withdrawal/",
                self.admin_site.admin_view(self.approve_withdrawal_view),
                name="transaction_approve_withdrawal",
            ),
            path(
                "<path:object_id>/reject-withdrawal/",
                self.admin_site.admin_view(self.reject_withdrawal_view),
                name="transaction_reject_withdrawal",
            ),
        ]
        return custom_urls + urls

    def approve_withdrawal_view(self, request, object_id):
        """Individual withdrawal approval view"""
        try:
            txn = Transaction.objects.get(pk=object_id)
            success = self._approve_withdrawal(txn, request.user)

            if success:
                messages.success(
                    request, f"Withdrawal {txn.id} has been approved successfully!"
                )
            else:
                messages.error(request, f"Failed to approve withdrawal {txn.id}.")
        except Transaction.DoesNotExist:
            messages.error(request, "Transaction not found.")

        return HttpResponseRedirect(
            reverse("admin:lawyer_wallet_transaction_changelist")
        )

    def reject_withdrawal_view(self, request, object_id):
        """Individual withdrawal rejection view"""
        try:
            txn = Transaction.objects.get(pk=object_id)
            rejection_reason = request.GET.get("reason", "Withdrawal rejected by admin")

            success = self._reject_withdrawal(txn, request.user, rejection_reason)

            if success:
                messages.success(request, f"Withdrawal {txn.id} has been rejected.")
            else:
                messages.error(request, f"Failed to reject withdrawal {txn.id}.")
        except Transaction.DoesNotExist:
            messages.error(request, "Transaction not found.")

        return HttpResponseRedirect(
            reverse("admin:lawyer_wallet_transaction_changelist")
        )

    def approve_selected_withdrawals(self, request, queryset):
        """Bulk approve withdrawals"""
        pending_withdrawals = queryset.filter(
            transaction_type=TransactionType.PAYOUT, status=TransactionStatus.PENDING
        )
        approved_count = 0

        for txn in pending_withdrawals:
            if self._approve_withdrawal(txn, request.user):
                approved_count += 1

        messages.success(
            request, f"Successfully approved {approved_count} withdrawal(s)."
        )

    approve_selected_withdrawals.short_description = "Approve selected withdrawals"

    def reject_selected_withdrawals(self, request, queryset):
        """Bulk reject withdrawals"""
        pending_withdrawals = queryset.filter(
            transaction_type=TransactionType.PAYOUT, status=TransactionStatus.PENDING
        )
        rejected_count = 0

        for txn in pending_withdrawals:
            if self._reject_withdrawal(txn, request.user, "Bulk rejection by admin"):
                rejected_count += 1

        messages.success(
            request, f"Successfully rejected {rejected_count} withdrawal(s)."
        )

    reject_selected_withdrawals.short_description = "Reject selected withdrawals"

    def _approve_withdrawal(self, withdrawal_transaction, admin_user):
        """Approve withdrawal transaction"""
        if (
            withdrawal_transaction.transaction_type != TransactionType.PAYOUT
            or withdrawal_transaction.status != TransactionStatus.PENDING
        ):
            return False

        try:
            with transaction.atomic():
                withdrawal_transaction.status = TransactionStatus.COMPLETED
                withdrawal_transaction.processed_at = timezone.now()
                withdrawal_transaction.processed_by = admin_user
                withdrawal_transaction.save()
                return True
        except Exception:
            return False

    def _reject_withdrawal(self, withdrawal_transaction, admin_user, rejection_reason):
        """Reject withdrawal transaction"""
        if (
            withdrawal_transaction.transaction_type != TransactionType.PAYOUT
            or withdrawal_transaction.status != TransactionStatus.PENDING
        ):
            return False

        try:
            with transaction.atomic():
                withdrawal_transaction.status = TransactionStatus.FAILED
                withdrawal_transaction.processed_at = timezone.now()
                withdrawal_transaction.processed_by = admin_user
                withdrawal_transaction.rejection_reason = rejection_reason
                withdrawal_transaction.save()

                # Return money to wallet balance
                wallet = withdrawal_transaction.wallet
                wallet.balance += withdrawal_transaction.amount
                wallet.save(update_fields=["balance"])

                return True
        except Exception:
            return False


class PendingWithdrawalFilter(admin.SimpleListFilter):
    """Custom filter for pending withdrawals"""

    title = "Withdrawal Status"
    parameter_name = "withdrawal_filter"

    def lookups(self, request, model_admin):
        return (
            ("pending_withdrawals", "Pending Withdrawals"),
            ("completed_withdrawals", "Completed Withdrawals"),
            ("rejected_withdrawals", "Rejected Withdrawals"),
            ("all_withdrawals", "All Withdrawals"),
        )

    def queryset(self, request, queryset):
        if self.value() == "pending_withdrawals":
            return queryset.filter(
                transaction_type=TransactionType.PAYOUT,
                status=TransactionStatus.PENDING,
            )
        elif self.value() == "completed_withdrawals":
            return queryset.filter(
                transaction_type=TransactionType.PAYOUT,
                status=TransactionStatus.COMPLETED,
            )
        elif self.value() == "rejected_withdrawals":
            return queryset.filter(
                transaction_type=TransactionType.PAYOUT, status=TransactionStatus.FAILED
            )
        elif self.value() == "all_withdrawals":
            return queryset.filter(transaction_type=TransactionType.PAYOUT)
