from datetime import time

from django.utils import timezone
from rest_framework import serializers

from lawyer.models import LawyerOffering

from .models import Availability, Unavailability


class AvailabilitySerializer(serializers.ModelSerializer):
    """
    Serializer for lawyer availability management with offering details
    """

    day_of_week_display = serializers.CharField(
        source="get_day_of_week_display", read_only=True
    )
    duration_hours = serializers.ReadOnlyField()
    duration_minutes = serializers.ReadOnlyField()

    offering_name = serializers.CharField(source="offering.name", read_only=True)
    offering_price_per_30min = serializers.DecimalField(
        source="offering.price_per_30min",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    slot_price = serializers.SerializerMethodField()
    slot_price_breakdown = serializers.SerializerMethodField()

    class Meta:
        model = Availability
        fields = [
            "id",
            "lawyer",
            "day_of_week",
            "day_of_week_display",
            "start_time",
            "end_time",
            "offering",
            "offering_name",
            "offering_price_per_30min",
            "is_active",
            "duration_hours",
            "duration_minutes",
            "slot_price",
            "slot_price_breakdown",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def get_slot_price(self, obj):
        """Get price for this availability slot's duration"""
        return obj.get_price_for_duration()

    def get_slot_price_breakdown(self, obj):
        """Get complete price breakdown for this availability slot"""
        return obj.get_price_breakdown()

    def validate(self, attrs):
        """Validate availability data"""
        start_time = attrs.get("start_time")
        end_time = attrs.get("end_time")
        offering = attrs.get("offering")
        lawyer = attrs.get("lawyer")

        if start_time and end_time:
            if start_time >= end_time:
                raise serializers.ValidationError(
                    {"end_time": "End time must be after start time."}
                )

        if offering and lawyer:
            if offering.lawyer_profile != lawyer:
                raise serializers.ValidationError(
                    {"offering": "Offering must belong to the same lawyer."}
                )

        return attrs

    def validate_start_time(self, value):
        """Validate start time is reasonable"""
        if value < time(6, 0) or value > time(22, 0):
            raise serializers.ValidationError(
                "Start time should be between 06:00 and 22:00"
            )
        return value

    def validate_end_time(self, value):
        """Validate end time is reasonable"""
        if value < time(7, 0) or value > time(23, 59):
            raise serializers.ValidationError(
                "End time should be between 07:00 and 23:59"
            )
        return value


class AvailabilityCreateUpdateSerializer(AvailabilitySerializer):
    """
    Serializer for creating/updating availability (excludes lawyer field)
    """

    class Meta(AvailabilitySerializer.Meta):
        fields = [
            "id",
            "day_of_week",
            "day_of_week_display",
            "start_time",
            "end_time",
            "offering",
            "offering_name",
            "offering_price_per_30min",
            "is_active",
            "duration_hours",
            "duration_minutes",
            "slot_price",
            "slot_price_breakdown",
            "created_at",
            "updated_at",
        ]

    def validate_offering(self, value):
        """Validate that offering belongs to the requesting lawyer"""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            try:
                from lawyer.models import LawyerProfile

                lawyer_profile = LawyerProfile.objects.get(
                    vendor_profile__user=request.user
                )
                if value.lawyer_profile != lawyer_profile:
                    raise serializers.ValidationError(
                        "You can only use your own offerings."
                    )
            except LawyerProfile.DoesNotExist:
                raise serializers.ValidationError(
                    "Lawyer profile not found for this user."
                )
        return value


class UnavailabilitySerializer(serializers.ModelSerializer):
    """
    Serializer for lawyer unavailability management
    """

    unavailability_type_display = serializers.CharField(
        source="get_unavailability_type_display", read_only=True
    )
    duration_hours = serializers.ReadOnlyField()

    class Meta:
        model = Unavailability
        fields = [
            "id",
            "lawyer",
            "date",
            "start_time",
            "end_time",
            "is_all_day",
            "unavailability_type",
            "unavailability_type_display",
            "reason",
            "duration_hours",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]

    def validate(self, attrs):
        """Validate unavailability data"""
        date = attrs.get("date")
        start_time = attrs.get("start_time")
        end_time = attrs.get("end_time")
        is_all_day = attrs.get("is_all_day", False)

        # Validate date is not in the past
        if date and date < timezone.now().date():
            raise serializers.ValidationError(
                {"date": "Cannot create unavailability for past dates."}
            )

        # Validate time logic for non-all-day entries
        if not is_all_day:
            if not start_time or not end_time:
                raise serializers.ValidationError(
                    {
                        "non_field_errors": [
                            "Start time and end time are required when not all-day."
                        ]
                    }
                )
            if start_time >= end_time:
                raise serializers.ValidationError(
                    {"end_time": "End time must be after start time."}
                )

        return attrs

    def validate_date(self, value):
        """Validate date is not too far in the future"""
        if value > timezone.now().date().replace(year=timezone.now().year + 2):
            raise serializers.ValidationError(
                "Cannot create unavailability more than 2 years in advance."
            )
        return value


class UnavailabilityCreateUpdateSerializer(UnavailabilitySerializer):
    """
    Serializer for creating/updating unavailability (excludes lawyer field)
    """

    class Meta(UnavailabilitySerializer.Meta):
        fields = [
            "id",
            "date",
            "start_time",
            "end_time",
            "is_all_day",
            "unavailability_type",
            "unavailability_type_display",
            "reason",
            "duration_hours",
            "created_at",
            "updated_at",
        ]


class AvailabilityBulkCreateSerializer(serializers.Serializer):
    """
    Serializer for bulk creating availability across multiple days with offering
    """

    days_of_week = serializers.ListField(
        child=serializers.IntegerField(min_value=0, max_value=6),
        min_length=1,
        max_length=7,
    )
    start_time = serializers.TimeField()
    end_time = serializers.TimeField()
    offering = serializers.PrimaryKeyRelatedField(queryset=LawyerOffering.objects.all())
    is_active = serializers.BooleanField(default=True)

    def validate(self, attrs):
        """Validate bulk availability data"""
        start_time = attrs.get("start_time")
        end_time = attrs.get("end_time")

        if start_time >= end_time:
            raise serializers.ValidationError(
                {"end_time": "End time must be after start time."}
            )

        return attrs

    def validate_days_of_week(self, value):
        """Ensure no duplicate days"""
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Duplicate days of week not allowed.")
        return value

    def validate_offering(self, value):
        """Validate that offering belongs to the requesting lawyer"""
        request = self.context.get("request")
        if request and hasattr(request, "user"):
            try:
                from lawyer.models import LawyerProfile

                lawyer_profile = LawyerProfile.objects.get(
                    vendor_profile__user=request.user
                )
                if value.lawyer_profile != lawyer_profile:
                    raise serializers.ValidationError(
                        "You can only use your own offerings."
                    )
            except LawyerProfile.DoesNotExist:
                raise serializers.ValidationError(
                    "Lawyer profile not found for this user."
                )
        return value
