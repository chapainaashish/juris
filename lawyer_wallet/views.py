from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from lawyer.models import LawyerProfile

from .models import Transaction, TransactionStatus, TransactionType, Wallet
from .serializers import (
    TransactionListSerializer,
    TransactionSerializer,
    WalletSerializer,
    WalletStatsSerializer,
    WithdrawSerializer,
)


class WalletDetailView(generics.RetrieveAPIView):
    """Get wallet details for the authenticated lawyer"""

    serializer_class = WalletSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        """Get wallet for the authenticated lawyer"""
        try:
            lawyer_profile = LawyerProfile.objects.get(
                vendor_profile__user=self.request.user
            )
            wallet, created = Wallet.objects.get_or_create(
                lawyer=lawyer_profile, defaults={"balance": Decimal("0.00")}
            )
            return wallet
        except LawyerProfile.DoesNotExist:
            from rest_framework.exceptions import NotFound

            raise NotFound("Only lawyers can access wallet information")

    def retrieve(self, request, *args, **kwargs):
        """Return wallet details with balance information"""
        wallet = self.get_object()
        serializer = self.get_serializer(wallet)

        # Add additional context
        data = serializer.data
        data["can_withdraw"] = not wallet.is_locked and wallet.balance > Decimal(
            "10.00"
        )
        data["minimum_withdrawal"] = "10.00"
        data["maximum_withdrawal"] = "50000.00"

        return Response(data)


class LawyerTransactionsListView(generics.ListAPIView):
    """List all transactions for the authenticated lawyer"""

    serializer_class = TransactionListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Get transactions for the authenticated lawyer"""
        try:
            lawyer_profile = LawyerProfile.objects.get(
                vendor_profile__user=self.request.user
            )
            queryset = Transaction.objects.filter(lawyer=lawyer_profile)

            # Apply filters
            transaction_type = self.request.query_params.get("type")
            if transaction_type:
                queryset = queryset.filter(transaction_type=transaction_type)

            transaction_status = self.request.query_params.get("status")
            if transaction_status:
                queryset = queryset.filter(status=transaction_status)

            date_from = self.request.query_params.get("date_from")
            if date_from:
                queryset = queryset.filter(created_at__date__gte=date_from)

            date_to = self.request.query_params.get("date_to")
            if date_to:
                queryset = queryset.filter(created_at__date__lte=date_to)

            return queryset.select_related(
                "client", "appointment", "processed_by"
            ).order_by("-created_at")

        except LawyerProfile.DoesNotExist:
            return Transaction.objects.none()


class ClientTransactionsListView(generics.ListAPIView):
    """List all transactions for the authenticated client"""

    serializer_class = TransactionListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Get transactions for the authenticated client"""
        queryset = Transaction.objects.filter(client=self.request.user)

        # Apply filters
        transaction_type = self.request.query_params.get("type")
        if transaction_type:
            queryset = queryset.filter(transaction_type=transaction_type)

        transaction_status = self.request.query_params.get("status")
        if transaction_status:
            queryset = queryset.filter(status=transaction_status)

        date_from = self.request.query_params.get("date_from")
        if date_from:
            queryset = queryset.filter(created_at__date__gte=date_from)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            queryset = queryset.filter(created_at__date__lte=date_to)

        return queryset.select_related(
            "lawyer", "lawyer__vendor_profile", "appointment", "processed_by"
        ).order_by("-created_at")


class TransactionDetailView(generics.RetrieveAPIView):
    """Get detailed information about a specific transaction"""

    serializer_class = TransactionSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_field = "id"

    def get_queryset(self):
        """Filter transactions based on user role"""
        user = self.request.user

        # Check if user is a lawyer
        try:
            lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=user)
            return Transaction.objects.filter(lawyer=lawyer_profile)
        except LawyerProfile.DoesNotExist:
            # User is a client
            return Transaction.objects.filter(client=user)


