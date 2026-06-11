from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.text import slugify
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, status, viewsets
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from lawyer.models import LawyerProfile
from lawyer.permissions import IsLawyerVendor

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
from .serializers import (
    AddressCreationSerializer,
    AddressSerializer,
    AvatarUploadSerializer,
    BusinessNameSerializer,
    CategorySelectionSerializer,
    CategorySerializer,
    CertificateSerializer,
    CertificateUpdateSerializer,
    CertificateUploadSerializer,
    LanguageSelectionSerializer,
    LanguageSerializer,
    LegalInfoSerializer,
    MediaSerializer,
    MediaUpdateSerializer,
    MediaUploadSerializer,
    ProfileAdditionalInfoSerializer,
    ProfileCompletionSessionSerializer,
    ServiceCategoryCreateSerializer,
    ServiceCategorySerializer,
    ServiceCreateSerializer,
    ServiceSerializer,
    VendorLegalInfoSerializer,
    VendorProfileSerializer,
    VendorProfileUpdateSerializer,
)
from .utils import generate_cloudinary_signature, upload_to_cloudinary


# CORE DATA VIEWS (Independent models - categories, languages)
class CategoryListView(generics.ListAPIView):
    """Get a list of all available categories"""

    queryset = Category.objects.all()
    serializer_class = CategorySerializer

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class LanguageListView(generics.ListAPIView):
    """Get a list of all available languages"""

    queryset = Language.objects.all()
    serializer_class = LanguageSerializer

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


class BarAssociationListView(APIView):
    """Get a list of all available bar associations"""

    def get(self, request):
        # Get the choices from the model
        choices = VendorLegalInfo.BAR_ASSOCIATION_CHOICES

        # Format the choices as a list of dictionaries
        formatted_choices = [
            {"value": value, "label": label} for value, label in choices
        ]

        return Response(formatted_choices, status=status.HTTP_200_OK)


