import uuid
from datetime import timedelta

from django.db import models
from django.utils.timezone import now

from users.models import User


# CORE MODELS
class Category(models.Model):
    """Vendor categories - independent model"""

    LAWYER = "Lawyer"
    NOTARY = "Notary"
    ACCOUNTANT = "Accountant"
    TRANSLATOR = "Translator"

    CATEGORY_CHOICES = [
        (LAWYER, "Lawyer"),
        (NOTARY, "Notary"),
        (ACCOUNTANT, "Accountant"),
        (TRANSLATOR, "Translator"),
    ]

    name = models.CharField(max_length=50, choices=CATEGORY_CHOICES, unique=True)

    def __str__(self):
        return self.name


class Language(models.Model):
    """Languages - independent model"""

    name = models.CharField(max_length=50, unique=True)
    icon_url = models.URLField(
        max_length=255, blank=True, null=True
    )  # Cloudinary image link

    def __str__(self):
        return self.name


class Address(models.Model):
    """Address information - independent model"""

    street = models.CharField(max_length=255)
    city = models.CharField(max_length=100)
    postcode = models.CharField(max_length=20)
    country = models.CharField(max_length=100)
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)

    def __str__(self):
        return f"{self.street}, {self.city}, {self.country}"


# MAIN VENDOR MODELS (Depend on core models)


class VendorProfile(models.Model):
    """Main vendor profile - depends on User, Category, Address, Language"""

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    business_name = models.CharField(max_length=255)
    address = models.OneToOneField(
        Address, on_delete=models.SET_NULL, null=True, blank=True
    )
    languages = models.ManyToManyField(Language, blank=True)
    avatar_url = models.URLField(
        max_length=255, blank=True, null=True
    )  # Stored on Cloudinary

    bio = models.TextField(blank=True, null=True)
    experience = models.TextField(blank=True, null=True)
    website = models.URLField(max_length=255, blank=True, null=True)
    whatsapp = models.CharField(max_length=50, blank=True, null=True)
    facebook = models.URLField(max_length=255, blank=True, null=True)
    youtube = models.URLField(max_length=255, blank=True, null=True)
    instagram = models.URLField(max_length=255, blank=True, null=True)
    twitter = models.URLField(max_length=255, blank=True, null=True)
    social_media_status = models.BooleanField(default=False)
    general_link = models.URLField(max_length=255, blank=True, null=True)
    is_completed = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def deactivate_listing(self):
        """Deactivate vendor listing when subscription is inactive"""
        self.is_active = False
        self.save()

    def activate_listing(self):
        """Activate vendor listing when subscription is active"""
        self.is_active = True
        self.save()

    def __str__(self):
        return f"{self.business_name} - {self.user.email}"


class VendorLegalInfo(models.Model):
    """Legal information for vendors - depends on VendorProfile"""

    BAR_ASSOCIATION_CHOICES = [
        ("Alba Bar Association", "Alba Bar Association"),
        ("Arad Bar Association", "Arad Bar Association"),
        ("Arges Bar Association", "Arges Bar Association"),
        ("Bacau Bar Association", "Bacau Bar Association"),
        ("Bihor Bar Association", "Bihor Bar Association"),
        ("Bistrita-Nasaud Bar Association", "Bistrita-Nasaud Bar Association"),
        ("Botosani Bar Association", "Botosani Bar Association"),
        ("Braila Bar Association", "Braila Bar Association"),
        ("Brasov Bar Association", "Brasov Bar Association"),
        ("Bucharest Bar Association", "Bucharest Bar Association"),
        ("Buzau Bar Association", "Buzau Bar Association"),
        ("Caras-Severin Bar Association", "Caras-Severin Bar Association"),
        ("Calarasi Bar Association", "Calarasi Bar Association"),
        ("Cluj Bar Association", "Cluj Bar Association"),
        ("Constanta Bar Association", "Constanta Bar Association"),
        ("Covasna Bar Association", "Covasna Bar Association"),
        ("Dambovita Bar Association", "Dambovita Bar Association"),
        ("Dolj Bar Association", "Dolj Bar Association"),
        ("Galati Bar Association", "Galati Bar Association"),
        ("Giurgiu Bar Association", "Giurgiu Bar Association"),
        ("Gorj Bar Association", "Gorj Bar Association"),
        ("Harghita Bar Association", "Harghita Bar Association"),
        ("Hunedoara Bar Association", "Hunedoara Bar Association"),
        ("Ialomita Bar Association", "Ialomita Bar Association"),
        ("Iasi Bar Association", "Iasi Bar Association"),
        ("Ilfov Bar Association", "Ilfov Bar Association"),
        ("Maramures Bar Association", "Maramures Bar Association"),
        ("Mehedinti Bar Association", "Mehedinti Bar Association"),
        ("Mures Bar Association", "Mures Bar Association"),
        ("Neamt Bar Association", "Neamt Bar Association"),
        ("Olt Bar Association", "Olt Bar Association"),
        ("Prahova Bar Association", "Prahova Bar Association"),
        ("Salaj Bar Association", "Salaj Bar Association"),
        ("Satu Mare Bar Association", "Satu Mare Bar Association"),
        ("Sibiu Bar Association", "Sibiu Bar Association"),
        ("Suceava Bar Association", "Suceava Bar Association"),
        ("Teleorman Bar Association", "Teleorman Bar Association"),
        ("Timis Bar Association", "Timis Bar Association"),
        ("Tulcea Bar Association", "Tulcea Bar Association"),
        ("Valcea Bar Association", "Valcea Bar Association"),
        ("Vaslui Bar Association", "Vaslui Bar Association"),
        ("Vrancea Bar Association", "Vrancea Bar Association"),
    ]
    vendor_profile = models.OneToOneField(VendorProfile, on_delete=models.CASCADE)
    first_name_id = models.CharField(max_length=100)
    last_name_id = models.CharField(max_length=100)
    email = models.EmailField()
    bar_association = models.CharField(
        max_length=50, choices=BAR_ASSOCIATION_CHOICES, null=True, blank=True
    )

    def __str__(self):
        return f"{self.first_name_id} {self.last_name_id}"


