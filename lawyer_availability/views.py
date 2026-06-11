from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.serializers import ValidationError

from lawyer.models import LawyerProfile
from lawyer.permissions import (
    IsAuthenticatedReadOrLawyerWrite,
    IsLawyerVendor,
)

from .models import Availability, Unavailability
from .serializers import (
    AvailabilityBulkCreateSerializer,
    AvailabilityCreateUpdateSerializer,
    AvailabilitySerializer,
    UnavailabilityCreateUpdateSerializer,
    UnavailabilitySerializer,
)


# AVAILABILITY VIEWS
class AvailabilityListCreateView(generics.ListCreateAPIView):
    """
    List and create availability slots for lawyers
    - GET: Any authenticated user can view lawyer availability
    - POST: Only lawyer vendors can create availability
    """

    permission_classes = [IsAuthenticatedReadOrLawyerWrite]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return AvailabilityCreateUpdateSerializer
        return AvailabilitySerializer

    def get_queryset(self):
        lawyer_id = self.request.query_params.get("lawyer_id")

        if lawyer_id:
            # Any authenticated user can view specific lawyer's availability
            try:
                lawyer_profile = LawyerProfile.objects.get(id=lawyer_id)
                queryset = Availability.objects.filter(lawyer=lawyer_profile)
            except LawyerProfile.DoesNotExist:
                return Availability.objects.none()
        else:
            # If no lawyer_id specified:
            # - For lawyers: show their own availability
            # - For non-lawyers: return empty queryset (they must specify lawyer_id)
            if (
                hasattr(self.request.user, "vendorprofile")
                and self.request.user.vendorprofile.category
                and self.request.user.vendorprofile.category.name == "Lawyer"
            ):
                try:
                    lawyer_profile = LawyerProfile.objects.get(
                        vendor_profile__user=self.request.user
                    )
                    queryset = Availability.objects.filter(lawyer=lawyer_profile)
                except LawyerProfile.DoesNotExist:
                    return Availability.objects.none()
            else:
                # Non-lawyer users must specify lawyer_id
                return Availability.objects.none()

        # Apply optional filters
        day_of_week = self.request.query_params.get("day_of_week")
        if day_of_week is not None:
            queryset = queryset.filter(day_of_week=day_of_week)

        is_active = self.request.query_params.get("is_active")
        if is_active is not None:
            val = is_active.strip().lower()
            if val not in {"true", "1", "yes", "false", "0", "no"}:
                raise ValidationError(
                    {"is_active": "Must be one of true/false/1/0/yes/no."}
                )
            queryset = queryset.filter(is_active=val in {"true", "1", "yes"})

        return queryset.order_by("day_of_week", "start_time")

    def perform_create(self, serializer):
        try:
            lawyer_profile = LawyerProfile.objects.get(
                vendor_profile__user=self.request.user
            )
            try:
                serializer.save(lawyer=lawyer_profile)
            except DjangoValidationError as e:
                error_dict = {}
                if hasattr(e, "error_dict"):
                    for field, errors in e.error_dict.items():
                        error_dict[field] = [str(error) for error in errors]
                elif hasattr(e, "error_list"):
                    error_dict["non_field_errors"] = [
                        str(error) for error in e.error_list
                    ]
                else:
                    error_dict["non_field_errors"] = [str(e)]
                raise ValidationError(error_dict)
        except LawyerProfile.DoesNotExist:
            raise permissions.PermissionDenied(
                "Lawyer profile not found for this user."
            )


class AvailabilityDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update or delete a specific availability slot
    - GET: Any authenticated user can view
    - PUT/PATCH/DELETE: Only the owner lawyer can modify
    """

    permission_classes = [IsAuthenticatedReadOrLawyerWrite]

    def get_serializer_class(self):
        if self.request.method == "GET":
            return AvailabilitySerializer
        return AvailabilityCreateUpdateSerializer

    def get_queryset(self):
        return Availability.objects.all()

    def perform_update(self, serializer):
        """Handle Django ValidationError during updates"""
        try:
            serializer.save()
        except DjangoValidationError as e:
            error_dict = {}
            if hasattr(e, "error_dict"):
                for field, errors in e.error_dict.items():
                    error_dict[field] = [str(error) for error in errors]
            elif hasattr(e, "error_list"):
                error_dict["non_field_errors"] = [str(error) for error in e.error_list]
            else:
                error_dict["non_field_errors"] = [str(e)]
            raise ValidationError(error_dict)


@api_view(["POST"])
@permission_classes([IsLawyerVendor])
def bulk_create_availability(request):
    """
    Create availability slots for multiple days at once with offering
    POST /api/lawyer/availability/bulk-create/
    Body: {
        "days_of_week": [1, 2, 3],
        "start_time": "09:00",
        "end_time": "17:00",
        "offering": "offering-uuid",
        "is_active": true
    }
    """
    try:
        lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=request.user)
    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Lawyer profile not found for this user."},
            status=status.HTTP_404_NOT_FOUND,
        )

    serializer = AvailabilityBulkCreateSerializer(
        data=request.data, context={"request": request}
    )
    if serializer.is_valid():
        validated_data = serializer.validated_data
        created_slots = []
        errors = []

        with transaction.atomic():
            for day_of_week in validated_data["days_of_week"]:
                try:
                    availability, created = Availability.objects.get_or_create(
                        lawyer=lawyer_profile,
                        day_of_week=day_of_week,
                        start_time=validated_data["start_time"],
                        end_time=validated_data["end_time"],
                        offering=validated_data["offering"],  # NEW: Include offering
                        defaults={"is_active": validated_data.get("is_active", True)},
                    )
                    if created:
                        created_slots.append(AvailabilitySerializer(availability).data)
                    else:
                        errors.append(
                            f"Availability for {availability.get_day_of_week_display()} with {availability.offering.name} already exists"
                        )
                except DjangoValidationError as e:
                    errors.append(
                        f"Error creating availability for day {day_of_week}: {str(e)}"
                    )
                except Exception as e:
                    errors.append(
                        f"Error creating availability for day {day_of_week}: {str(e)}"
                    )

        return Response(
            {
                "created_slots": created_slots,
                "errors": errors,
                "total_created": len(created_slots),
            },
            status=(
                status.HTTP_201_CREATED
                if created_slots
                else status.HTTP_400_BAD_REQUEST
            ),
        )

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def weekly_availability_view(request):
    """
    Get availability organized by days of the week
    GET /api/lawyer/availability/weekly/?lawyer_id=<uuid>
    """
    lawyer_id = request.query_params.get("lawyer_id")

    if lawyer_id:
        # Any authenticated user can view specific lawyer's availability
        try:
            lawyer_profile = LawyerProfile.objects.get(id=lawyer_id)
        except LawyerProfile.DoesNotExist:
            return Response(
                {"error": "Lawyer profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
    else:
        # If no lawyer_id, try to get authenticated lawyer's own availability
        if (
            hasattr(request.user, "vendorprofile")
            and request.user.vendorprofile.category
            and request.user.vendorprofile.category.name == "Lawyer"
        ):
            try:
                lawyer_profile = LawyerProfile.objects.get(
                    vendor_profile__user=request.user
                )
            except LawyerProfile.DoesNotExist:
                return Response(
                    {"error": "Lawyer profile not found for this user."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            return Response(
                {"error": "lawyer_id parameter is required for non-lawyer users."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Get all availability slots
    availability_slots = (
        Availability.objects.filter(lawyer=lawyer_profile, is_active=True)
        .select_related("offering", "lawyer__vendor_profile")
        .order_by("day_of_week", "start_time")
    )

    # Organize by day of week
    weekly_data = {
        "monday": [],
        "tuesday": [],
        "wednesday": [],
        "thursday": [],
        "friday": [],
        "saturday": [],
        "sunday": [],
    }

    day_names = [
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]

    for slot in availability_slots:
        day_name = day_names[slot.day_of_week]
        weekly_data[day_name].append(AvailabilitySerializer(slot).data)

    return Response(weekly_data, status=status.HTTP_200_OK)


# UNAVAILABILITY VIEWS
class UnavailabilityListCreateView(generics.ListCreateAPIView):
    """
    List and create unavailability entries for lawyers
    - GET: Any authenticated user can view lawyer unavailability
    - POST: Only lawyer vendors can create unavailability
    """

    permission_classes = [IsAuthenticatedReadOrLawyerWrite]

    def get_serializer_class(self):
        if self.request.method == "POST":
            return UnavailabilityCreateUpdateSerializer
        return UnavailabilitySerializer

    def get_queryset(self):
        lawyer_id = self.request.query_params.get("lawyer_id")

        if lawyer_id:
            # Any authenticated user can view specific lawyer's unavailability
            try:
                lawyer_profile = LawyerProfile.objects.get(id=lawyer_id)
                queryset = Unavailability.objects.filter(lawyer=lawyer_profile)
            except LawyerProfile.DoesNotExist:
                return Unavailability.objects.none()
        else:
            # If no lawyer_id specified:
            # - For lawyers: show their own unavailability
            # - For non-lawyers: return empty queryset (they must specify lawyer_id)
            if (
                hasattr(self.request.user, "vendorprofile")
                and self.request.user.vendorprofile.category
                and self.request.user.vendorprofile.category.name == "Lawyer"
            ):
                try:
                    lawyer_profile = LawyerProfile.objects.get(
                        vendor_profile__user=self.request.user
                    )
                    queryset = Unavailability.objects.filter(lawyer=lawyer_profile)
                except LawyerProfile.DoesNotExist:
                    return Unavailability.objects.none()
            else:
                # Non-lawyer users must specify lawyer_id
                return Unavailability.objects.none()

        # Apply optional filters
        date_from = self.request.query_params.get("date_from")
        if date_from:
            try:
                df = datetime.strptime(date_from, "%Y-%m-%d").date()
            except ValueError:
                raise ValidationError({"date_from": "Invalid format. Use YYYY-MM-DD."})
            queryset = queryset.filter(date__gte=df)

        date_to = self.request.query_params.get("date_to")
        if date_to:
            try:
                dt = datetime.strptime(date_to, "%Y-%m-%d").date()
            except ValueError:
                raise ValidationError({"date_to": "Invalid format. Use YYYY-MM-DD."})
            queryset = queryset.filter(date__lte=dt)

        unavailability_type = self.request.query_params.get("type")
        if unavailability_type:
            queryset = queryset.filter(unavailability_type=unavailability_type)

        is_all_day = self.request.query_params.get("is_all_day")
        if is_all_day is not None:
            val = is_all_day.strip().lower()
            if val not in {"true", "1", "yes", "false", "0", "no"}:

                raise ValidationError(
                    {"is_all_day": "Must be one of true/false/1/0/yes/no."}
                )
            queryset = queryset.filter(is_all_day=val in {"true", "1", "yes"})

        # Default to showing future unavailability only
        show_past = self.request.query_params.get("show_past", "false")
        if show_past.lower() not in ["true", "1", "yes"]:
            queryset = queryset.filter(date__gte=timezone.now().date())

        return queryset.order_by("date", "start_time")

    def perform_create(self, serializer):
        try:
            lawyer_profile = LawyerProfile.objects.get(
                vendor_profile__user=self.request.user
            )
            try:
                serializer.save(lawyer=lawyer_profile)
            except DjangoValidationError as e:
                error_dict = {}
                if hasattr(e, "error_dict"):
                    for field, errors in e.error_dict.items():
                        error_dict[field] = [str(error) for error in errors]
                elif hasattr(e, "error_list"):
                    error_dict["non_field_errors"] = [
                        str(error) for error in e.error_list
                    ]
                else:
                    error_dict["non_field_errors"] = [str(e)]
                raise ValidationError(error_dict)
        except LawyerProfile.DoesNotExist:
            raise permissions.PermissionDenied(
                "Lawyer profile not found for this user."
            )


class UnavailabilityDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Retrieve, update or delete a specific unavailability entry
    - GET: Any authenticated user can view
    - PUT/PATCH/DELETE: Only the owner lawyer can modify
    """

    permission_classes = [IsAuthenticatedReadOrLawyerWrite]

    def get_serializer_class(self):
        if self.request.method == "GET":
            return UnavailabilitySerializer
        return UnavailabilityCreateUpdateSerializer

    def get_queryset(self):
        return Unavailability.objects.all()

    def perform_update(self, serializer):
        """Handle Django ValidationError during updates"""
        try:
            serializer.save()
        except DjangoValidationError as e:
            error_dict = {}
            if hasattr(e, "error_dict"):
                for field, errors in e.error_dict.items():
                    error_dict[field] = [str(error) for error in errors]
            elif hasattr(e, "error_list"):
                error_dict["non_field_errors"] = [str(error) for error in e.error_list]
            else:
                error_dict["non_field_errors"] = [str(e)]
            raise ValidationError(error_dict)


