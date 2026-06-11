import uuid
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models


class LawyerCategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, db_index=True)
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Lawyer Categories"
        ordering = ["title"]

    def __str__(self):
        return self.title


class LawyerSubcategory(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255, db_index=True)
    lawyercategory = models.ForeignKey(
        LawyerCategory,
        on_delete=models.CASCADE,
        related_name="subcategories",
        db_index=True,
    )
    description = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Lawyer Subcategories"
        ordering = ["title"]
        indexes = [
            models.Index(
                fields=["lawyercategory", "title"], name="lsubcat_cat_title_idx"
            ),
        ]

    def __str__(self):
        return f"{self.lawyercategory.title} - {self.title}"


class LawyerProfile(models.Model):
    KYC_STATUS_CHOICES = [
        ("unverified", "Unverified"),
        ("pending", "Pending"),
        ("verified", "Verified"),
        ("rejected", "Rejected"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    vendor_profile = models.OneToOneField(
        "profiles.VendorProfile",
        on_delete=models.CASCADE,
        related_name="lawyer_profile",
        db_index=True,
    )
    registration_number = models.CharField(
        max_length=100, db_index=True, blank=True, null=True
    )
    fiscal_code = models.CharField(max_length=50, db_index=True, blank=True, null=True)

    kyc_verification_status = models.CharField(
        max_length=20,
        choices=KYC_STATUS_CHOICES,
        default="unverified",
        db_index=True,
    )
    legal_verified = models.BooleanField(default=False)
    lawyercategories = models.ManyToManyField(
        LawyerCategory, related_name="lawyer_profiles", blank=True
    )
    lawyersubcategories = models.ManyToManyField(
        LawyerSubcategory, related_name="lawyer_profiles", blank=True
    )
    cancellation_threshold_hours = models.IntegerField(
        default=24, validators=[MinValueValidator(1), MaxValueValidator(168)]
    )
    average_rating = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(0), MaxValueValidator(5)],
        db_index=True,
    )
    review_count = models.IntegerField(default=0, db_index=True)

    commission_percentage = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=Decimal("10.00"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text="Platform commission percentage (e.g., 10.00 for 10%)",
    )
    default_pricing_plan = models.ForeignKey(
        "LawyerOffering",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_for_lawyers",
        help_text="Default pricing plan used when no specific plan is set",
    )

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(
                fields=["kyc_verification_status", "average_rating"],
                name="lprof_kyc_rating_idx",
            ),
            models.Index(
                fields=["vendor_profile", "kyc_verification_status"],
                name="lprof_vendor_kyc_idx",
            ),
            models.Index(fields=["-created_at"], name="lprof_created_desc_idx"),
        ]

    def __str__(self):
        return f"Lawyer Profile - {self.vendor_profile.business_name}"

    def update_rating_stats(self):
        """Update average rating and review count based on related reviews"""
        # This would be implemented when review system is added
        pass

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def get_availability_for_date_with_offerings(self, date):
        """
        Get availability for a specific date with offering details
        Returns a list of available time slots with their associated offerings
        """
        day_of_week = date.weekday()

        # Get regular availability slots for this day
        availability_slots = (
            self.availabilities.filter(
                day_of_week=day_of_week,
                is_active=True,
                offering__is_active=True,  # Only include active offerings
            )
            .select_related("offering")
            .order_by("start_time")
        )

        # Get unavailability for this specific date
        unavailable_periods = self.unavailabilities.filter(date=date)

        available_slots = []

        for slot in availability_slots:
            # Check if this slot is blocked by any unavailability
            is_blocked = False

            for unavail in unavailable_periods:
                if unavail.is_all_day:
                    is_blocked = True
                    break
                elif (
                    unavail.start_time
                    and unavail.end_time
                    and slot.start_time < unavail.end_time
                    and slot.end_time > unavail.start_time
                ):
                    is_blocked = True
                    break

            if not is_blocked:
                available_slots.append(
                    {
                        "availability_id": slot.id,
                        "start_time": slot.start_time,
                        "end_time": slot.end_time,
                        "duration": slot.duration_hours,
                        "duration_minutes": slot.duration_minutes,
                        "offering": {
                            "id": slot.offering.id,
                            "name": slot.offering.name,
                            "price_per_30min": slot.offering.price_per_30min,
                        },
                        "price_for_slot": slot.get_price_for_duration(),
                        "price_breakdown": slot.get_price_breakdown(),
                    }
                )

        return available_slots

    def is_available_at_time_with_offering(
        self, date, start_time, end_time, offering_id=None
    ):
        """
        Check if lawyer is available at specific time with optional offering filter
        """
        day_of_week = date.weekday()

        # Build base query
        availability_query = self.availabilities.filter(
            day_of_week=day_of_week,
            is_active=True,
            offering__is_active=True,
            start_time__lte=start_time,
            end_time__gte=end_time,
        )

        # Filter by specific offering if provided
        if offering_id:
            availability_query = availability_query.filter(offering_id=offering_id)

        # Check if any availability slot covers the requested time
        if not availability_query.exists():
            return False

        # Check for unavailability conflicts
        unavailable_periods = self.unavailabilities.filter(date=date)

        for unavail in unavailable_periods:
            if unavail.is_all_day:
                return False
            elif (
                unavail.start_time
                and unavail.end_time
                and start_time < unavail.end_time
                and end_time > unavail.start_time
            ):
                return False

        return True

    def get_offerings_for_day(self, day_of_week):
        """
        Get all offerings available for a specific day of the week
        """
        return self.offerings.filter(
            availabilities__day_of_week=day_of_week,
            availabilities__is_active=True,
            is_active=True,
        ).distinct()

    def get_availability_by_offering(self, offering_id, active_only=True):
        """
        Get all availability slots for a specific offering
        """
        query_filter = {"offering_id": offering_id}
        if active_only:
            query_filter["is_active"] = True

        return self.availabilities.filter(**query_filter).order_by(
            "day_of_week", "start_time"
        )

    def get_availability_stats_by_offering(self):
        """
        Get availability statistics grouped by offering
        """
        stats = []

        for offering in self.offerings.filter(is_active=True):
            # Get all availability slots for this offering
            availability_slots = self.availabilities.filter(
                offering=offering, is_active=True
            )

            total_slots = availability_slots.count()
            total_hours = Decimal("0")

            # Calculate total hours manually to avoid complex Django aggregation issues
            for slot in availability_slots:
                total_hours += Decimal(str(slot.duration_hours))

            total_hours = total_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

            # Get days of week where this offering is available
            days_available = list(
                availability_slots.values_list("day_of_week", flat=True).distinct()
            )

            stats.append(
                {
                    "offering_id": offering.id,
                    "offering_name": offering.name,
                    "offering_price_per_30min": offering.price_per_30min,
                    "total_slots": total_slots,
                    "total_hours": total_hours,
                    "days_available": days_available,
                    "days_count": len(days_available),
                }
            )

        return stats

    def clone_availability_to_offering(self, source_offering_id, target_offering_id):
        """
        Clone availability slots from one offering to another
        """
        source_slots = self.availabilities.filter(
            offering_id=source_offering_id, is_active=True
        )

        target_offering = self.offerings.get(id=target_offering_id)
        cloned_slots = []

        for slot in source_slots:
            # Check if slot already exists for target offering
            existing_slot = self.availabilities.filter(
                offering=target_offering,
                day_of_week=slot.day_of_week,
                start_time=slot.start_time,
                end_time=slot.end_time,
            ).first()

            if not existing_slot:
                # Import here to avoid circular imports
                from lawyer_availability.models import Availability

                new_slot = Availability.objects.create(
                    lawyer=self,
                    day_of_week=slot.day_of_week,
                    start_time=slot.start_time,
                    end_time=slot.end_time,
                    offering=target_offering,
                    is_active=slot.is_active,
                )
                cloned_slots.append(new_slot)

        return cloned_slots