# SESSION MODEL (For profile completion workflow)


def _generate_session_token():
    return uuid.uuid4().hex


def _default_session_expiry():
    return now() + timedelta(days=7)


class ProfileCompletionSession(models.Model):
    """Session model for multi-step profile completion - depends on User, Category, Address, Language"""

    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True)

    token = models.CharField(max_length=64, unique=True, default=_generate_session_token)
    category = models.ForeignKey(
        Category, on_delete=models.SET_NULL, null=True, blank=True
    )
    business_name = models.CharField(max_length=255, blank=True, null=True)
    address = models.ForeignKey(
        Address, on_delete=models.SET_NULL, null=True, blank=True
    )
    languages = models.ManyToManyField(Language, blank=True)
    avatar_url = models.URLField(max_length=255, blank=True, null=True)

    # Legal information fields
    first_name_id = models.CharField(max_length=100, blank=True, null=True)
    last_name_id = models.CharField(max_length=100, blank=True, null=True)
    legal_email = models.EmailField(blank=True, null=True)
    bar_association = models.CharField(max_length=50, blank=True, null=True)

    # Additional profile fields
    bio = models.TextField(blank=True, null=True)
    experience = models.TextField(blank=True, null=True)
    website = models.URLField(max_length=255, blank=True, null=True)
    whatsapp = models.CharField(max_length=50, blank=True, null=True)
    facebook = models.URLField(max_length=255, blank=True, null=True)
    youtube = models.URLField(max_length=255, blank=True, null=True)
    instagram = models.URLField(max_length=255, blank=True, null=True)
    twitter = models.URLField(max_length=255, blank=True, null=True)
    social_media_status = models.BooleanField(default=False)
    general_link = models.URLField(max_length=255, blank=True, null=True)

    # Session management
    created_at = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(auto_now=True)
    is_completed = models.BooleanField(default=False)
    expires_at = models.DateTimeField(default=_default_session_expiry)

    def __str__(self):
        return f"Session: {self.token[:8]}... for {self.user.email if self.user else 'Anonymous'}"


# SERVICE-RELATED MODELS (Depend on VendorProfile)


class ServiceCategory(models.Model):
    """Service categories for vendors - depends on VendorProfile"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_profile = models.ForeignKey(
        VendorProfile, on_delete=models.CASCADE, related_name="service_categories"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.vendor_profile.business_name}"

    class Meta:
        verbose_name = "Service Category"
        verbose_name_plural = "Service Categories"


class Service(models.Model):
    """Individual services - depends on VendorProfile and ServiceCategory"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_profile = models.ForeignKey(
        VendorProfile, on_delete=models.CASCADE, related_name="services"
    )
    category = models.ForeignKey(
        ServiceCategory, on_delete=models.CASCADE, related_name="services"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    tags = models.TextField(blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True)
    image = models.URLField(max_length=500, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return (
            f"{self.name} - {self.category.name} - {self.vendor_profile.business_name}"
        )

    class Meta:
        verbose_name = "Service"
        verbose_name_plural = "Services"
        ordering = ["-created_at"]


# MEDIA AND DOCUMENT MODELS (Depend on VendorProfile)


class Media(models.Model):
    """Media files for vendors - depends on VendorProfile"""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_profile = models.ForeignKey(
        VendorProfile, on_delete=models.CASCADE, related_name="media"
    )
    title = models.CharField(max_length=255, blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    file = models.URLField(max_length=500)  # Cloudinary URL
    file_type = models.CharField(max_length=50)  # e.g: image, video, document
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title or 'Untitled'} - {self.vendor_profile.business_name}"

    class Meta:
        verbose_name = "Media"
        verbose_name_plural = "Media"


class Certificate(models.Model):
    """Certificates for vendors - depends on VendorProfile"""

    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_profile = models.ForeignKey(
        VendorProfile, on_delete=models.CASCADE, related_name="certificates"
    )
    title = models.CharField(max_length=255)
    details = models.TextField(blank=True, null=True)
    file = models.URLField(max_length=500)  # Cloudinary URL
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default="active")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} - {self.vendor_profile.business_name}"
