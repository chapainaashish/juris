import uuid

from django.db import models, transaction


class KYCVerification(models.Model):
    """Simple KYC verification tracking"""

    STATUS_CHOICES = [
        ("requires_input", "Requires Input"),
        ("processing", "Processing"),
        ("verified", "Verified"),
        ("canceled", "Canceled"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lawyer_profile = models.OneToOneField(
        "lawyer.LawyerProfile",
        on_delete=models.CASCADE,
        related_name="kyc_verification",
    )
    stripe_verification_session_id = models.CharField(
        max_length=255, unique=True, db_index=True
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default="requires_input"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "KYC Verification"
        verbose_name_plural = "KYC Verifications"
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"KYC - {self.lawyer_profile.vendor_profile.business_name} ({self.status})"
        )

    @property
    def is_verified(self):
        return self.status == "verified"

    @transaction.atomic
    def update_from_stripe_data(self, stripe_data):
        """Update with essential data from Stripe"""

        if stripe_data["id"] != self.stripe_verification_session_id:
            raise ValueError("Stripe session ID mismatch")

        self.status = stripe_data.get("status", self.status)

        # Update lawyer profile KYC status
        if self.lawyer_profile:
            if self.status == "verified":
                self.lawyer_profile.kyc_verification_status = "verified"
            elif self.status == "processing":
                self.lawyer_profile.kyc_verification_status = "pending"
            elif self.status == "canceled":
                self.lawyer_profile.kyc_verification_status = "rejected"
            else:
                self.lawyer_profile.kyc_verification_status = "unverified"

            self.lawyer_profile.save(update_fields=["kyc_verification_status"])
