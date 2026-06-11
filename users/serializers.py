import re

import phonenumbers
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from phonenumbers import NumberParseException
from rest_framework import serializers

User = get_user_model()


# USER MANAGEMENT SERIALIZERS
class VendorProfileSerializer(serializers.Serializer):
    """Serializer for vendor profile data - only when profile is completed"""

    business_name = serializers.CharField()
    category = serializers.CharField(source="category.name")
    avatar_url = serializers.URLField()
    bio = serializers.CharField()
    experience = serializers.CharField()
    website = serializers.URLField()
    whatsapp = serializers.CharField()
    facebook = serializers.URLField()
    youtube = serializers.URLField()
    instagram = serializers.URLField()
    twitter = serializers.URLField()
    general_link = serializers.URLField()
    is_active = serializers.BooleanField()

    # Address data
    address_street = serializers.CharField(source="address.street")
    address_city = serializers.CharField(source="address.city")
    address_postcode = serializers.CharField(source="address.postcode")
    address_country = serializers.CharField(source="address.country")
    address_latitude = serializers.FloatField(source="address.latitude")
    address_longitude = serializers.FloatField(source="address.longitude")

    # Languages
    languages = serializers.SerializerMethodField()

    def get_languages(self, obj):
        return [
            {"name": lang.name, "icon_url": lang.icon_url}
            for lang in obj.languages.all()
        ]


class UserSerializer(serializers.ModelSerializer):
    """Serializer for user profile data with vendor profile if applicable"""

    vendor_profile = serializers.SerializerMethodField()
    is_complete = serializers.ReadOnlyField()
    can_access_dashboard = serializers.ReadOnlyField()
    is_2fa_enabled = serializers.ReadOnlyField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "phone_number",
            "first_name",
            "last_name",
            "role",
            "vendor_type",
            "is_complete",
            "can_access_dashboard",
            "vendor_profile",
            "is_2fa_enabled",  # new added
        ]
        read_only_fields = ["id"]

    def get_vendor_profile(self, obj):
        """Include vendor profile data if user is vendor and profile is completed"""
        if obj.role == "vendor" and obj.is_complete:
            try:
                vendor_profile = obj.vendorprofile
                return VendorProfileSerializer(vendor_profile).data
            except:
                return None
        return None


class CheckEmailSerializer(serializers.Serializer):
    """Serializer for checking if email exists"""

    email = serializers.EmailField()


def validate_phone_number(phone_number):
    """Simple phone number validator"""
    if not phone_number:
        return phone_number

    try:
        parsed = phonenumbers.parse(phone_number, None)
        if not phonenumbers.is_valid_number(parsed):
            raise serializers.ValidationError("Invalid phone number format.")
        # Return normalized E164 format
        return phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
    except NumberParseException:
        raise serializers.ValidationError("Invalid phone number format.")


class UpdatePhoneSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=20)

    def validate_phone_number(self, value):
        if not value:
            raise serializers.ValidationError("Phone number is required.")

        # Validate format
        normalized_phone = validate_phone_number(value)

        # Check uniqueness
        user = self.context.get("request").user if self.context.get("request") else None
        if (
            user
            and User.objects.filter(phone_number=normalized_phone)
            .exclude(id=user.id)
            .exists()
        ):
            raise serializers.ValidationError("This phone number is already in use.")

        return normalized_phone


# AUTHENTICATION SERIALIZERS
class LoginSerializer(serializers.Serializer):
    """Serializer for user login"""

    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)


class SignupSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    confirm_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = [
            "email",
            "phone_number",
            "password",
            "confirm_password",
            "first_name",
            "last_name",
            "role",
        ]

    def validate_phone_number(self, value):
        if value:
            # Validate format
            normalized_phone = validate_phone_number(value)

            # Check uniqueness
            if User.objects.filter(phone_number=normalized_phone).exists():
                raise serializers.ValidationError(
                    "This phone number is already in use."
                )

            return normalized_phone
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs["confirm_password"]:
            raise serializers.ValidationError(
                {"password": "Password fields didn't match."}
            )

        return attrs

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        user = User.objects.create_user(
            username=validated_data["email"],
            email=validated_data["email"],
            password=validated_data["password"],
            first_name=validated_data.get("first_name", ""),
            last_name=validated_data.get("last_name", ""),
            phone_number=validated_data.get("phone_number", ""),
            role=validated_data.get("role", "client"),
            vendor_type=None,  # Will be set during profile completion
            is_active=True,
            is_email_verified=False,
        )
        return user


