from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    """Extended user model with role-based access"""

    ROLES = [
        ("client", "Client"),
        ("vendor", "Vendor"),
    ]

    VENDOR_TYPES = [
        ("lawyer", "Lawyer"),
        ("notary", "Notary"),
        ("accountant", "Accountant"),
        ("translator", "Translator"),
    ]

    email = models.EmailField(_("email address"), unique=True)
    phone_number = models.CharField(max_length=20, unique=True, null=True, blank=True)
    password_attempt = models.IntegerField(default=0)
    is_email_verified = models.BooleanField(default=False)
    email_verification_valid_until = models.DateTimeField(null=True, blank=True)
    is_2fa_enabled = models.BooleanField(default=False)
    has_initiate_login = models.BooleanField(default=False)

    role = models.CharField(
        max_length=20,
        choices=ROLES,
        default="client",
        help_text="User role determines platform access",
    )

    vendor_type = models.CharField(
        max_length=20,
        choices=VENDOR_TYPES,
        null=True,
        blank=True,
        help_text="Professional category for vendors",
    )

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username", "first_name", "last_name"]

    def __str__(self):
        return self.email

    @property
    def is_complete(self):
        """
        Check if user profile is complete based on role
        - Clients: Always complete (no additional setup required)
        - Vendors: Complete when vendor profile is finished
        """
        if self.role == "client":
            return True

        if self.role == "vendor":
            try:
                vendor_profile = self.vendorprofile
                return vendor_profile.is_completed if vendor_profile else False
            except AttributeError:
                return False

        return False

    @property
    def can_access_dashboard(self):
        """Determine if user can access vendor dashboard"""
        return self.role == "vendor" and self.is_complete


class PasswordResetToken(models.Model):
    """Model for email-based password reset tokens"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="password_reset_tokens"
    )
    token = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)

    class Meta:
        db_table = "password_reset_tokens"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Password reset token for {self.user.email}"

    def is_valid(self):
        """Check if token is still valid and not used"""
        return not self.is_used and self.expires_at > timezone.now()

    @classmethod
    def cleanup_expired(cls):
        """Clean up expired tokens - call this in a periodic task"""
        cls.objects.filter(expires_at__lt=timezone.now()).delete()
