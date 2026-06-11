from decimal import Decimal

from django.db.models import Avg, Count, Max, Min, Q
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from profiles.models import VendorProfile

from .models import (
    LawyerCategory,
    LawyerOffering,
    LawyerProfile,
    LawyerSubcategory,
    OfferingType,
)
from .permissions import IsLawyerVendor, IsOwnerLawyerVendor
from .serializers import (
    LawyerCategorySerializer,
    LawyerOfferingCreateUpdateSerializer,
    LawyerOfferingListSerializer,
    LawyerOfferingWithServiceTypesSerializer,
    LawyerProfileSerializer,
    LawyerProfileStepSerializer,
    LawyerSubcategorySerializer,
    OfferingTypeCreateUpdateSerializer,
    OfferingTypeSerializer,
    PriceCalculationSerializer,
    PublicLawyerOfferingSerializer,
)


class LawyerCategoryListView(generics.ListAPIView):
    """List all lawyer categories with their subcategories"""

    queryset = LawyerCategory.objects.all()
    serializer_class = LawyerCategorySerializer
    permission_classes = [permissions.AllowAny]


class LawyerCategoryDetailView(generics.RetrieveAPIView):
    """Get a specific lawyer category with its subcategories"""

    queryset = LawyerCategory.objects.all()
    serializer_class = LawyerCategorySerializer
    permission_classes = [permissions.AllowAny]


class LawyerSubcategoryListView(generics.ListAPIView):
    """List all lawyer subcategories, optionally filtered by category"""

    queryset = LawyerSubcategory.objects.all()
    serializer_class = LawyerSubcategorySerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = super().get_queryset()
        category_id = self.request.query_params.get("category", None)
        if category_id:
            queryset = queryset.filter(lawyercategory_id=category_id)
        return queryset


class LawyerSubcategoryDetailView(generics.RetrieveAPIView):
    """Get a specific lawyer subcategory"""

    queryset = LawyerSubcategory.objects.all()
    serializer_class = LawyerSubcategorySerializer
    permission_classes = [permissions.AllowAny]


class LawyerProfileListView(generics.ListAPIView):
    """Lawyer Profile List View"""

    queryset = LawyerProfile.objects.all()
    serializer_class = LawyerProfileSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .prefetch_related(
                "lawyercategories",
                "lawyersubcategories",
                "offerings",
            )
        )

        if not self.request.user.is_staff:
            queryset = queryset.filter(vendor_profile__user=self.request.user)

        # Optional filters
        kyc_status = self.request.query_params.get("kyc_status", None)
        if kyc_status:
            queryset = queryset.filter(kyc_verification_status=kyc_status)

        return queryset