# VERIFICATION & OTP SERIALIZERS
class VerifyOTPSerializer(serializers.Serializer):
    """Serializer for OTP verification"""

    verification_token = serializers.CharField()
    otp = serializers.CharField(max_length=6, min_length=6)

    def validate_otp(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("OTP must contain only digits.")
        return value


class Toggle2FASerializer(serializers.Serializer):
    enable = serializers.BooleanField(required=False)
    enabled = serializers.BooleanField(required=False)
    phone_number = serializers.CharField(max_length=20, required=False)
    # otp field removed

    def validate(self, attrs):
        if "enable" not in attrs and "enabled" not in attrs:
            raise serializers.ValidationError({"enable": "This field is required."})
        attrs["enable"] = attrs.get("enable", attrs.get("enabled"))
        return attrs

    def validate_phone_number(self, value):
        if value:
            normalized_phone = validate_phone_number(value)
            user = (
                self.context.get("request").user
                if self.context.get("request")
                else None
            )
            if (
                user
                and User.objects.filter(phone_number=normalized_phone)
                .exclude(id=user.id)
                .exists()
            ):
                raise serializers.ValidationError(
                    "This phone number is already in use."
                )
            return normalized_phone
        return value


# EMAIL CHANGE SERIALIZERS
class ChangeEmailRequestSerializer(serializers.Serializer):
    """Serializer for requesting email change"""

    new_email = serializers.EmailField()

    def validate_new_email(self, value):
        request = self.context.get("request")

        # Check if email is already in use by another user
        if request and request.user:
            if User.objects.filter(email=value).exclude(id=request.user.id).exists():
                raise serializers.ValidationError(
                    "This email is already in use by another account."
                )

        # Check if it's the same as current email
        if request and request.user and request.user.email == value:
            raise serializers.ValidationError("This is your current email address.")

        return value


class VerifyEmailChangeSerializer(serializers.Serializer):
    """Serializer for verifying email change with code"""

    verification_code = serializers.CharField(max_length=6, min_length=6)

    def validate_verification_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError(
                "Verification code must contain only digits."
            )
        return value


# PASSWORD MANAGEMENT SERIALIZERS
class ChangePasswordSerializer(serializers.Serializer):
    """Serializer for changing password"""

    current_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        write_only=True, validators=[validate_password]
    )
    confirm_new_password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError(
                {"confirm_new_password": "New password fields didn't match."}
            )
        return attrs


class ForgotPasswordSerializer(serializers.Serializer):
    """Serializer for forgot password request - accepts email or phone"""

    identifier = serializers.CharField(help_text="Email address or phone number")

    def validate_identifier(self, value):
        """Validate that identifier is either a valid email or phone number format"""
        # Check if it's an email
        if "@" in value:
            # Basic email validation
            email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
            if not re.match(email_regex, value):
                raise serializers.ValidationError("Invalid email format.")
        else:
            # Assume it's a phone number - basic validation
            phone_regex = r"^\+?[1-9]\d{1,14}$"  # International format
            if not re.match(phone_regex, value.replace(" ", "").replace("-", "")):
                raise serializers.ValidationError("Invalid phone number format.")

        return value


class ResetPasswordSerializer(serializers.Serializer):
    """Serializer for password reset - supports both token and OTP methods"""

    new_password = serializers.CharField(
        write_only=True, validators=[validate_password]
    )
    confirm_new_password = serializers.CharField(write_only=True)

    # For email-based reset
    token = serializers.CharField(required=False, allow_blank=True)

    # For SMS-based reset
    otp = serializers.CharField(max_length=6, required=False, allow_blank=True)
    identifier = serializers.CharField(
        required=False, allow_blank=True, help_text="Email or phone number"
    )

    def validate(self, attrs):
        # Check password confirmation
        if attrs["new_password"] != attrs["confirm_new_password"]:
            raise serializers.ValidationError(
                {"confirm_new_password": "Password fields didn't match."}
            )

        # Check that either token OR (otp + identifier) is provided
        token = attrs.get("token")
        otp = attrs.get("otp")
        identifier = attrs.get("identifier")

        if not token and not (otp and identifier):
            raise serializers.ValidationError(
                "Either 'token' or both 'otp' and 'identifier' must be provided."
            )

        if token and (otp or identifier):
            raise serializers.ValidationError(
                "Provide either 'token' or 'otp + identifier', not both."
            )

        # Validate OTP format if provided
        if otp and not otp.isdigit():
            raise serializers.ValidationError({"otp": "OTP must contain only digits."})

        # Validate identifier format if provided
        if identifier:
            if "@" in identifier:
                # Email validation
                email_regex = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
                if not re.match(email_regex, identifier):
                    raise serializers.ValidationError(
                        {"identifier": "Invalid email format."}
                    )
            else:
                # Phone validation
                phone_regex = r"^\+?[1-9]\d{1,14}$"
                if not re.match(
                    phone_regex, identifier.replace(" ", "").replace("-", "")
                ):
                    raise serializers.ValidationError(
                        {"identifier": "Invalid phone number format."}
                    )

        return attrs


class ResendPasswordResetOTPSerializer(serializers.Serializer):
    """Serializer for resending password reset OTP"""

    identifier = serializers.CharField(help_text="Phone number to resend OTP to")

    def validate_identifier(self, value):
        """Validate phone number format"""
        # Should be a phone number for OTP resend
        if "@" in value:
            raise serializers.ValidationError("OTP can only be sent to phone numbers.")

        phone_regex = r"^\+?[1-9]\d{1,14}$"
        if not re.match(phone_regex, value.replace(" ", "").replace("-", "")):
            raise serializers.ValidationError("Invalid phone number format.")

        return value


# PROFILE MANAGEMENT SERIALIZERS
class UpdateProfileSerializer(serializers.ModelSerializer):
    """Serializer for updating user profile"""

    class Meta:
        model = User
        fields = ["first_name", "last_name"]


# OTP STATUS SERIALIZERS


class OTPStatusSerializer(serializers.Serializer):
    """Serializer for OTP status response"""

    sms_otp = serializers.DictField()
    email_change = serializers.DictField()
    password_reset = serializers.DictField()
    user_2fa_enabled = serializers.BooleanField()
    user_has_phone = serializers.BooleanField()
