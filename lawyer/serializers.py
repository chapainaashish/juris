from rest_framework import serializers

from .models import (
    LawyerCategory,
    LawyerOffering,
    LawyerProfile,
    LawyerSubcategory,
    OfferingType,
)


# Category serializers
class LawyerCategorySerializer(serializers.ModelSerializer):
    subcategories = serializers.SerializerMethodField()

    class Meta:
        model = LawyerCategory
        fields = [
            "id",
            "title",
            "description",
            "subcategories",
            "created_at",
            "updated_at",
        ]

    def get_subcategories(self, obj):
        return LawyerSubcategorySerializer(obj.subcategories.all(), many=True).data


class LawyerSubcategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LawyerSubcategory
        fields = [
            "id",
            "title",
            "lawyercategory",
            "description",
            "created_at",
            "updated_at",
        ]


class LawyerProfileSerializer(serializers.ModelSerializer):
    lawyercategories = LawyerCategorySerializer(many=True, read_only=True)
    lawyersubcategories = LawyerSubcategorySerializer(many=True, read_only=True)
    total_pricing_plans = serializers.SerializerMethodField()
    active_pricing_plans = serializers.SerializerMethodField()
    default_pricing_plan_name = serializers.CharField(
        source="default_pricing_plan.name", read_only=True
    )

    class Meta:
        model = LawyerProfile
        fields = [
            "id",
            "vendor_profile",
            "registration_number",
            "kyc_verification_status",
            "legal_verified",
            "lawyercategories",
            "lawyersubcategories",
            "fiscal_code",
            "cancellation_threshold_hours",
            "average_rating",
            "review_count",
            "default_pricing_plan",
            "default_pricing_plan_name",
            "total_pricing_plans",
            "active_pricing_plans",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "kyc_verification_status",
            "legal_verified",
            "average_rating",
            "review_count",
        ]

    def get_total_pricing_plans(self, obj):
        return obj.offerings.count()

    def get_active_pricing_plans(self, obj):
        return obj.offerings.filter(is_active=True).count()


class LawyerProfileStepSerializer(serializers.Serializer):
    """Serializer for lawyer profile update step"""

    registration_number = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )
    fiscal_code = serializers.CharField(max_length=50, required=False, allow_blank=True)
    cancellation_threshold_hours = serializers.IntegerField(
        default=24, min_value=1, max_value=168, required=False
    )
    lawyer_category_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )
    lawyer_subcategory_ids = serializers.ListField(
        child=serializers.UUIDField(), required=False, allow_empty=True
    )

    def validate_lawyer_category_ids(self, value):
        """Validate that all category IDs exist"""
        if value:
            from lawyer.models import LawyerCategory

            existing_ids = set(
                LawyerCategory.objects.filter(id__in=value).values_list("id", flat=True)
            )
            if len(existing_ids) != len(set(value)):
                raise serializers.ValidationError(
                    "Some lawyer category IDs do not exist."
                )
        return value

    def validate_lawyer_subcategory_ids(self, value):
        """Validate that all subcategory IDs exist"""
        if value:
            from lawyer.models import LawyerSubcategory

            existing_ids = set(
                LawyerSubcategory.objects.filter(id__in=value).values_list(
                    "id", flat=True
                )
            )
            if len(existing_ids) != len(set(value)):
                raise serializers.ValidationError(
                    "Some lawyer subcategory IDs do not exist."
                )
        return value