class LawyerProfileDetailView(generics.RetrieveUpdateAPIView):
    """Lawyer Profile Detail View - Read-only for authenticated users, editable for owner"""

    queryset = LawyerProfile.objects.all()
    serializer_class = LawyerProfileSerializer

    def get_permissions(self):
        """
        Instantiate and return the list of permissions that this view requires.
        """
        if self.request.method in ["PUT", "PATCH"]:
            # Only owner can update
            permission_classes = [IsOwnerLawyerVendor]
        else:
            # Anyone authenticated can read
            permission_classes = [IsAuthenticated]

        return [permission() for permission in permission_classes]

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .prefetch_related(
                "lawyercategories",
                "lawyersubcategories",
                "offerings",
            )
        )

        # For non-staff users doing update operations, filter by ownership
        if self.request.method in ["PUT", "PATCH"]:
            queryset = queryset.filter(vendor_profile__user=self.request.user)

        # For read operations, don't filter - allow viewing any profile
        return queryset

    def perform_update(self, serializer):
        # Remove commission_percentage if user is not staff
        if (
            "commission_percentage" in serializer.validated_data
            and not self.request.user.is_staff
        ):
            serializer.validated_data.pop("commission_percentage")

        serializer.save()

    def update(self, request, *args, **kwargs):
        """Override to ensure only owners can update"""
        instance = self.get_object()

        # Double-check ownership for non-staff users
        if instance.vendor_profile.user != request.user:
            return Response(
                {"error": "You can only update your own lawyer profile."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return super().update(request, *args, **kwargs)


class LawyerOfferingListCreateView(generics.ListCreateAPIView):
    """
    API View to list and create pricing plans (LawyerOffering) - Only for lawyers
    LawyerOffering now represents pricing plans (Standard, Weekend, Premium, etc.)
    """

    queryset = LawyerOffering.objects.all()
    permission_classes = [IsLawyerVendor]

    def get_serializer_class(self):
        if self.request.method == "GET":
            return LawyerOfferingListSerializer
        return LawyerOfferingCreateUpdateSerializer

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("lawyer_profile")
            .prefetch_related(
                "lawyer_profile__lawyercategories",
                "lawyer_profile__lawyersubcategories",
                "offering_types",
            )
        )

        # Filter by current user's lawyer profiles if not admin
        if not self.request.user.is_staff:
            queryset = queryset.filter(
                lawyer_profile__vendor_profile__user=self.request.user
            )

        # Optional filters
        lawyer_profile_id = self.request.query_params.get("lawyer_profile", None)
        if lawyer_profile_id:
            queryset = queryset.filter(lawyer_profile_id=lawyer_profile_id)

        is_active = self.request.query_params.get("is_active", None)
        if is_active is not None:
            is_active_bool = is_active.lower() in ["true", "1", "yes"]
            queryset = queryset.filter(is_active=is_active_bool)

        # Search by name
        search = self.request.query_params.get("search", None)
        if search:
            queryset = queryset.filter(name__icontains=search)

        # Price range filters
        min_price = self.request.query_params.get("min_price", None)
        if min_price:
            queryset = queryset.filter(price_per_30min__gte=min_price)

        max_price = self.request.query_params.get("max_price", None)
        if max_price:
            queryset = queryset.filter(price_per_30min__lte=max_price)

        return queryset.order_by("-created_at")

    def perform_create(self, serializer):
        try:
            lawyer_profile = LawyerProfile.objects.get(
                vendor_profile__user=self.request.user
            )
            serializer.save(lawyer_profile=lawyer_profile)
        except LawyerProfile.DoesNotExist:
            raise Exception("Lawyer profile not found for this user.")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        try:
            lawyer_profile = LawyerProfile.objects.get(
                vendor_profile__user=self.request.user
            )
            context["lawyer_profile"] = lawyer_profile
        except LawyerProfile.DoesNotExist:
            pass
        return context


class LawyerOfferingDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    API View to retrieve, update and delete pricing plans (LawyerOffering) - Only for lawyers
    """

    queryset = LawyerOffering.objects.all()
    permission_classes = [IsOwnerLawyerVendor]

    def get_serializer_class(self):
        if self.request.method == "GET":
            return LawyerOfferingWithServiceTypesSerializer
        return LawyerOfferingCreateUpdateSerializer

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("lawyer_profile")
            .prefetch_related(
                "lawyer_profile__lawyercategories",
                "lawyer_profile__lawyersubcategories",
                "offering_types",
            )
        )

        if not self.request.user.is_staff:
            queryset = queryset.filter(
                lawyer_profile__vendor_profile__user=self.request.user
            )

        return queryset

    def get_serializer_context(self):
        context = super().get_serializer_context()
        if self.get_object():
            context["lawyer_profile"] = self.get_object().lawyer_profile
        return context


class OfferingTypeListCreateView(generics.ListCreateAPIView):
    """
    API View to list and create service types for a specific pricing plan
    OfferingType now represents service delivery methods (physical/audio/video)
    """

    permission_classes = [IsLawyerVendor]

    def get_serializer_class(self):
        if self.request.method == "GET":
            return OfferingTypeSerializer
        return OfferingTypeCreateUpdateSerializer

    def get_queryset(self):
        offering_id = self.kwargs.get("offering_id")
        offering = get_object_or_404(LawyerOffering, id=offering_id)

        # Check if user owns the pricing plan
        if not self.request.user.is_staff:
            if offering.lawyer_profile.vendor_profile.user != self.request.user:
                raise permissions.PermissionDenied(
                    "You can only access service types for your own pricing plans."
                )

        return OfferingType.objects.filter(offering=offering)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        offering_id = self.kwargs.get("offering_id")
        offering = get_object_or_404(LawyerOffering, id=offering_id)
        context["offering"] = offering
        return context

    def perform_create(self, serializer):
        offering_id = self.kwargs.get("offering_id")
        offering = get_object_or_404(LawyerOffering, id=offering_id)

        # Check if user owns the pricing plan
        if not self.request.user.is_staff:
            if offering.lawyer_profile.vendor_profile.user != self.request.user:
                raise permissions.PermissionDenied(
                    "You can only create service types for your own pricing plans."
                )

        serializer.save(offering=offering)


class OfferingTypeDetailView(generics.RetrieveUpdateDestroyAPIView):
    """API View to retrieve, update and delete service types"""

    queryset = OfferingType.objects.all()
    permission_classes = [IsOwnerLawyerVendor]

    def get_serializer_class(self):
        if self.request.method == "GET":
            return OfferingTypeSerializer
        return OfferingTypeCreateUpdateSerializer

    def get_queryset(self):
        queryset = super().get_queryset().select_related("offering__lawyer_profile")

        if not self.request.user.is_staff:
            queryset = queryset.filter(
                offering__lawyer_profile__vendor_profile__user=self.request.user
            )

        return queryset


@api_view(["POST"])
@permission_classes([permissions.IsAuthenticated])
def calculate_appointment_price(request):
    """Calculate price for an appointment based on pricing plan, duration, and service type"""
    serializer = PriceCalculationSerializer(data=request.data)

    if serializer.is_valid():
        validated_data = serializer.validated_data
        pricing_plan = validated_data["pricing_plan"]
        service_type_obj = validated_data["service_type_obj"]
        duration_minutes = validated_data["duration_minutes"]

        # Calculate price breakdown
        price_breakdown = service_type_obj.get_price_breakdown(duration_minutes)

        response_data = {
            "pricing_plan_id": pricing_plan.id,
            "pricing_plan_name": pricing_plan.name,
            "service_type": service_type_obj.type,
            "service_type_display": service_type_obj.get_type_display(),
            "duration_minutes": duration_minutes,
            "base_price_per_30min": pricing_plan.price_per_30min,
            **price_breakdown,
        }

        return Response(response_data, status=status.HTTP_200_OK)

    return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


@api_view(["GET"])
@permission_classes([permissions.IsAuthenticated])
def get_pricing_plan_details(request, pricing_plan_id):
    """Get detailed pricing information for a specific pricing plan"""
    try:
        pricing_plan = LawyerOffering.objects.get(id=pricing_plan_id, is_active=True)
    except LawyerOffering.DoesNotExist:
        return Response(
            {"error": "Active pricing plan not found."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Get available service types for this pricing plan
    service_types = OfferingType.objects.filter(offering=pricing_plan, is_active=True)

    # Calculate prices for different durations and service types
    pricing_info = {
        "pricing_plan": LawyerOfferingWithServiceTypesSerializer(pricing_plan).data,
        "pricing_options": [],
    }

    for service_type in service_types:
        service_info = {
            "service_type": service_type.type,
            "service_type_display": service_type.get_type_display(),
            "is_free": service_type.is_free_service,
            "pricing": {
                "30min": service_type.get_price_breakdown(30),
                "60min": service_type.get_price_breakdown(60),
            },
        }
        pricing_info["pricing_options"].append(service_info)

    return Response(pricing_info, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsLawyerVendor])
def lawyer_dashboard(request):
    """Get comprehensive dashboard data for a lawyer"""
    try:
        lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=request.user)
    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Lawyer profile not found for this user."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Get pricing plans (offerings)
    pricing_plans = LawyerOffering.objects.filter(lawyer_profile=lawyer_profile)
    active_pricing_plans = pricing_plans.filter(is_active=True)

    # Get service types statistics
    total_service_types = OfferingType.objects.filter(
        offering__lawyer_profile=lawyer_profile
    ).count()
    active_service_types = OfferingType.objects.filter(
        offering__lawyer_profile=lawyer_profile, is_active=True
    ).count()

    # Calculate pricing statistics
    pricing_stats = pricing_plans.aggregate(
        avg_price=Avg("price_per_30min"),
        min_price=Min("price_per_30min"),
        max_price=Max("price_per_30min"),
    )

    dashboard_data = {
        "lawyer_profile": LawyerProfileSerializer(lawyer_profile).data,
        "stats": {
            "total_pricing_plans": pricing_plans.count(),
            "active_pricing_plans": active_pricing_plans.count(),
            "total_service_types": total_service_types,
            "active_service_types": active_service_types,
            "average_rating": lawyer_profile.average_rating,
            "total_reviews": lawyer_profile.review_count,
            "commission_percentage": lawyer_profile.commission_percentage,
            "pricing_stats": {
                "average_price": pricing_stats["avg_price"] or Decimal("0.00"),
                "min_price": pricing_stats["min_price"] or Decimal("0.00"),
                "max_price": pricing_stats["max_price"] or Decimal("0.00"),
            },
        },
        "pricing_plans": LawyerOfferingListSerializer(
            active_pricing_plans, many=True
        ).data,
    }

    return Response(dashboard_data, status=status.HTTP_200_OK)


@api_view(["GET"])
@permission_classes([IsLawyerVendor])
def pricing_analytics(request):
    """Get pricing analytics for the authenticated lawyer"""
    try:
        lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=request.user)
    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Lawyer profile not found for this user."},
            status=status.HTTP_404_NOT_FOUND,
        )

    # Pricing plans analytics
    pricing_plans = LawyerOffering.objects.filter(lawyer_profile=lawyer_profile)
    service_types = OfferingType.objects.filter(offering__lawyer_profile=lawyer_profile)

    # Service type breakdown
    service_type_breakdown = service_types.values("type").annotate(
        count=Count("id"), active_count=Count("id", filter=Q(is_active=True))
    )

    analytics_data = {
        "pricing_plans": {
            "total": pricing_plans.count(),
            "active": pricing_plans.filter(is_active=True).count(),
            "price_statistics": pricing_plans.aggregate(
                avg_price=Avg("price_per_30min"),
                min_price=Min("price_per_30min"),
                max_price=Max("price_per_30min"),
            ),
        },
        "service_types": {
            "total": service_types.count(),
            "active": service_types.filter(is_active=True).count(),
            "breakdown": service_type_breakdown,
        },
        "commission_info": {
            "commission_percentage": lawyer_profile.commission_percentage,
            "estimated_commission_30min": lawyer_profile.commission_percentage
            / 100
            * (pricing_plans.aggregate(avg=Avg("price_per_30min"))["avg"] or 0),
        },
    }

    return Response(analytics_data, status=status.HTTP_200_OK)


class PublicLawyerOfferingListView(generics.ListAPIView):
    """Public endpoint for browsing active lawyer pricing plans"""

    queryset = LawyerOffering.objects.filter(
        is_active=True,
        # lawyer_profile__kyc_verification_status="verified",
        lawyer_profile__vendor_profile__category__name="Lawyer",
    )
    serializer_class = PublicLawyerOfferingSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .select_related("lawyer_profile__vendor_profile")
            .prefetch_related("offering_types")
        )

        # Location-based filters
        city = self.request.query_params.get("city", None)
        if city:
            queryset = queryset.filter(
                lawyer_profile__vendor_profile__address__city__icontains=city
            )

        # Price range filters
        min_price = self.request.query_params.get("min_price", None)
        if min_price:
            queryset = queryset.filter(price_per_30min__gte=min_price)

        max_price = self.request.query_params.get("max_price", None)
        if max_price:
            queryset = queryset.filter(price_per_30min__lte=max_price)

        # Service type filters
        service_type = self.request.query_params.get("service_type", None)
        if service_type:
            queryset = queryset.filter(
                offering_types__type=service_type, offering_types__is_active=True
            ).distinct()

        # Rating filter
        min_rating = self.request.query_params.get("min_rating", None)
        if min_rating:
            queryset = queryset.filter(lawyer_profile__average_rating__gte=min_rating)

        # Search functionality
        search = self.request.query_params.get("search", None)
        if search:
            queryset = queryset.filter(
                Q(name__icontains=search)
                | Q(lawyer_profile__vendor_profile__business_name__icontains=search)
            )

        # Sorting options
        sort_by = self.request.query_params.get("sort_by", "-created_at")
        allowed_sorts = [
            "price_per_30min",
            "-price_per_30min",
            "created_at",
            "-created_at",
            "name",
            "-name",
            "lawyer_profile__average_rating",
            "-lawyer_profile__average_rating",
        ]
        if sort_by in allowed_sorts:
            queryset = queryset.order_by(sort_by)
        else:
            queryset = queryset.order_by("-created_at")

        return queryset


class PublicLawyerOfferingDetailView(generics.RetrieveAPIView):
    """Public endpoint for viewing a specific pricing plan"""

    queryset = (
        LawyerOffering.objects.filter(
            is_active=True,
            # lawyer_profile__kyc_verification_status="verified",
            lawyer_profile__vendor_profile__category__name="Lawyer",
        )
        .select_related("lawyer_profile__vendor_profile")
        .prefetch_related("offering_types")
    )

    serializer_class = LawyerOfferingWithServiceTypesSerializer
    permission_classes = [permissions.AllowAny]


@api_view(["GET"])
@permission_classes([permissions.AllowAny])
def system_info(request):
    """Get information about service types, durations, and other system constants"""
    service_types = [
        {"value": choice[0], "label": choice[1]}
        for choice in OfferingType.OFFERING_CHOICES
    ]

    duration_options = [30, 60]

    return Response(
        {
            "service_types": service_types,
            "duration_options": duration_options,
            "commission_info": {
                "default_percentage": 10.0,
                "description": "Platform commission percentage",
            },
            "pricing_info": {
                "base_unit": "30 minutes",
                "supported_durations": [30, 60],
                "currency": "USD",
            },
            "business_rules": {
                "physical_appointments_free": True,
                "video_audio_paid": True,
                "duration_multiples": "30 minutes",
            },
        },
        status=status.HTTP_200_OK,
    )


@api_view(["GET"])
@permission_classes([IsLawyerVendor])
def lawyer_pricing_summary(request):
    """Get a summary of lawyer's pricing configuration"""
    try:
        lawyer_profile = LawyerProfile.objects.get(vendor_profile__user=request.user)
    except LawyerProfile.DoesNotExist:
        return Response(
            {"error": "Lawyer profile not found for this user."},
            status=status.HTTP_404_NOT_FOUND,
        )

    pricing_plans = LawyerOffering.objects.filter(
        lawyer_profile=lawyer_profile, is_active=True
    ).prefetch_related("offering_types")

    summary_data = {
        "lawyer_profile": {
            "id": lawyer_profile.id,
            "business_name": lawyer_profile.vendor_profile.business_name,
            "commission_percentage": lawyer_profile.commission_percentage,
        },
        "pricing_plans": [],
    }

    for plan in pricing_plans:
        plan_data = {
            "id": plan.id,
            "name": plan.name,
            "price_per_30min": plan.price_per_30min,
            "service_types": [],
        }

        for service_type in plan.offering_types.filter(is_active=True):
            service_data = {
                "type": service_type.type,
                "type_display": service_type.get_type_display(),
                "is_free": service_type.is_free_service,
                "price_30min": service_type.get_price_for_duration(30),
                "price_60min": service_type.get_price_for_duration(60),
            }
            plan_data["service_types"].append(service_data)

        summary_data["pricing_plans"].append(plan_data)

    return Response(summary_data, status=status.HTTP_200_OK)


class LawyerProfileUpdateView(APIView):
    """Update lawyer profile information for the current user"""

    permission_classes = [IsAuthenticated]

    def get_object(self):
        """Get lawyer profile for current user"""
        try:
            vendor_profile = VendorProfile.objects.get(user=self.request.user)
            return LawyerProfile.objects.get(vendor_profile=vendor_profile)
        except (VendorProfile.DoesNotExist, LawyerProfile.DoesNotExist):
            raise Http404("Lawyer profile not found")

    def get(self, request):
        """Get current lawyer profile"""
        lawyer_profile = self.get_object()
        serializer = LawyerProfileSerializer(lawyer_profile)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def put(self, request):
        """Update lawyer profile"""
        lawyer_profile = self.get_object()

        # Use the LawyerProfileStepSerializer for updates
        serializer = LawyerProfileStepSerializer(data=request.data, partial=True)
        if serializer.is_valid():
            # Update basic fields
            for field in [
                "registration_number",
                "fiscal_code",
                "cancellation_threshold_hours",
            ]:
                if field in serializer.validated_data:
                    setattr(lawyer_profile, field, serializer.validated_data[field])

            # Handle lawyer categories
            lawyer_category_ids = serializer.validated_data.get("lawyer_category_ids")
            if lawyer_category_ids is not None:
                lawyer_categories = LawyerCategory.objects.filter(
                    id__in=lawyer_category_ids
                )
                lawyer_profile.lawyercategories.clear()
                lawyer_profile.lawyercategories.add(*lawyer_categories)

            # Handle lawyer subcategories
            lawyer_subcategory_ids = serializer.validated_data.get(
                "lawyer_subcategory_ids"
            )
            if lawyer_subcategory_ids is not None:
                lawyer_subcategories = LawyerSubcategory.objects.filter(
                    id__in=lawyer_subcategory_ids
                )
                lawyer_profile.lawyersubcategories.clear()
                lawyer_profile.lawyersubcategories.add(*lawyer_subcategories)

            lawyer_profile.save()

            # Return updated profile
            response_serializer = LawyerProfileSerializer(lawyer_profile)
            return Response(response_serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