@api_view(["GET"])
@permission_classes([IsLawyerVendor])
def unavailability_stats(request):
    """
    Get statistics about unavailability (only for lawyer owners)
    GET /api/lawyer/unavailability/stats/
    """
    try:
        lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=request.user)
    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Lawyer profile not found for this user."},
            status=status.HTTP_404_NOT_FOUND,
        )

    today = timezone.now().date()

    # Get all unavailability entries
    all_unavailability = Unavailability.objects.filter(lawyer=lawyer_profile)
    upcoming_unavailability = all_unavailability.filter(date__gte=today)

    # Count by type
    type_counts = all_unavailability.values("unavailability_type").annotate(
        count=Count("id")
    )
    by_type = {item["unavailability_type"]: item["count"] for item in type_counts}

    # Get next unavailability
    next_unavailability = upcoming_unavailability.order_by("date", "start_time").first()

    stats = {
        "total_unavailable_days": all_unavailability.count(),
        "upcoming_unavailable_days": upcoming_unavailability.count(),
        "by_type": by_type,
        "next_unavailability": (
            UnavailabilitySerializer(next_unavailability).data
            if next_unavailability
            else None
        ),
    }

    return Response(stats, status=status.HTTP_200_OK)


# AVAILABILITY CHECKING VIEWS


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def check_availability_for_date(request, lawyer_id, date):
    """
    Check availability for a specific lawyer on a specific date with offering details
    GET /api/lawyer/{lawyer_id}/availability/{date}/
    REQUIRES AUTHENTICATION - any authenticated user can check
    """
    try:
        # Parse the date
        check_date = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        return Response(
            {"error": "Invalid date format. Use YYYY-MM-DD."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        lawyer_profile = LawyerProfile.objects.get(id=lawyer_id)
    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Lawyer profile not found."}, status=status.HTTP_404_NOT_FOUND
        )

    # Get availability for the date with offering details
    available_slots = lawyer_profile.get_availability_for_date_with_offerings(
        check_date
    )

    response_data = {
        "date": check_date,
        "available_slots": available_slots,
        "is_available": len(available_slots) > 0,
        "total_slots": len(available_slots),
    }

    return Response(response_data, status=status.HTTP_200_OK)


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def check_time_availability(request):
    """
    Check if lawyer is available at specific date and time, optionally for specific offering
    POST /api/lawyer/availability/check-time/
    REQUIRES AUTHENTICATION - any authenticated user can check
    Body: {
        "lawyer_id": "uuid",
        "date": "2025-07-10",
        "start_time": "09:00",
        "end_time": "10:00",
        "offering_id": "uuid" (optional)
    }
    """
    lawyer_id = request.data.get("lawyer_id")
    if not lawyer_id:
        return Response(
            {"error": "lawyer_id is required."}, status=status.HTTP_400_BAD_REQUEST
        )

    try:
        lawyer_profile = LawyerProfile.objects.get(id=lawyer_id)
    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Lawyer profile not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Validate required fields
    required_fields = ["date", "start_time", "end_time"]
    for field in required_fields:
        if field not in request.data:
            return Response(
                {"error": f"'{field}' is required."}, status=status.HTTP_400_BAD_REQUEST
            )

    try:
        # Parse input data
        check_date = datetime.strptime(request.data["date"], "%Y-%m-%d").date()
        start_time = datetime.strptime(request.data["start_time"], "%H:%M").time()
        end_time = datetime.strptime(request.data["end_time"], "%H:%M").time()
    except ValueError as e:
        return Response(
            {"error": f"Invalid date/time format: {str(e)}"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Optional offering filter
    offering_id = request.data.get("offering_id")

    if start_time >= end_time:
        return Response(
            {"error": "'end_time' must be after 'start_time'."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Check availability using the LawyerProfile method
    is_available = lawyer_profile.is_available_at_time_with_offering(
        check_date, start_time, end_time, offering_id
    )

    response_data = {
        "date": check_date,
        "start_time": start_time,
        "end_time": end_time,
        "offering_id": offering_id,
        "is_available": is_available,
    }

    return Response(response_data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def availability_calendar(request):
    """
    Get availability calendar for a date range
    GET /api/lawyer/availability/calendar/?lawyer_id=<uuid>&date_from=2025-07-01&date_to=2025-07-31
    REQUIRES AUTHENTICATION - any authenticated user can view
    """
    lawyer_id = request.query_params.get("lawyer_id")

    if lawyer_id:
        # Any authenticated user can view specific lawyer's calendar
        try:
            lawyer_profile = LawyerProfile.objects.get(id=lawyer_id)
        except LawyerProfile.DoesNotExist:
            return Response(
                {"error": "Lawyer profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
    else:
        # If no lawyer_id, try to get authenticated lawyer's own calendar
        if (
            hasattr(request.user, "vendorprofile")
            and request.user.vendorprofile.category
            and request.user.vendorprofile.category.name == "Lawyer"
        ):
            try:
                lawyer_profile = LawyerProfile.objects.get(
                    vendor_profile__user=request.user
                )
            except LawyerProfile.DoesNotExist:
                return Response(
                    {"error": "Lawyer profile not found for this user."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            return Response(
                {"error": "lawyer_id parameter is required for non-lawyer users."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Get date range parameters
    date_from_str = request.query_params.get("date_from")
    date_to_str = request.query_params.get("date_to")

    if not date_from_str or not date_to_str:
        return Response(
            {"error": "Both 'date_from' and 'date_to' parameters are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    try:
        date_from = datetime.strptime(date_from_str, "%Y-%m-%d").date()
        date_to = datetime.strptime(date_to_str, "%Y-%m-%d").date()
    except ValueError:
        return Response(
            {"error": "Invalid date format. Use YYYY-MM-DD."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if date_to < date_from:
        return Response(
            {"error": "'date_to' must be after 'date_from'."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Limit the range to prevent performance issues
    if (date_to - date_from).days > 90:
        return Response(
            {"error": "Date range cannot exceed 90 days."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Generate calendar data using LawyerProfile method
    calendar_data = []
    current_date = date_from

    while current_date <= date_to:
        available_slots = lawyer_profile.get_availability_for_date_with_offerings(
            current_date
        )
        total_hours = sum(Decimal(str(slot["duration"])) for slot in available_slots)
        total_hours = total_hours.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        calendar_data.append(
            {
                "date": current_date,
                "available_slots": available_slots,
                "is_available": len(available_slots) > 0,
                "total_hours": total_hours,
            }
        )
        current_date += timedelta(days=1)

    return Response(
        {"date_from": date_from, "date_to": date_to, "calendar": calendar_data},
        status=status.HTTP_200_OK,
    )


# UTILITY VIEWS (LAWYER ONLY)
@api_view(["DELETE"])
@permission_classes([IsLawyerVendor])
def clear_all_availability(request):
    """
    Clear all availability slots for the authenticated lawyer
    DELETE /api/lawyer/availability/clear-all/
    """
    try:
        lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=request.user)
    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Lawyer profile not found for this user."},
            status=status.HTTP_404_NOT_FOUND,
        )

    deleted_count = Availability.objects.filter(lawyer=lawyer_profile).delete()[0]

    return Response(
        {
            "message": f"Successfully deleted {deleted_count} availability slots.",
            "deleted_count": deleted_count,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["DELETE"])
@permission_classes([IsLawyerVendor])
def clear_past_unavailability(request):
    """
    Clear all past unavailability entries for the authenticated lawyer
    DELETE /api/lawyer/unavailability/clear-past/
    """
    try:
        lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=request.user)
    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Lawyer profile not found for this user."},
            status=status.HTTP_404_NOT_FOUND,
        )

    today = timezone.now().date()
    deleted_count = Unavailability.objects.filter(
        lawyer=lawyer_profile, date__lt=today
    ).delete()[0]

    return Response(
        {
            "message": f"Successfully deleted {deleted_count} past unavailability entries.",
            "deleted_count": deleted_count,
        },
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsLawyerVendor])
def copy_availability_template(request):
    """
    Copy availability from one day to other days (with same offering)
    POST /api/lawyer/availability/copy-template/
    Body: {
        "source_day": 1,  // Monday
        "target_days": [2, 3, 4],  // Tuesday, Wednesday, Thursday
        "offering_id": "uuid" (optional - if not provided, copies all offerings)
    }
    """
    try:
        lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=request.user)
    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Lawyer profile not found for this user."},
            status=status.HTTP_404_NOT_FOUND,
        )

    source_day = request.data.get("source_day")
    target_days = request.data.get("target_days", [])
    offering_id = request.data.get("offering_id")

    if source_day is None or not target_days:
        return Response(
            {"error": "Both 'source_day' and 'target_days' are required."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if not (0 <= source_day <= 6):
        return Response(
            {"error": "source_day must be between 0 (Monday) and 6 (Sunday)."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    for day in target_days:
        if not (0 <= day <= 6):
            return Response(
                {
                    "error": f"target_day {day} must be between 0 (Monday) and 6 (Sunday)."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Get source availability (with optional offering filter)
    source_query = {
        "lawyer": lawyer_profile,
        "day_of_week": source_day,
        "is_active": True,
    }

    if offering_id:
        source_query["offering_id"] = offering_id

    source_availability = Availability.objects.filter(**source_query)

    if not source_availability.exists():
        error_msg = f"No active availability found for source day {source_day}"
        if offering_id:
            error_msg += f" with the specified offering"
        return Response(
            {"error": error_msg},
            status=status.HTTP_400_BAD_REQUEST,
        )

    created_slots = []
    errors = []

    with transaction.atomic():
        for target_day in target_days:
            for slot in source_availability:
                try:
                    new_slot, created = Availability.objects.get_or_create(
                        lawyer=lawyer_profile,
                        day_of_week=target_day,
                        start_time=slot.start_time,
                        end_time=slot.end_time,
                        offering=slot.offering,  # NEW: Include offering
                        defaults={"is_active": slot.is_active},
                    )
                    if created:
                        created_slots.append(AvailabilitySerializer(new_slot).data)
                    else:
                        day_name = dict(Availability.WEEKDAYS)[target_day]
                        errors.append(
                            f"Slot {slot.start_time}-{slot.end_time} with {slot.offering.name} already exists for {day_name}"
                        )
                except DjangoValidationError as e:
                    errors.append(f"Error copying to day {target_day}: {str(e)}")
                except Exception as e:
                    errors.append(f"Error copying to day {target_day}: {str(e)}")

    return Response(
        {
            "created_slots": created_slots,
            "errors": errors,
            "total_created": len(created_slots),
        },
        status=(
            status.HTTP_201_CREATED if created_slots else status.HTTP_400_BAD_REQUEST
        ),
    )


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def availability_types_info(request):
    """
    Get information about availability types and day choices
    GET /api/lawyer/availability/types-info/
    PUBLIC ENDPOINT - No authentication required
    """
    weekdays = [{"value": day[0], "label": day[1]} for day in Availability.WEEKDAYS]

    unavailability_types = [
        {"value": choice[0], "label": choice[1]}
        for choice in Unavailability.UNAVAILABILITY_TYPES
    ]

    return Response(
        {
            "weekdays": weekdays,
            "unavailability_types": unavailability_types,
            "time_format": "HH:MM (24-hour format)",
            "date_format": "YYYY-MM-DD",
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def availability_grouped_by_offering(request):
    """
    Get availability organized by offerings
    GET /api/lawyer/availability/by-offering/?lawyer_id=<uuid>
    """
    lawyer_id = request.query_params.get("lawyer_id")

    if lawyer_id:
        # Any authenticated user can view specific lawyer's availability
        try:
            lawyer_profile = LawyerProfile.objects.get(id=lawyer_id)
        except LawyerProfile.DoesNotExist:
            return Response(
                {"error": "Lawyer profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
    else:
        # If no lawyer_id, try to get authenticated lawyer's own availability
        if (
            hasattr(request.user, "vendorprofile")
            and request.user.vendorprofile.category
            and request.user.vendorprofile.category.name == "Lawyer"
        ):
            try:
                lawyer_profile = LawyerProfile.objects.get(
                    vendor_profile__user=request.user
                )
            except LawyerProfile.DoesNotExist:
                return Response(
                    {"error": "Lawyer profile not found for this user."},
                    status=status.HTTP_404_NOT_FOUND,
                )
        else:
            return Response(
                {"error": "lawyer_id parameter is required for non-lawyer users."},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # Get availability stats by offering
    offering_stats = lawyer_profile.get_availability_stats_by_offering()

    # Get detailed availability for each offering
    grouped_data = []

    for offering in lawyer_profile.offerings.filter(is_active=True):
        availability_slots = lawyer_profile.get_availability_by_offering(offering.id)

        grouped_data.append(
            {
                "offering_id": offering.id,
                "offering_name": offering.name,
                "offering_price_per_30min": offering.price_per_30min,
                "availability_slots": AvailabilitySerializer(
                    availability_slots, many=True
                ).data,
                "total_slots": availability_slots.count(),
                "total_hours": sum(slot.duration_hours for slot in availability_slots),
            }
        )

    return Response(
        {
            "lawyer_id": lawyer_profile.id,
            "offerings_with_availability": grouped_data,
            "summary": offering_stats,
        },
        status=status.HTTP_200_OK,
    )