# LawyerOffering serializers
class LawyerOfferingSerializer(serializers.ModelSerializer):
    """
    LawyerOffering now represents Pricing Plans
    Fields adapted for pricing plan functionality
    """

    service_types = serializers.SerializerMethodField()
    lawyer_name = serializers.CharField(
        source="lawyer_profile.vendor_profile.business_name", read_only=True
    )
    price_for_30min = serializers.DecimalField(
        source="price_per_30min", max_digits=10, decimal_places=2, read_only=True
    )
    price_for_60min = serializers.SerializerMethodField()
    min_price = serializers.ReadOnlyField()
    max_price = serializers.ReadOnlyField()

    class Meta:
        model = LawyerOffering
        fields = [
            "id",
            "lawyer_profile",
            "name",
            "price_per_30min",
            "price_for_30min",
            "price_for_60min",
            "min_price",
            "max_price",
            "is_active",
            "service_types",
            "lawyer_name",
            "created_at",
            "updated_at",
        ]

    def get_service_types(self, obj):
        return OfferingTypeSerializer(
            obj.offering_types.filter(is_active=True), many=True
        ).data

    def get_price_for_60min(self, obj):
        return obj.calculate_price(60)

    def validate_name(self, value):
        lawyer_profile = self.context.get("lawyer_profile") or (
            self.instance.lawyer_profile if self.instance else None
        )
        if (
            lawyer_profile
            and LawyerOffering.objects.filter(lawyer_profile=lawyer_profile, name=value)
            .exclude(pk=self.instance.pk if self.instance else None)
            .exists()
        ):
            raise serializers.ValidationError(
                "A pricing plan with this name already exists."
            )
        return value


class LawyerOfferingCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating/updating pricing plans (LawyerOffering)
    """

    class Meta:
        model = LawyerOffering
        fields = [
            "name",
            "price_per_30min",
            "is_active",
        ]

    def validate_price_per_30min(self, value):
        if value <= 0:
            raise serializers.ValidationError(
                "Price per 30 minutes must be greater than 0."
            )
        return value

    def validate_name(self, value):
        # Validate unique name per lawyer
        lawyer_profile = self.context.get("lawyer_profile")
        if (
            lawyer_profile
            and LawyerOffering.objects.filter(lawyer_profile=lawyer_profile, name=value)
            .exclude(pk=self.instance.pk if self.instance else None)
            .exists()
        ):
            raise serializers.ValidationError(
                "A pricing plan with this name already exists."
            )
        return value


class LawyerOfferingListSerializer(serializers.ModelSerializer):
    """
    Simplified serializer for listing pricing plans
    """

    lawyer_name = serializers.CharField(
        source="lawyer_profile.vendor_profile.business_name", read_only=True
    )
    service_types_count = serializers.SerializerMethodField()
    price_display = serializers.SerializerMethodField()

    class Meta:
        model = LawyerOffering
        fields = [
            "id",
            "name",
            "price_per_30min",
            "price_display",
            "is_active",
            "lawyer_name",
            "service_types_count",
            "created_at",
        ]

    def get_service_types_count(self, obj):
        return obj.offering_types.filter(is_active=True).count()

    def get_price_display(self, obj):
        return f"{obj.price_per_30min} USD / 30 minute"


# OfferingType serializers
class OfferingTypeSerializer(serializers.ModelSerializer):
    """
    OfferingType now represents Service Types (physical/audio/video)
    """

    type_display = serializers.CharField(source="get_type_display", read_only=True)
    price_for_30min = serializers.ReadOnlyField()
    price_for_60min = serializers.ReadOnlyField()
    is_free = serializers.ReadOnlyField(source="is_free_service")
    pricing_plan_name = serializers.CharField(source="offering.name", read_only=True)
    pricing_plan_base_price = serializers.DecimalField(
        source="offering.price_per_30min",
        max_digits=10,
        decimal_places=2,
        read_only=True,
    )

    class Meta:
        model = OfferingType
        fields = [
            "id",
            "offering",
            "type",
            "type_display",
            "is_active",
            "price_for_30min",
            "price_for_60min",
            "is_free",
            "pricing_plan_name",
            "pricing_plan_base_price",
            "created_at",
            "updated_at",
        ]


class OfferingTypeCreateUpdateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating/updating service types
    """

    class Meta:
        model = OfferingType
        fields = [
            "type",
            "is_active",
        ]

    def validate_type(self, value):
        offering = self.context.get("offering") or (
            self.instance.offering if self.instance else None
        )
        if (
            offering
            and OfferingType.objects.filter(offering=offering, type=value)
            .exclude(pk=self.instance.pk if self.instance else None)
            .exists()
        ):
            raise serializers.ValidationError(
                "This service type already exists for this pricing plan."
            )
        return value