class WithdrawView(generics.CreateAPIView):
    """Create a withdrawal request for lawyers"""

    serializer_class = WithdrawSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_context(self):
        """Add user to serializer context"""
        context = super().get_serializer_context()
        context["user"] = self.request.user
        return context

    def create(self, request, *args, **kwargs):
        """Process withdrawal request"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        validated_data = serializer.validated_data
        amount = validated_data["amount"]
        withdrawal_reason = validated_data["withdrawal_reason"]
        idempotency_key = validated_data["idempotency_key"]
        wallet = validated_data["wallet"]
        lawyer_profile = validated_data["lawyer_profile"]

        try:
            with transaction.atomic():
                # Re-fetch wallet with row lock to prevent concurrent withdrawals
                wallet = Wallet.objects.select_for_update().get(pk=wallet.pk)
                if wallet.is_locked:
                    raise Exception("Wallet is temporarily locked")
                if wallet.balance < amount:
                    raise Exception(
                        f"Insufficient balance. Available: {wallet.balance} USD, Requested: {amount} USD"
                    )

                # Create withdrawal transaction
                withdrawal_transaction = Transaction.objects.create(
                    wallet=wallet,
                    lawyer=lawyer_profile,
                    client=None,  # No client for withdrawals
                    appointment=None,  # No appointment for withdrawals
                    title=withdrawal_reason,
                    amount=amount,
                    transaction_type=TransactionType.PAYOUT,
                    status=TransactionStatus.PENDING,  # Pending approval
                    idempotency_key=idempotency_key,
                )

                # Subtract amount from wallet balance immediately
                # This prevents double withdrawal while pending approval
                wallet.balance -= amount
                wallet.save(update_fields=["balance"])

                # Serialize the transaction
                response_serializer = TransactionSerializer(withdrawal_transaction)

                return Response(
                    {
                        "transaction": response_serializer.data,
                        "message": "Withdrawal request submitted successfully. It will be processed by our admin team within 1-2 business days.",
                        "wallet_balance": str(wallet.balance),
                    },
                    status=status.HTTP_201_CREATED,
                )

        except Exception as e:
            return Response(
                {"error": "Failed to process withdrawal request", "details": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def wallet_stats(request):
    """Get wallet statistics for the authenticated lawyer"""
    try:
        lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=request.user)

        # Get current date ranges
        now = timezone.now()
        current_month_start = now.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
        last_month_start = (current_month_start - timedelta(days=1)).replace(day=1)
        last_month_end = current_month_start - timedelta(days=1)

        # Get wallet
        wallet = Wallet.objects.get(lawyer=lawyer_profile)

        # Calculate various statistics
        all_transactions = Transaction.objects.filter(lawyer=lawyer_profile)

        # Earnings (completed payments only - this shows net earnings without platform fees)
        completed_payments = all_transactions.filter(
            transaction_type=TransactionType.PAYMENT, status=TransactionStatus.COMPLETED
        )

        total_earnings = completed_payments.aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0.00")

        # Pending earnings (payments in escrow)
        pending_payments = all_transactions.filter(
            transaction_type=TransactionType.PAYMENT, status=TransactionStatus.PENDING
        )

        pending_earnings = pending_payments.aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0.00")

        # Withdrawals
        completed_withdrawals = all_transactions.filter(
            transaction_type=TransactionType.PAYOUT, status=TransactionStatus.COMPLETED
        )

        total_withdrawals = completed_withdrawals.aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0.00")

        # Monthly earnings
        earnings_this_month = completed_payments.filter(
            processed_at__gte=current_month_start
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        earnings_last_month = completed_payments.filter(
            processed_at__gte=last_month_start, processed_at__lte=last_month_end
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        # Monthly withdrawals
        withdrawals_this_month = completed_withdrawals.filter(
            processed_at__gte=current_month_start
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        # Transaction counts
        stats_data = {
            "total_earnings": total_earnings,
            "total_withdrawals": total_withdrawals,
            "pending_earnings": pending_earnings,
            "available_balance": wallet.balance,
            "total_transactions": all_transactions.count(),
            "completed_payments": completed_payments.count(),
            "pending_payments": pending_payments.count(),
            "total_withdrawals_count": completed_withdrawals.count(),
            "earnings_this_month": earnings_this_month,
            "earnings_last_month": earnings_last_month,
            "withdrawals_this_month": withdrawals_this_month,
        }

        serializer = WalletStatsSerializer(stats_data)
        return Response(serializer.data)

    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Only lawyers can access wallet statistics"},
            status=status.HTTP_403_FORBIDDEN,
        )
    except Wallet.DoesNotExist:
        return Response({"error": "Wallet not found"}, status=status.HTTP_404_NOT_FOUND)
