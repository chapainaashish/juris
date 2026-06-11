from rest_framework import serializers

from .models import KYCVerification


class KYCVerificationSerializer(serializers.ModelSerializer):
    """Simple KYC verification serializer"""

    is_verified = serializers.ReadOnlyField()

    class Meta:
        model = KYCVerification
        fields = [
            "id",
            "status",
            "is_verified",
            "created_at",
            "updated_at",
        ]
        read_only_fields = [
            "id",
            "status",
            "created_at",
            "updated_at",
        ]


class KYCVerificationSessionSerializer(serializers.Serializer):
    """Serializer for creating KYC verification session"""

    return_url = serializers.URLField(
        help_text="URL to redirect user after completing verification"
    )
