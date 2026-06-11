from decimal import Decimal

from rest_framework import serializers

from lawyer.serializers import LawyerCategorySerializer, LawyerSubcategorySerializer

from .models import (
    Address,
    Category,
    Certificate,
    Language,
    Media,
    ProfileCompletionSession,
    Service,
    ServiceCategory,
    VendorLegalInfo,
    VendorProfile,
)


# CORE MODEL SERIALIZERS (Independent models)
class CategorySerializer(serializers.ModelSerializer):
    """Serializer for vendor categories"""

    class Meta:
        model = Category
        fields = ["id", "name"]


class LanguageSerializer(serializers.ModelSerializer):
    """Serializer for languages"""

    class Meta:
        model = Language
        fields = ["id", "name", "icon_url"]


class AddressSerializer(serializers.ModelSerializer):
    """Serializer for address information"""

    class Meta:
        model = Address
        fields = [
            "id",
            "street",
            "city",
            "postcode",
            "country",
            "latitude",
            "longitude",
        ]


# MAIN VENDOR SERIALIZERS (Core business logic)
class VendorLegalInfoSerializer(serializers.ModelSerializer):
    """Serializer for vendor legal information"""

    class Meta:
        model = VendorLegalInfo
        fields = ["id", "first_name_id", "last_name_id", "email", "bar_association"]


class VendorProfileSerializer(serializers.ModelSerializer):
    """Complete vendor profile serializer with all related data"""

    category = CategorySerializer(read_only=True)
    address = AddressSerializer(read_only=True)
    languages = LanguageSerializer(many=True, read_only=True)
    legal_info = VendorLegalInfoSerializer(source="vendorlegalinfo", read_only=True)
    media = serializers.SerializerMethodField()  # Will be defined after MediaSerializer
    certificates = (
        serializers.SerializerMethodField()
    )  # Will be defined after CertificateSerializer
    service_categories = (
        serializers.SerializerMethodField()
    )  # Will be defined after ServiceCategorySerializer

    class Meta:
        model = VendorProfile
        fields = [
            "id",
            "user",
            "category",
            "business_name",
            "address",
            "languages",
            "avatar_url",
            "legal_info",
            "is_completed",
            "created_at",
            "updated_at",
            "bio",
            "experience",
            "website",
            "whatsapp",
            "facebook",
            "youtube",
            "instagram",
            "twitter",
            "social_media_status",
            "general_link",
            "media",
            "certificates",
            "service_categories",
        ]
        read_only_fields = ["user", "is_completed", "created_at", "updated_at"]

    def get_media(self, obj):
        """Get media using MediaSerializer"""
        return MediaSerializer(obj.media.all(), many=True).data

    def get_certificates(self, obj):
        """Get certificates using CertificateSerializer"""
        return CertificateSerializer(obj.certificates.all(), many=True).data

    def get_service_categories(self, obj):
        """Get service categories using ServiceCategorySerializer"""
        return ServiceCategorySerializer(obj.service_categories.all(), many=True).data


class VendorProfileUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating vendor profile fields including business name and languages"""

    language_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False, write_only=True
    )

    class Meta:
        model = VendorProfile
        fields = [
            "business_name",
            "language_ids",
            "bio",
            "experience",
            "website",
            "whatsapp",
            "facebook",
            "youtube",
            "instagram",
            "twitter",
            "social_media_status",
            "general_link",
        ]

    def validate_language_ids(self, value):
        """Validate that all language_ids exist in the database"""
        if value:
            existing_ids = set(
                Language.objects.filter(id__in=value).values_list("id", flat=True)
            )
            if len(existing_ids) != len(set(value)):
                raise serializers.ValidationError(
                    "Invalid language selection. Some language IDs do not exist."
                )
        return value

    def update(self, instance, validated_data):
        """Update vendor profile with language handling"""
        language_ids = validated_data.pop("language_ids", None)

        # Update regular fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        # Handle language updates
        if language_ids is not None:
            # Clear existing languages and add new ones
            instance.languages.clear()
            if language_ids:
                languages = Language.objects.filter(id__in=language_ids)
                instance.languages.add(*languages)

        instance.save()
        return instance


# SESSION SERIALIZERS (Profile completion workflow)


class ProfileCompletionSessionSerializer(serializers.ModelSerializer):
    """Serializer for profile completion session management"""

    category = CategorySerializer(read_only=True)
    address = AddressSerializer(read_only=True)
    languages = LanguageSerializer(many=True, read_only=True)

    class Meta:
        model = ProfileCompletionSession
        fields = [
            "id",
            "token",
            "user",
            "category",
            "business_name",
            "address",
            "languages",
            "avatar_url",
            "first_name_id",
            "last_name_id",
            "legal_email",
            "bar_association",
            "created_at",
            "last_updated",
            "is_completed",
            "expires_at",
            "bio",
            "experience",
            "website",
            "whatsapp",
            "facebook",
            "youtube",
            "instagram",
            "twitter",
            "social_media_status",
            "general_link",
        ]
        read_only_fields = [
            "token",
            "user",
            "created_at",
            "last_updated",
            "is_completed",
            "expires_at",
        ]


# SERVICE SERIALIZERS (Vendor services and categories)


class ServiceSerializer(serializers.ModelSerializer):
    """Serializer for individual services"""

    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "description",
            "tags",
            "price",
            "image",
            "is_active",
            "created_at",
            "updated_at",
            "category",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ServiceCategorySerializer(serializers.ModelSerializer):
    """Serializer for service categories with nested services"""

    services = ServiceSerializer(many=True, read_only=True)

    class Meta:
        model = ServiceCategory
        fields = [
            "id",
            "name",
            "description",
            "is_active",
            "created_at",
            "updated_at",
            "services",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ServiceCategoryCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating service categories"""

    class Meta:
        model = ServiceCategory
        fields = ["id", "name", "description", "is_active"]
        read_only_fields = ["id"]


