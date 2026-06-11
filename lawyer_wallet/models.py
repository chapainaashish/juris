import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone

from lawyer.models import LawyerProfile
from lawyer_appointment.models import Appointment
from users.models import User


class TransactionType(models.TextChoices):
    PAYMENT = "payment", "Payment"
    PAYOUT = "payout", "Payout"
    REFUND = "refund", "Refund"
    FEE = "fee", "Platform Fee"
    ADJUSTMENT = "adjustment", "Adjustment"


class TransactionStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    COMPLETED = "completed", "Completed"
    FAILED = "failed", "Failed"
    CANCELLED = "cancelled", "Cancelled"


class Wallet(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lawyer = models.OneToOneField(LawyerProfile, on_delete=models.CASCADE)
    balance = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=0.00,
        validators=[MinValueValidator(Decimal("0.00"))],
    )
    is_locked = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Wallet for {self.lawyer} - Balance: ${self.balance}"


class Transaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wallet = models.ForeignKey(
        Wallet,
        on_delete=models.CASCADE,
        related_name="transactions",
        null=True,
        blank=True,
    )
    lawyer = models.ForeignKey(LawyerProfile, on_delete=models.CASCADE)
    client = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    appointment = models.ForeignKey(
        Appointment, on_delete=models.SET_NULL, null=True, blank=True
    )
    stripe_transaction_id = models.CharField(max_length=255, null=True, blank=True)
    title = models.CharField(max_length=255, blank=True)
    amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
    )
    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices,
    )
    status = models.CharField(
        max_length=20,
        choices=TransactionStatus.choices,
        default=TransactionStatus.PENDING,
    )
    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Unique key to prevent duplicate transactions",
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="processed_payouts",
    )
    rejection_reason = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["wallet", "status"]),
            models.Index(fields=["lawyer", "created_at"]),
            models.Index(fields=["idempotency_key"]),
        ]

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.transaction_type.title()} - ${self.amount} ({self.status})"