class LawyerOffering(models.Model):
    """
    Pricing Plans (e.g., Standard Plan, Weekend Plan, Premium Plan)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lawyer_profile = models.ForeignKey(
        LawyerProfile,
        on_delete=models.CASCADE,
        related_name="offerings",
        db_index=True,
    )

    name = models.CharField(
        max_length=255,
        db_index=True,
        help_text="Pricing plan name (e.g., Standard plan, Weekend plan, Premium plan)",
    )

    price_per_30min = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"))],
        help_text="Base price for 30 minutes in USD",
        default=Decimal("200.00"),
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["lawyer_profile", "name"], name="unique_lawyer_profile_name"
            ),
        ]
        indexes = [
            models.Index(
                fields=["is_active", "lawyer_profile"], name="loff_active_prof_idx"
            ),
            models.Index(
                fields=["lawyer_profile", "is_active", "name"],
                name="loff_prof_active_name_idx",
            ),
        ]

    def __str__(self):
        return f"{self.name} - {self.lawyer_profile.vendor_profile.business_name}"

    # METHODS for pricing functionality
    def calculate_price(self, duration_minutes):
        """Calculate price based on duration in minutes"""
        units = Decimal(str(duration_minutes)) / Decimal("30")
        total = self.price_per_30min * units
        return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    def calculate_commission(self, total_price):
        """Calculate platform commission"""
        commission_rate = self.lawyer_profile.commission_percentage / 100
        return total_price * commission_rate

    def get_price_breakdown(self, duration_minutes):
        """Get complete price breakdown"""
        total_price = self.calculate_price(duration_minutes)
        commission = self.calculate_commission(total_price)
        lawyer_amount = total_price - commission

        return {
            "total_price": total_price,
            "commission_amount": commission,
            "lawyer_amount": lawyer_amount,
            "commission_percentage": self.lawyer_profile.commission_percentage,
        }

    @property
    def min_price(self):
        """Get the minimum price (30 minutes)"""
        return self.price_per_30min

    @property
    def max_price(self):
        """Get the maximum price (60 minutes)"""
        return self.calculate_price(60)

    def clean(self):
        """Validate pricing plan"""
        if self.price_per_30min <= 0:
            raise ValidationError("Price per 30 minutes must be greater than 0.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)


class OfferingType(models.Model):
    """
    Represents service delivery methods: physical (free), audio (paid), video (paid)
    """

    PHYSICAL = "physical"
    AUDIO = "audio"
    VIDEO = "video"

    OFFERING_CHOICES = [
        (PHYSICAL, "Physical"),  # Free - at lawyer's office
        (AUDIO, "Audio"),  # Paid - audio consultation
        (VIDEO, "Video"),  # Paid - video consultation
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    offering = models.ForeignKey(
        LawyerOffering,
        on_delete=models.CASCADE,
        related_name="offering_types",
        db_index=True,
    )
    type = models.CharField(
        max_length=10,
        choices=OFFERING_CHOICES,
        db_index=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["offering", "type"], name="unique_offering_type"
            ),
        ]
        ordering = ["type"]
        indexes = [
            models.Index(
                fields=["offering", "is_active"], name="otype_offering_active_idx"
            ),
            models.Index(fields=["type", "is_active"], name="otype_type_active_idx"),
        ]

    def __str__(self):
        return f"{self.offering.name} - {self.get_type_display()}"

    def get_price_for_duration(self, duration_minutes):
        """Get price for specific duration based on service type"""
        if self.type == "physical":
            return Decimal("0.00")  # Physical appointments are always free
        return self.offering.calculate_price(duration_minutes)

    def get_price_breakdown(self, duration_minutes):
        """Get complete price breakdown for this service type"""
        if self.type == "physical":
            return {
                "total_price": Decimal("0.00"),
                "commission_amount": Decimal("0.00"),
                "lawyer_amount": Decimal("0.00"),
                "commission_percentage": Decimal("0.00"),
                "is_free": True,
            }

        breakdown = self.offering.get_price_breakdown(duration_minutes)
        breakdown["is_free"] = False
        return breakdown

    @property
    def is_free_service(self):
        """Check if this service type is free"""
        return self.type == "physical"

    @property
    def price_for_30min(self):
        """Get price for 30 minutes"""
        return self.get_price_for_duration(30)

    @property
    def price_for_60min(self):
        """Get price for 60 minutes"""
        return self.get_price_for_duration(60)

    def clean(self):
        """Validate service type"""
        if not self.offering_id:
            raise ValidationError("Pricing plan (offering) is required.")

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