class ServiceCreateSerializer(serializers.ModelSerializer):
    tags = serializers.ListField(
        child=serializers.CharField(),
        write_only=True,
        allow_empty=True,
        required=False,
    )
    tags_list = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Service
        fields = [
            "id",
            "name",
            "description",
            "tags",  # write-only input
            "tags_list",  # read-only output
            "price",
            "image",
            "is_active",
            "category",
        ]
        read_only_fields = ["id"]

    def get_tags_list(self, obj):
        return [tag.strip() for tag in obj.tags.split(",")] if obj.tags else []

    def validate_tags(self, value):
        cleaned = list(
            dict.fromkeys(tag.strip().lower() for tag in value if tag.strip())
        )
        return ",".join(cleaned)

    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        validated_data["tags"] = self.validate_tags(tags)
        return super().create(validated_data)

    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        if tags is not None:
            validated_data["tags"] = self.validate_tags(tags)
        return super().update(instance, validated_data)


# MEDIA AND DOCUMENT SERIALIZERS
class MediaSerializer(serializers.ModelSerializer):
    """Serializer for vendor media files"""

    class Meta:
        model = Media
        fields = ["id", "title", "description", "file", "file_type", "created_at"]
        read_only_fields = ["id", "created_at"]


class CertificateSerializer(serializers.ModelSerializer):
    """Serializer for vendor certificates"""

    class Meta:
        model = Certificate
        fields = ["id", "title", "details", "file", "status", "created_at"]
        read_only_fields = ["id", "created_at"]


# STEP-BY-STEP PROFILE COMPLETION SERIALIZERS
class CategorySelectionSerializer(serializers.Serializer):
    """Serializer for category selection step"""

    category_id = serializers.IntegerField()


class BusinessNameSerializer(serializers.Serializer):
    """Serializer for business name step"""

    business_name = serializers.CharField(max_length=255)


class AddressCreationSerializer(serializers.ModelSerializer):
    """Serializer for address creation step"""

    class Meta:
        model = Address
        fields = ["street", "city", "postcode", "country", "latitude", "longitude"]


class LanguageSelectionSerializer(serializers.Serializer):
    """Serializer for language selection step"""

    language_ids = serializers.ListField(
        child=serializers.IntegerField(), required=False
    )


class AvatarUploadSerializer(serializers.Serializer):
    """Serializer for avatar upload step"""

    avatar_url = serializers.URLField(max_length=255)


class LegalInfoSerializer(serializers.ModelSerializer):
    """Serializer for legal information step"""

    class Meta:
        model = VendorLegalInfo
        fields = ["first_name_id", "last_name_id", "email", "bar_association"]


class ProfileAdditionalInfoSerializer(serializers.Serializer):
    """Serializer for additional profile information step"""

    bio = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    experience = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    website = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    whatsapp = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    facebook = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    youtube = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    instagram = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    twitter = serializers.URLField(required=False, allow_blank=True, allow_null=True)
    social_media_status = serializers.BooleanField(required=False)
    general_link = serializers.URLField(
        required=False, allow_blank=True, allow_null=True
    )


# UPLOAD AND UPDATE SERIALIZERS
class MediaUploadSerializer(serializers.Serializer):
    """Serializer for media file uploads"""

    title = serializers.CharField(
        max_length=255, required=False, allow_blank=True, allow_null=True
    )
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )
    file_url = serializers.URLField()
    file_type = serializers.CharField(max_length=50)  # image, video, document


class MediaUpdateSerializer(serializers.Serializer):
    """Serializer for updating media information"""

    title = serializers.CharField(
        max_length=255, required=False, allow_blank=True, allow_null=True
    )
    description = serializers.CharField(
        required=False, allow_blank=True, allow_null=True
    )


class CertificateUploadSerializer(serializers.Serializer):
    """Serializer for certificate uploads"""

    title = serializers.CharField(max_length=255)
    details = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    file_url = serializers.URLField()


class CertificateUpdateSerializer(serializers.Serializer):
    """Serializer for updating certificate information"""

    title = serializers.CharField(max_length=255, required=False)
    details = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    status = serializers.ChoiceField(choices=Certificate.STATUS_CHOICES, required=False)