# Price calculation serializers
class PriceCalculationSerializer(serializers.Serializer):
    """
    Serializer for calculating appointment prices
    """

    pricing_plan_id = serializers.UUIDField()
    duration_minutes = serializers.IntegerField()
    service_type = serializers.ChoiceField(choices=OfferingType.OFFERING_CHOICES)

    def validate_duration_minutes(self, value):
        if value not in [30, 60]:
            raise serializers.ValidationError("Duration must be 30 or 60 minutes.")
        return value

    def validate(self, data):
        # Get pricing plan and validate
        try:
            pricing_plan = LawyerOffering.objects.get(
                id=data["pricing_plan_id"], is_active=True
            )
        except LawyerOffering.DoesNotExist:
            raise serializers.ValidationError(
                {"pricing_plan_id": "Active pricing plan not found."}
            )

        # Check if service type is available for this pricing plan
        try:
            service_type_obj = OfferingType.objects.get(
                offering=pricing_plan, type=data["service_type"], is_active=True
            )
        except OfferingType.DoesNotExist:
            raise serializers.ValidationError(
                {
                    "service_type": f"Service type '{data['service_type']}' not available for this pricing plan."
                }
            )

        data["pricing_plan"] = pricing_plan
        data["service_type_obj"] = service_type_obj
        return data


# Public serializers (for client browsing)
class PublicLawyerOfferingSerializer(serializers.ModelSerializer):
    """
    Public serializer for browsing lawyer pricing plans
    """

    lawyer_name = serializers.CharField(
        source="lawyer_profile.vendor_profile.business_name", read_only=True
    )
    lawyer_city = serializers.CharField(
        source="lawyer_profile.vendor_profile.address.city", read_only=True
    )
    lawyer_rating = serializers.DecimalField(
        source="lawyer_profile.average_rating",
        max_digits=3,
        decimal_places=2,
        read_only=True,
    )
    service_types = OfferingTypeSerializer(
        source="offering_types", many=True, read_only=True
    )
    price_display = serializers.SerializerMethodField()

    class Meta:
        model = LawyerOffering
        fields = [
            "id",
            "name",
            "price_per_30min",
            "price_display",
            "lawyer_name",
            "lawyer_city",
            "lawyer_rating",
            "service_types",
            "created_at",
        ]

    def get_price_display(self, obj):
        return f"{obj.price_per_30min} USD / 30 min"


# Pricing plan with service types serializer
class LawyerOfferingWithServiceTypesSerializer(serializers.ModelSerializer):
    """
    Complete pricing plan serializer with all service types
    Used for detailed views and creation workflows
    """

    service_types = OfferingTypeSerializer(
        source="offering_types", many=True, read_only=True
    )
    lawyer_name = serializers.CharField(
        source="lawyer_profile.vendor_profile.business_name", read_only=True
    )
    price_breakdown_30min = serializers.SerializerMethodField()
    price_breakdown_60min = serializers.SerializerMethodField()

    class Meta:
        model = LawyerOffering
        fields = [
            "id",
            "lawyer_profile",
            "name",
            "price_per_30min",
            "is_active",
            "service_types",
            "lawyer_name",
            "price_breakdown_30min",
            "price_breakdown_60min",
            "created_at",
            "updated_at",
        ]

    def get_price_breakdown_30min(self, obj):
        return obj.get_price_breakdown(30)

    def get_price_breakdown_60min(self, obj):
        return obj.get_price_breakdown(60)
