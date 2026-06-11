from decimal import Decimal

from django.db.models import Q, Sum
from rest_framework import serializers

from lawyer.models import LawyerProfile

from .models import Transaction, TransactionStatus, TransactionType, Wallet


class WalletSerializer(serializers.ModelSerializer):
    """Serializer for wallet with calculated balances"""

    available_balance = serializers.SerializerMethodField()
    pending_balance = serializers.SerializerMethodField()
    total_balance = serializers.SerializerMethodField()
    lawyer_name = serializers.CharField(
        source="lawyer.vendor_profile.business_name", read_only=True
    )

    class Meta:
        model = Wallet
        fields = [
            "id",
            "lawyer",
            "lawyer_name",
            "balance",
            "available_balance",
            "pending_balance",
            "total_balance",
            "is_locked",
            "updated_at",
        ]
        read_only_fields = ["id", "lawyer", "balance", "updated_at"]

    def get_available_balance(self, obj):
        """Get the available balance (completed transactions only)"""
        return obj.balance

    def get_pending_balance(self, obj):
        """Get pending balance from appointment payments in escrow"""
        pending_amount = obj.transactions.filter(
            transaction_type=TransactionType.PAYMENT, status=TransactionStatus.PENDING
        ).aggregate(total=Sum("amount"))["total"] or Decimal("0.00")

        return pending_amount

    def get_total_balance(self, obj):
        """Get total balance (available + pending)"""
        return self.get_available_balance(obj) + self.get_pending_balance(obj)


class TransactionSerializer(serializers.ModelSerializer):
    """Serializer for transaction details"""

    transaction_type_display = serializers.CharField(
        source="get_transaction_type_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    lawyer_name = serializers.CharField(
        source="lawyer.vendor_profile.business_name", read_only=True
    )
    client_name = serializers.CharField(source="client.get_full_name", read_only=True)
    appointment_id = serializers.UUIDField(source="appointment.id", read_only=True)
    processed_by_name = serializers.CharField(
        source="processed_by.get_full_name", read_only=True
    )

    class Meta:
        model = Transaction
        fields = [
            "id",
            "wallet",
            "lawyer",
            "lawyer_name",
            "client",
            "client_name",
            "appointment",
            "appointment_id",
            "stripe_transaction_id",
            "title",
            "amount",
            "transaction_type",
            "transaction_type_display",
            "status",
            "status_display",
            "idempotency_key",
            "processed_at",
            "processed_by",
            "processed_by_name",
            "rejection_reason",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "wallet",
            "lawyer",
            "client",
            "appointment",
            "stripe_transaction_id",
            "processed_at",
            "processed_by",
            "created_at",
            "updated_at",
        ]


class TransactionListSerializer(serializers.ModelSerializer):
    """Simplified serializer for transaction lists"""

    transaction_type_display = serializers.CharField(
        source="get_transaction_type_display", read_only=True
    )
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    lawyer_name = serializers.CharField(
        source="lawyer.vendor_profile.business_name", read_only=True
    )
    client_name = serializers.CharField(source="client.get_full_name", read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "lawyer_name",
            "client_name",
            "title",
            "amount",
            "transaction_type",
            "transaction_type_display",
            "status",
            "status_display",
            "created_at",
        ]


class WithdrawSerializer(serializers.Serializer):
    """Serializer for lawyer withdrawal requests"""

    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal("0.01")
    )
    withdrawal_reason = serializers.CharField(
        max_length=500, required=False, default="Withdrawal request"
    )
    idempotency_key = serializers.CharField(
        max_length=255,
        required=True,
        help_text="Unique key to prevent duplicate withdrawals",
    )

    def validate_amount(self, value):
        """Validate withdrawal amount"""
        # Check minimum withdrawal amount
        min_withdrawal = Decimal("10.00")  # Minimum 10 USD
        if value < min_withdrawal:
            raise serializers.ValidationError(
                f"Minimum withdrawal amount is {min_withdrawal} USD"
            )

        # Check maximum withdrawal amount (optional safety limit)
        max_withdrawal = Decimal("50000.00")  # Maximum 50,000 USD
        if value > max_withdrawal:
            raise serializers.ValidationError(
                f"Maximum withdrawal amount is {max_withdrawal} USD"
            )

        return value

    def validate_idempotency_key(self, value):
        """Validate idempotency key format"""
        if not value.strip():
            raise serializers.ValidationError("Idempotency key cannot be empty")

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
        user = self.context.get("user")
        amount = attrs["amount"]
        idempotency_key = attrs["idempotency_key"]

        if not user:
            raise serializers.ValidationError("User context is required")

        # Check if user is a lawyer
        try:
            lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=user)
        except LawyerProfile.DoesNotExist:
            raise serializers.ValidationError("Only lawyers can make withdrawals")

        # Check KYC verification
        from kyc.models import KYCVerification

        try:
            kyc = lawyer_profile.kyc_verification
            if not kyc.is_verified:
                raise serializers.ValidationError(
                    "KYC verification must be completed before withdrawing funds"
                )
        except KYCVerification.DoesNotExist:
            raise serializers.ValidationError(
                "KYC verification must be completed before withdrawing funds"
            )

        # Check if lawyer has a wallet
        try:
            wallet = Wallet.objects.get(lawyer=lawyer_profile)
        except Wallet.DoesNotExist:
            raise serializers.ValidationError("Wallet not found")

        # Check if wallet is locked
        if wallet.is_locked:
            raise serializers.ValidationError("Wallet is temporarily locked")

        # Check available balance
        if wallet.balance < amount:
            raise serializers.ValidationError(
                f"Insufficient balance. Available: {wallet.balance} USD, Requested: {amount} USD"
            )

        # Check for duplicate idempotency key
        existing_transaction = Transaction.objects.filter(
            idempotency_key=idempotency_key, transaction_type=TransactionType.PAYOUT
        ).first()

        if existing_transaction:
            raise serializers.ValidationError(
                "A withdrawal with this idempotency key already exists"
            )

        # Add wallet and lawyer to validated data
        attrs["wallet"] = wallet
        attrs["lawyer_profile"] = lawyer_profile

        return attrs


class WalletStatsSerializer(serializers.Serializer):
    """Serializer for wallet statistics"""

    total_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_withdrawals = serializers.DecimalField(max_digits=12, decimal_places=2)
    pending_earnings = serializers.DecimalField(max_digits=12, decimal_places=2)
    available_balance = serializers.DecimalField(max_digits=12, decimal_places=2)

    # Transaction counts
    total_transactions = serializers.IntegerField()
    completed_payments = serializers.IntegerField()
    pending_payments = serializers.IntegerField()
    total_withdrawals_count = serializers.IntegerField()

    # Time-based stats
    earnings_this_month = serializers.DecimalField(max_digits=12, decimal_places=2)
    earnings_last_month = serializers.DecimalField(max_digits=12, decimal_places=2)
    withdrawals_this_month = serializers.DecimalField(max_digits=12, decimal_places=2)
