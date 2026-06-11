import uuid
from datetime import datetime, time

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from lawyer.models import LawyerOffering, LawyerProfile


class Availability(models.Model):
    """
    Defines regular weekly availability slots for lawyers with specific offerings
    """

    WEEKDAYS = [
        (0, "Monday"),
        (1, "Tuesday"),
        (2, "Wednesday"),
        (3, "Thursday"),
        (4, "Friday"),
        (5, "Saturday"),
        (6, "Sunday"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lawyer = models.ForeignKey(
        LawyerProfile,
        on_delete=models.CASCADE,
        related_name="availabilities",
        db_index=True,
    )
    day_of_week = models.IntegerField(
        choices=WEEKDAYS, db_index=True, help_text="0=Monday, 1=Tuesday, ... 6=Sunday"
    )
    start_time = models.TimeField(help_text="Start time for availability (e.g., 09:00)")
    end_time = models.TimeField(help_text="End time for availability (e.g., 17:00)")

    offering = models.ForeignKey(
        LawyerOffering,
        on_delete=models.CASCADE,
        related_name="availabilities",
        db_index=True,
        help_text="The pricing plan/offering associated with this availability slot",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        help_text="Whether this availability slot is currently active",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "lawyer",
                    "day_of_week",
                    "start_time",
                    "end_time",
                    "offering",
                ],
                name="unique_lawyer_schedule_slot",
            ),
        ]
        ordering = ["day_of_week", "start_time"]
        indexes = [
            models.Index(
                fields=["lawyer", "day_of_week", "is_active"],
                name="avail_lawyer_day_active_idx",
            ),
            models.Index(
                fields=["day_of_week", "start_time"], name="avail_day_start_idx"
            ),
            models.Index(
                fields=["offering", "is_active"], name="avail_offering_active_idx"
            ),
            models.Index(
                fields=["lawyer", "offering", "day_of_week"],
                name="avail_lawyer_offering_day_idx",
            ),
        ]

    def __str__(self):
        return f"{self.lawyer} - {self.get_day_of_week_display()} {self.start_time}-{self.end_time} ({self.offering.name})"

    def clean(self):
        """Validate availability slot"""
        errors = {}

        if self.start_time and self.end_time and self.start_time >= self.end_time:
            errors["end_time"] = ["Start time must be before end time."]

        # Validate that offering belongs to the same lawyer
        if self.offering_id and self.lawyer_id:
            if self.offering.lawyer_profile_id != self.lawyer_id:
                errors["offering"] = ["Offering must belong to the same lawyer."]

        # Check for overlapping availability slots for the same lawyer and day
        if self.is_active and self.lawyer_id:
            overlapping = Availability.objects.filter(
                lawyer=self.lawyer, day_of_week=self.day_of_week, is_active=True
            ).exclude(pk=self.pk)

            for slot in overlapping:
                if self.start_time < slot.end_time and self.end_time > slot.start_time:
                    if "start_time" not in errors:
                        errors["start_time"] = []
                    errors["start_time"].append(
                        f"This availability slot overlaps with existing slot: "
                        f"{slot.start_time}-{slot.end_time} ({slot.offering.name})"
                    )
                    break

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def duration_hours(self):
        """Calculate duration in hours"""
        start = datetime.combine(datetime.today(), self.start_time)
        end = datetime.combine(datetime.today(), self.end_time)
        return (end - start).total_seconds() / 3600

    @property
    def duration_minutes(self):
        """Calculate duration in minutes"""
        return self.duration_hours * 60

    def get_price_for_duration(self, duration_minutes=None):
        """Get price for this availability slot's duration or custom duration"""
        if duration_minutes is None:
            duration_minutes = self.duration_minutes
        return self.offering.calculate_price(duration_minutes)

    def get_price_breakdown(self, duration_minutes=None):
        """Get complete price breakdown for this availability slot"""
        if duration_minutes is None:
            duration_minutes = self.duration_minutes
        return self.offering.get_price_breakdown(duration_minutes)


class Unavailability(models.Model):
    """
    Defines specific dates/times when lawyer is unavailable
    (overrides regular availability)
    """

    UNAVAILABILITY_TYPES = [
        ("vacation", "Vacation"),
        ("sick_leave", "Sick Leave"),
        ("personal", "Personal"),
        ("court_appearance", "Court Appearance"),
        ("meeting", "Meeting"),
        ("training", "Training"),
        ("other", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    lawyer = models.ForeignKey(
        LawyerProfile,
        on_delete=models.CASCADE,
        related_name="unavailabilities",
        db_index=True,
    )
    date = models.DateField(db_index=True, help_text="Date of unavailability")
    start_time = models.TimeField(
        null=True,
        blank=True,
        help_text="Start time (leave blank for all-day unavailability)",
    )
    end_time = models.TimeField(
        null=True,
        blank=True,
        help_text="End time (leave blank for all-day unavailability)",
    )
    is_all_day = models.BooleanField(
        default=False, help_text="Whether this is an all-day unavailability"
    )
    unavailability_type = models.CharField(
        max_length=20, choices=UNAVAILABILITY_TYPES, default="other", db_index=True
    )
    reason = models.TextField(
        blank=True, null=True, help_text="Optional reason for unavailability"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["date", "start_time"]
        indexes = [
            models.Index(fields=["lawyer", "date"], name="unavail_lawyer_date_idx"),
            models.Index(fields=["date", "start_time"], name="unavail_date_start_idx"),
            models.Index(
                fields=["lawyer", "unavailability_type"], name="unavail_lawyer_type_idx"
            ),
        ]

    def __str__(self):
        if self.is_all_day:
            return f"{self.lawyer} - {self.date} (All Day)"
        return f"{self.lawyer} - {self.date} {self.start_time}-{self.end_time}"

    def clean(self):
        """Validate unavailability entry"""
        errors = {}

        # Validate that date is not in the past
        if self.date and self.date < timezone.now().date():
            errors["date"] = ["Cannot create unavailability for past dates."]

        # Validate time logic
        if not self.is_all_day:
            if not self.start_time or not self.end_time:
                errors["non_field_errors"] = [
                    "Start time and end time are required when not all-day."
                ]
            elif self.start_time >= self.end_time:
                errors["end_time"] = ["Start time must be before end time."]
        else:
            # For all-day unavailability, clear the time fields
            self.start_time = None
            self.end_time = None

        # Check for overlapping unavailability on the same date
        if self.lawyer_id and self.date:
            overlapping = Unavailability.objects.filter(
                lawyer=self.lawyer, date=self.date
            ).exclude(pk=self.pk)

            for unavail in overlapping:
                if self.is_all_day or unavail.is_all_day:
                    errors.setdefault("non_field_errors", []).append(
                        "Cannot have overlapping unavailability on the same date."
                    )
                    break
                elif (
                    self.start_time
                    and self.end_time
                    and unavail.start_time
                    and unavail.end_time
                    and self.start_time < unavail.end_time
                    and self.end_time > unavail.start_time
                ):
                    if "start_time" not in errors:
                        errors["start_time"] = []
                    errors["start_time"].append(
                        f"This unavailability overlaps with existing entry: "
                        f"{unavail.start_time}-{unavail.end_time}"
                    )
                    break

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def duration_hours(self):
        """Calculate duration in hours"""
        if self.is_all_day:
            return 24
        if self.start_time and self.end_time:
            start = datetime.combine(datetime.today(), self.start_time)
            end = datetime.combine(datetime.today(), self.end_time)
            return (end - start).total_seconds() / 3600
        return 0