# PROFILE COMPLETION SESSION VIEWS (Multi-step workflow)
class StartProfileCompletionView(APIView):
    """Start a new profile completion session or retrieve an existing one"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        with transaction.atomic():
            User = get_user_model()
            user = User.objects.select_for_update().get(pk=request.user.pk)
            existing_session = ProfileCompletionSession.objects.filter(
                user=user, is_completed=False, expires_at__gt=timezone.now()
            ).first()

            if existing_session:
                serializer = ProfileCompletionSessionSerializer(existing_session)
                return Response(
                    {
                        "token": existing_session.token,
                        "message": "Existing session retrieved",
                        "data": serializer.data,
                    },
                    status=status.HTTP_200_OK,
                )

            session = ProfileCompletionSession(user=user)
            session.save()

            return Response(
                {
                    "token": session.token,
                    "message": "New profile completion session created",
                },
                status=status.HTTP_201_CREATED,
            )


class ProfileProgressView(APIView):
    """Get the current progress of a profile completion session"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        token = request.query_params.get("token")
        if not token:
            return Response(
                {"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        session = get_object_or_404(
            ProfileCompletionSession,
            token=token,
            is_completed=False,
            expires_at__gt=timezone.now(),
        )

        if session.user != request.user:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        serializer = ProfileCompletionSessionSerializer(session)
        return Response(serializer.data, status=status.HTTP_200_OK)


# STEP-BY-STEP PROFILE COMPLETION VIEWS
class CategoryStepView(APIView):
    """Handle the category selection step"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response(
                {"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        session = get_object_or_404(
            ProfileCompletionSession,
            token=token,
            is_completed=False,
            expires_at__gt=timezone.now(),
        )

        if session.user != request.user:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        serializer = CategorySelectionSerializer(data=request.data)
        if serializer.is_valid():
            category_id = serializer.validated_data["category_id"]
            category = get_object_or_404(Category, id=category_id)

            session.category = category
            session.save()

            return Response(
                {"message": "Category saved successfully"}, status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BusinessNameStepView(APIView):
    """Handle the business name step"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response(
                {"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        session = get_object_or_404(
            ProfileCompletionSession,
            token=token,
            is_completed=False,
            expires_at__gt=timezone.now(),
        )

        if session.user != request.user:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        serializer = BusinessNameSerializer(data=request.data)
        if serializer.is_valid():
            session.business_name = serializer.validated_data["business_name"]
            session.save()

            return Response(
                {"message": "Business name saved successfully"},
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AddressStepView(APIView):
    """Handle the address step"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response(
                {"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        session = get_object_or_404(
            ProfileCompletionSession,
            token=token,
            is_completed=False,
            expires_at__gt=timezone.now(),
        )

        if session.user != request.user:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        address_data = {
            "street": request.data.get("street"),
            "city": request.data.get("city"),
            "postcode": request.data.get("postcode"),
            "country": request.data.get("country"),
            "latitude": request.data.get("latitude"),
            "longitude": request.data.get("longitude"),
        }

        serializer = AddressCreationSerializer(data=address_data)
        if serializer.is_valid():
            address = Address.objects.create(**serializer.validated_data)
            session.address = address
            session.save()

            return Response(
                {"message": "Address saved successfully"}, status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LanguagesStepView(APIView):
    """Handle the languages selection step"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response(
                {"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        session = get_object_or_404(
            ProfileCompletionSession,
            token=token,
            is_completed=False,
            expires_at__gt=timezone.now(),
        )

        if session.user != request.user:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        serializer = LanguageSelectionSerializer(data=request.data)
        if serializer.is_valid():
            language_ids = serializer.validated_data.get("language_ids", [])

            # Validate that all language_ids exist in the database
            if language_ids:
                existing_ids = set(
                    Language.objects.filter(id__in=language_ids).values_list(
                        "id", flat=True
                    )
                )
                if len(existing_ids) != len(set(language_ids)):
                    return Response(
                        {
                            "error": "Invalid language selection. Some language IDs do not exist."
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            # Clear previous languages and add new ones
            session.languages.clear()

            if language_ids:
                languages = Language.objects.filter(id__in=language_ids)
                session.languages.add(*languages)

            session.save()

            return Response(
                {"message": "Languages saved successfully"}, status=status.HTTP_200_OK
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AvatarStepView(APIView):
    """Handle the avatar upload step with size validation"""

    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response(
                {"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        session = get_object_or_404(
            ProfileCompletionSession,
            token=token,
            is_completed=False,
            expires_at__gt=timezone.now(),
        )

        if session.user != request.user:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # Try to use AvatarUploadSerializer first (for URL uploads)
        serializer = AvatarUploadSerializer(data=request.data)
        if serializer.is_valid():
            avatar_url = serializer.validated_data["avatar_url"]
            session.avatar_url = avatar_url
            session.save()

            return Response(
                {
                    "message": "Avatar saved successfully",
                    "avatar_url": session.avatar_url,
                },
                status=status.HTTP_200_OK,
            )

        # Handle file upload fallback if URL validation fails
        avatar_file = request.data.get("avatar")
        if avatar_file:
            MAX_SIZE = 2 * 1024 * 1024  # 2MB in bytes

            if avatar_file.size > MAX_SIZE:
                return Response(
                    {"error": "Avatar image size must not exceed 2MB"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Generate vendor ID for upload
            if session.business_name:
                vendor_id = slugify(session.business_name)
            elif session.user:
                vendor_id = f"user_{session.user.id}"
            else:
                vendor_id = f"session_{session.token[:8]}"

            try:
                upload_result = upload_to_cloudinary(
                    avatar_file, vendor_id=vendor_id, folder_type="avatars"
                )
                session.avatar_url = upload_result["secure_url"]
                session.save()

                return Response(
                    {
                        "message": "Avatar saved successfully",
                        "avatar_url": session.avatar_url,
                    },
                    status=status.HTTP_200_OK,
                )
            except Exception as e:
                return Response(
                    {"error": "Upload failed, please try again"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LegalInfoStepView(APIView):
    """Handle the legal information step"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response(
                {"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        session = get_object_or_404(
            ProfileCompletionSession,
            token=token,
            is_completed=False,
            expires_at__gt=timezone.now(),
        )

        if session.user != request.user:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # Validate that legal info is only for lawyers
        if not session.category or session.category.name != "Lawyer":
            return Response(
                {"error": "Legal information is only allowed for Lawyers"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        legal_info_data = {
            "first_name_id": request.data.get("first_name_id"),
            "last_name_id": request.data.get("last_name_id"),
            "email": request.data.get("email"),
            "bar_association": request.data.get("bar_association"),
        }

        serializer = LegalInfoSerializer(data=legal_info_data)
        if serializer.is_valid():
            # Store legal info directly in session
            session.first_name_id = serializer.validated_data["first_name_id"]
            session.last_name_id = serializer.validated_data["last_name_id"]
            session.legal_email = serializer.validated_data["email"]
            session.bar_association = serializer.validated_data["bar_association"]
            session.save()

            return Response(
                {"message": "Legal information saved successfully"},
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AdditionalInfoStepView(APIView):
    """Handle the additional information step (bio, experience, social media, etc.)"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response(
                {"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        session = get_object_or_404(
            ProfileCompletionSession,
            token=token,
            is_completed=False,
            expires_at__gt=timezone.now(),
        )

        if session.user != request.user:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        serializer = ProfileAdditionalInfoSerializer(data=request.data)
        if serializer.is_valid():
            for key, value in serializer.validated_data.items():
                if key != "token":  # Skip the token field
                    setattr(session, key, value)

            session.save()

            return Response(
                {"message": "Additional information saved successfully"},
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CompleteProfileView(APIView):
    """Complete the profile and create the vendor profile"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        token = request.data.get("token")
        if not token:
            return Response(
                {"error": "Token is required"}, status=status.HTTP_400_BAD_REQUEST
            )

        session = get_object_or_404(
            ProfileCompletionSession,
            token=token,
            is_completed=False,
            expires_at__gt=timezone.now(),
        )

        if session.user != request.user:
            return Response({"error": "Forbidden"}, status=status.HTTP_403_FORBIDDEN)

        # Validate that all required fields are present
        if (
            not session.user
            or not session.category
            or not session.business_name
            or not session.address
        ):
            return Response(
                {
                    "error": "Missing required information. Make sure all steps are completed."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = session.user
        user.role = "vendor"
        user.vendor_type = session.category.name.lower()
        user.save()

        existing_profile = VendorProfile.objects.filter(user=session.user).first()

        if existing_profile:
            if session.address:
                vendor_address = Address.objects.create(
                    street=session.address.street,
                    city=session.address.city,
                    postcode=session.address.postcode,
                    country=session.address.country,
                    latitude=session.address.latitude,
                    longitude=session.address.longitude,
                )

                if existing_profile.address:
                    old_address = existing_profile.address
                    existing_profile.address = None
                    existing_profile.save()
                    old_address.delete()

                existing_profile.address = vendor_address

            existing_profile.category = session.category
            existing_profile.business_name = session.business_name
            existing_profile.avatar_url = session.avatar_url
            existing_profile.bio = session.bio
            existing_profile.experience = session.experience
            existing_profile.website = session.website
            existing_profile.whatsapp = session.whatsapp
            existing_profile.facebook = session.facebook
            existing_profile.youtube = session.youtube
            existing_profile.instagram = session.instagram
            existing_profile.twitter = session.twitter
            existing_profile.social_media_status = session.social_media_status
            existing_profile.general_link = session.general_link
            existing_profile.is_completed = True
            existing_profile.save()

            # Clear and update languages
            existing_profile.languages.clear()
            existing_profile.languages.add(*session.languages.all())

            # Update or create legal info if it exists and category is Lawyer
            if session.category.name == "Lawyer" and session.first_name_id:
                try:
                    legal_info = VendorLegalInfo.objects.get(
                        vendor_profile=existing_profile
                    )
                    legal_info.first_name_id = session.first_name_id
                    legal_info.last_name_id = session.last_name_id
                    legal_info.email = session.legal_email
                    legal_info.bar_association = session.bar_association
                    legal_info.save()
                except VendorLegalInfo.DoesNotExist:
                    VendorLegalInfo.objects.create(
                        vendor_profile=existing_profile,
                        first_name_id=session.first_name_id,
                        last_name_id=session.last_name_id,
                        email=session.legal_email,
                        bar_association=session.bar_association,
                    )

            profile = existing_profile
        else:
            vendor_address = None
            if session.address:
                vendor_address = Address.objects.create(
                    street=session.address.street,
                    city=session.address.city,
                    postcode=session.address.postcode,
                    country=session.address.country,
                    latitude=session.address.latitude,
                    longitude=session.address.longitude,
                )

            profile = VendorProfile.objects.create(
                user=session.user,
                category=session.category,
                business_name=session.business_name,
                address=vendor_address,
                avatar_url=session.avatar_url,
                bio=session.bio,
                experience=session.experience,
                website=session.website,
                whatsapp=session.whatsapp,
                facebook=session.facebook,
                youtube=session.youtube,
                instagram=session.instagram,
                twitter=session.twitter,
                social_media_status=session.social_media_status,
                general_link=session.general_link,
                is_completed=True,
            )

            profile.languages.add(*session.languages.all())

            # Add legal info if it exists and category is Lawyer
            if session.category.name == "Lawyer" and session.first_name_id:
                VendorLegalInfo.objects.create(
                    vendor_profile=profile,
                    first_name_id=session.first_name_id,
                    last_name_id=session.last_name_id,
                    email=session.legal_email,
                    bar_association=session.bar_association,
                )

        if session.category.name == "Lawyer":
            try:
                # Check if lawyer profile already exists
                lawyer_profile = LawyerProfile.objects.get(vendor_profile=profile)
            except LawyerProfile.DoesNotExist:
                LawyerProfile.objects.create(
                    vendor_profile=profile,
                    registration_number="",
                    fiscal_code="",
                    kyc_verification_status="unverified",
                )

        session.is_completed = True
        session.save()

        serializer = VendorProfileSerializer(profile)
        return Response(
            {"message": "Profile completed successfully", "profile": serializer.data},
            status=status.HTTP_200_OK,
        )


# VENDOR PROFILE MANAGEMENT VIEWS
class VendorProfileDetailView(generics.RetrieveAPIView):
    """Get the vendor profile for the current user"""

    permission_classes = [IsAuthenticated]
    serializer_class = VendorProfileSerializer

    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def get_object(self):
        return get_object_or_404(VendorProfile, user=self.request.user)


class VendorProfileUpdateView(APIView):
    """Update vendor profile information including business name and languages"""

    permission_classes = [IsAuthenticated]

    def put(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)

        serializer = VendorProfileUpdateSerializer(
            profile, data=request.data, partial=True
        )
        if serializer.is_valid():
            serializer.save()

            return Response(
                VendorProfileSerializer(profile).data,
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AddressDetailView(APIView):
    """Get or update address for vendor profile"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)
        if profile.address:
            serializer = AddressSerializer(profile.address)
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response({"error": "No address found"}, status=status.HTTP_404_NOT_FOUND)

    def put(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)

        if profile.address:
            serializer = AddressSerializer(
                profile.address, data=request.data, partial=True
            )
            if serializer.is_valid():
                serializer.save()
                return Response(serializer.data, status=status.HTTP_200_OK)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Create new address if none exists
        serializer = AddressSerializer(data=request.data)
        if serializer.is_valid():
            address = serializer.save()
            profile.address = address
            profile.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class VendorLegalInfoView(APIView):
    """Get or update legal info for vendor profile"""

    permission_classes = [IsLawyerVendor]

    def get(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)
        try:
            legal_info = VendorLegalInfo.objects.get(vendor_profile=profile)
            serializer = VendorLegalInfoSerializer(legal_info)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except VendorLegalInfo.DoesNotExist:
            return Response(
                {"error": "No legal info found"}, status=status.HTTP_404_NOT_FOUND
            )

    def put(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)

        try:
            legal_info = VendorLegalInfo.objects.get(vendor_profile=profile)
            serializer = VendorLegalInfoSerializer(
                legal_info, data=request.data, partial=True
            )
        except VendorLegalInfo.DoesNotExist:
            serializer = VendorLegalInfoSerializer(data=request.data)

        if serializer.is_valid():
            if hasattr(serializer, "instance") and serializer.instance:
                serializer.save()
            else:
                legal_info = serializer.save(vendor_profile=profile)

            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ProfileAvatarUpdateView(APIView):
    """Update avatar for existing vendor profile"""

    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def put(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)

        # AvatarUploadSerializer first (for URL uploads)
        serializer = AvatarUploadSerializer(data=request.data)
        if serializer.is_valid():
            avatar_url = serializer.validated_data["avatar_url"]
            profile.avatar_url = avatar_url
            profile.save()

            return Response(
                {
                    "message": "Avatar updated successfully",
                    "avatar_url": profile.avatar_url,
                },
                status=status.HTTP_200_OK,
            )

        # Handle file upload fallback if URL validation fails
        avatar_file = request.data.get("avatar")
        if avatar_file:
            MAX_SIZE = 2 * 1024 * 1024  # 2MB in bytes

            if avatar_file.size > MAX_SIZE:
                return Response(
                    {"error": "Avatar image size must not exceed 2MB"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Generate vendor folder for upload
            vendor_folder = slugify(profile.business_name) or f"vendor_{profile.id}"

            try:
                upload_result = upload_to_cloudinary(
                    avatar_file, vendor_id=vendor_folder, folder_type="avatars"
                )
                profile.avatar_url = upload_result["secure_url"]
                profile.save()

                return Response(
                    {
                        "message": "Avatar updated successfully",
                        "avatar_url": profile.avatar_url,
                    },
                    status=status.HTTP_200_OK,
                )
            except Exception as e:
                return Response(
                    {"error": "Upload failed, please try again"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def get(self, request):
        """Get current avatar URL"""
        profile = get_object_or_404(VendorProfile, user=request.user)
        return Response(
            {"avatar_url": profile.avatar_url, "business_name": profile.business_name},
            status=status.HTTP_200_OK,
        )


# SERVICE MANAGEMENT VIEWSETS
class ServiceCategoryViewSet(viewsets.ViewSet):
    """API endpoints that allow vendors to manage their service categories"""

    permission_classes = [IsAuthenticated]

    def list(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)
        categories = ServiceCategory.objects.filter(vendor_profile=profile)
        serializer = ServiceCategorySerializer(categories, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def retrieve(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        category = get_object_or_404(ServiceCategory, id=pk, vendor_profile=profile)
        serializer = ServiceCategorySerializer(category)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)

        serializer = ServiceCategoryCreateSerializer(data=request.data)
        if serializer.is_valid():
            category = ServiceCategory.objects.create(
                vendor_profile=profile,
                name=serializer.validated_data.get("name"),
                description=serializer.validated_data.get("description"),
                is_active=serializer.validated_data.get("is_active", True),
            )

            return Response(
                ServiceCategorySerializer(category).data,
                status=status.HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        category = get_object_or_404(ServiceCategory, id=pk, vendor_profile=profile)

        serializer = ServiceCategoryCreateSerializer(data=request.data)
        if serializer.is_valid():
            # Update the fields
            category.name = serializer.validated_data.get("name", category.name)
            category.description = serializer.validated_data.get(
                "description", category.description
            )
            category.is_active = serializer.validated_data.get(
                "is_active", category.is_active
            )

            category.save()

            return Response(
                ServiceCategorySerializer(category).data,
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        category = get_object_or_404(ServiceCategory, id=pk, vendor_profile=profile)
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServiceViewSet(viewsets.ViewSet):
    """API endpoints that allow vendors to manage their services"""

    permission_classes = [IsAuthenticated]
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def list(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)
        services = Service.objects.filter(vendor_profile=profile)
        serializer = ServiceSerializer(services, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def retrieve(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        service = get_object_or_404(Service, id=pk, vendor_profile=profile)
        serializer = ServiceSerializer(service)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)

        image_url = request.data.get("image_url")
        image_file = request.data.get("image")

        # Check if image_file is actually a file upload (has size attribute) and not a URL string
        if image_file and hasattr(image_file, "size") and not image_url:
            if image_file.size > 5 * 1024 * 1024:
                return Response(
                    {"error": "Image size must not exceed 5MB"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            vendor_folder = slugify(profile.business_name) or f"vendor_{profile.id}"

            try:
                upload_result = upload_to_cloudinary(
                    image_file, vendor_id=vendor_folder, folder_type="services"
                )
                image_url = upload_result["secure_url"]
            except Exception:
                return Response(
                    {"error": "Upload failed"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )
        elif image_file and not hasattr(image_file, "size"):
            # If image_file is a string (URL), treat it as image_url
            image_url = image_file

        # Add image_url to request data if we got one
        data = request.data.copy()
        if image_url:
            data["image"] = image_url

        serializer = ServiceCreateSerializer(data=data)
        if serializer.is_valid():
            category_id = serializer.validated_data.get("category").id
            category = get_object_or_404(
                ServiceCategory, id=category_id, vendor_profile=profile
            )

            # Get validated data and remove category to avoid duplicate
            service_data = serializer.validated_data.copy()
            service_data.pop("category", None)  # Remove category from validated_data

            # Create service with explicit category and remaining data
            service = Service.objects.create(
                vendor_profile=profile, category=category, **service_data
            )

            return Response(
                ServiceSerializer(service).data,
                status=status.HTTP_201_CREATED,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        service = get_object_or_404(Service, id=pk, vendor_profile=profile)

        # Handle image upload if provided
        image_url = request.data.get("image_url")
        image_file = request.data.get("image")

        if image_file and not image_url:
            if image_file.size > 5 * 1024 * 1024:
                return Response(
                    {"error": "Image size must not exceed 5MB"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            vendor_folder = slugify(profile.business_name) or f"vendor_{profile.id}"

            try:
                upload_result = upload_to_cloudinary(
                    image_file, vendor_id=vendor_folder, folder_type="services"
                )
                image_url = upload_result["secure_url"]
            except Exception:
                return Response(
                    {"error": "Upload failed"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        # Add image_url to request data if we got one
        data = request.data.copy()
        if image_url:
            data["image"] = image_url

        serializer = ServiceCreateSerializer(data=data, partial=True)
        if serializer.is_valid():
            # Check if provided category belongs to this vendor
            if "category" in serializer.validated_data:
                category_id = serializer.validated_data.get("category").id
                get_object_or_404(
                    ServiceCategory, id=category_id, vendor_profile=profile
                )

            # Update service
            for key, value in serializer.validated_data.items():
                setattr(service, key, value)
            service.save()

            return Response(
                ServiceSerializer(service).data,
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        service = get_object_or_404(Service, id=pk, vendor_profile=profile)
        service.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# MEDIA MANAGEMENT VIEWSETS
class MediaViewSet(viewsets.ViewSet):
    """API endpoints that allow vendors to manage their media files"""

    permission_classes = [IsAuthenticated]
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def list(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)
        media = Media.objects.filter(vendor_profile=profile)
        serializer = MediaSerializer(media, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @swagger_auto_schema(
        operation_description="Retrieve a specific media file",
        responses={
            200: MediaSerializer(),
            404: "Media not found",
        },
        tags=["Media Management"],
    )
    def retrieve(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        media = get_object_or_404(Media, id=pk, vendor_profile=profile)
        serializer = MediaSerializer(media)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)

        # Try to use MediaUploadSerializer first (for URL uploads)
        serializer = MediaUploadSerializer(data=request.data)
        if serializer.is_valid():
            file_url = serializer.validated_data["file_url"]
            file_type = serializer.validated_data["file_type"]
            title = serializer.validated_data.get("title")
            description = serializer.validated_data.get("description")

            # Create media record
            media = Media.objects.create(
                vendor_profile=profile,
                title=title,
                description=description,
                file=file_url,
                file_type=file_type,
            )

            return Response(
                MediaSerializer(media).data,
                status=status.HTTP_201_CREATED,
            )

        # Handle file upload fallback if URL validation fails
        file = request.data.get("file")
        file_type = request.data.get("file_type")

        if file and file_type:
            if file_type == "image":
                MAX_SIZE = 5 * 1024 * 1024  # 5MB
                folder_type = "media/images"
            elif file_type == "video":
                MAX_SIZE = 50 * 1024 * 1024  # 50MB
                folder_type = "media/videos"
            elif file_type == "document":
                MAX_SIZE = 10 * 1024 * 1024  # 10MB
                folder_type = "media/documents"
            else:
                MAX_SIZE = 5 * 1024 * 1024  # 5MB default
                folder_type = "media/other"

            if file.size > MAX_SIZE:
                return Response(
                    {
                        "error": f"File size exceeds the limit of {MAX_SIZE / (1024 * 1024)}MB for {file_type} files"
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            vendor_folder = slugify(profile.business_name) or f"vendor_{profile.id}"

            try:
                upload_result = upload_to_cloudinary(
                    file, vendor_id=vendor_folder, folder_type=folder_type
                )
                file_url = upload_result["secure_url"]

                media = Media.objects.create(
                    vendor_profile=profile,
                    title=request.data.get("title"),
                    description=request.data.get("description"),
                    file=file_url,
                    file_type=file_type,
                )

                return Response(
                    MediaSerializer(media).data,
                    status=status.HTTP_201_CREATED,
                )
            except Exception as e:
                return Response(
                    {"error": "Upload failed, please try again"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        media = get_object_or_404(Media, id=pk, vendor_profile=profile)

        serializer = MediaUpdateSerializer(data=request.data)
        if serializer.is_valid():
            if "title" in serializer.validated_data:
                media.title = serializer.validated_data.get("title")
            if "description" in serializer.validated_data:
                media.description = serializer.validated_data.get("description")

            media.save()

            return Response(
                MediaSerializer(media).data,
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        media = get_object_or_404(Media, id=pk, vendor_profile=profile)
        media.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CertificateViewSet(viewsets.ViewSet):
    """API endpoints that allow vendors to manage their certificates"""

    permission_classes = [IsAuthenticated]
    parser_classes = (JSONParser, MultiPartParser, FormParser)

    def list(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)
        certificates = Certificate.objects.filter(vendor_profile=profile)
        serializer = CertificateSerializer(certificates, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def retrieve(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        certificate = get_object_or_404(Certificate, id=pk, vendor_profile=profile)
        serializer = CertificateSerializer(certificate)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def create(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)

        # Try to use CertificateUploadSerializer first (for URL uploads)
        serializer = CertificateUploadSerializer(data=request.data)
        if serializer.is_valid():
            title = serializer.validated_data["title"]
            details = serializer.validated_data.get("details")
            file_url = serializer.validated_data["file_url"]

            certificate = Certificate.objects.create(
                vendor_profile=profile,
                title=title,
                details=details,
                file=file_url,
                status="active",
            )

            return Response(
                CertificateSerializer(certificate).data,
                status=status.HTTP_201_CREATED,
            )

        # Handle file upload fallback if URL validation fails
        file = request.data.get("file")
        title = request.data.get("title")

        if file and title:
            MAX_SIZE = 5 * 1024 * 1024
            if file.size > MAX_SIZE:
                return Response(
                    {"error": "Certificate file size must not exceed 5MB"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            vendor_folder = slugify(profile.business_name) or f"vendor_{profile.id}"

            try:
                upload_result = upload_to_cloudinary(
                    file, vendor_id=vendor_folder, folder_type="certificates"
                )
                file_url = upload_result["secure_url"]

                certificate = Certificate.objects.create(
                    vendor_profile=profile,
                    title=title,
                    details=request.data.get("details"),
                    file=file_url,
                    status="active",
                )

                return Response(
                    CertificateSerializer(certificate).data,
                    status=status.HTTP_201_CREATED,
                )
            except Exception as e:
                return Response(
                    {"error": "Upload failed, please try again"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def update(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        certificate = get_object_or_404(Certificate, id=pk, vendor_profile=profile)

        serializer = CertificateUpdateSerializer(data=request.data)
        if serializer.is_valid():
            if "title" in serializer.validated_data:
                certificate.title = serializer.validated_data.get("title")
            if "details" in serializer.validated_data:
                certificate.details = serializer.validated_data.get("details")
            if "status" in serializer.validated_data:
                certificate.status = serializer.validated_data.get("status")

            certificate.save()

            return Response(
                CertificateSerializer(certificate).data,
                status=status.HTTP_200_OK,
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def destroy(self, request, pk=None):
        profile = get_object_or_404(VendorProfile, user=request.user)
        certificate = get_object_or_404(Certificate, id=pk, vendor_profile=profile)
        certificate.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# CLOUDINARY SIGNATURE VIEWS (File upload utilities)
class CloudinarySignatureView(APIView):
    """Generate a signature for direct uploads to Cloudinary with size limit enforcement"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Get vendor profile for the user if it exists
        vendor_profile = VendorProfile.objects.filter(user=request.user).first()

        folder_type = request.query_params.get("folder_type", "avatars")

        if vendor_profile:
            vendor_folder = (
                slugify(vendor_profile.business_name) or f"vendor_{vendor_profile.id}"
            )
            folder = f"vendors/{vendor_folder}/{folder_type}"
        else:
            folder = f"vendors/user_{request.user.id}/{folder_type}"

        signature_data = generate_cloudinary_signature(
            folder=folder, options={"max_file_size": 2000000}  # 2MB in bytes
        )

        return Response(signature_data, status=status.HTTP_200_OK)


class CloudinaryMediaSignatureView(APIView):
    """Generate a signature for direct uploads to Cloudinary for media files"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)

        file_type = request.query_params.get("file_type", "image")
        vendor_folder = slugify(profile.business_name) or f"vendor_{profile.id}"

        # Determine folder path based on file type
        if file_type == "image":
            folder = f"vendors/{vendor_folder}/media/images"
            max_size = 5 * 1024 * 1024  # 5MB for images
        elif file_type == "video":
            folder = f"vendors/{vendor_folder}/media/videos"
            max_size = 50 * 1024 * 1024  # 50MB for videos
        elif file_type == "document":
            folder = f"vendors/{vendor_folder}/media/documents"
            max_size = 10 * 1024 * 1024  # 10MB for documents
        else:
            folder = f"vendors/{vendor_folder}/media/other"
            max_size = 5 * 1024 * 1024  # 5MB default

        # Generate signature with size limit
        signature_data = generate_cloudinary_signature(
            folder=folder, options={"max_file_size": max_size}
        )

        return Response(signature_data, status=status.HTTP_200_OK)


class CloudinaryCertificateSignatureView(APIView):
    """Generate a signature for direct uploads to Cloudinary for certificates"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile = get_object_or_404(VendorProfile, user=request.user)
        vendor_folder = slugify(profile.business_name) or f"vendor_{profile.id}"
        folder = f"vendors/{vendor_folder}/certificates"
        # Generate signature with size limit (5MB for certificates)
        signature_data = generate_cloudinary_signature(
            folder=folder, options={"max_file_size": 5 * 1024 * 1024}
        )
        return Response(signature_data, status=status.HTTP_200_OK)
