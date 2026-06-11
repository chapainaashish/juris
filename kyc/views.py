import stripe
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from lawyer.models import LawyerProfile
from lawyer.permissions import IsLawyerVendor

from .models import KYCVerification
from .serializers import KYCVerificationSerializer, KYCVerificationSessionSerializer

stripe.api_key = settings.STRIPE_SECRET_KEY


class KYCVerificationView(APIView):
    """Simple KYC verification operations"""

    permission_classes = [IsLawyerVendor]

    def get(self, request):
        """Get KYC verification status"""
        try:
            lawyer_profile = LawyerProfile.objects.get(
                vendor_profile__user=request.user
            )
            kyc_verification = KYCVerification.objects.filter(
                lawyer_profile=lawyer_profile
            ).first()

            if not kyc_verification:
                return Response({"status": "not_started", "is_verified": False})

            serializer = KYCVerificationSerializer(kyc_verification)
            return Response(serializer.data)

        except LawyerProfile.DoesNotExist:
            return Response(
                {"error": "Lawyer profile not found"}, status=status.HTTP_404_NOT_FOUND
            )

    def post(self, request):
        """Start KYC verification with duplicate prevention"""
        try:
            # Validate input
            serializer = KYCVerificationSessionSerializer(data=request.data)
            if not serializer.is_valid():
                return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

            lawyer_profile = LawyerProfile.objects.get(
                vendor_profile__user=request.user
            )

            # Check if already verified
            existing_kyc = KYCVerification.objects.filter(
                lawyer_profile=lawyer_profile, status="verified"
            ).first()
            if existing_kyc:
                return Response(
                    {"error": "Already verified"}, status=status.HTTP_400_BAD_REQUEST
                )

            # Check if a verification is already in progress
            in_progress_kyc = (
                KYCVerification.objects.filter(lawyer_profile=lawyer_profile)
                .exclude(status="verified")
                .first()
            )

            if in_progress_kyc:
                return Response(
                    {
                        "message": "Verification already in progress",
                        "verification_session_id": in_progress_kyc.stripe_verification_session_id,
                        "status": in_progress_kyc.status,
                    },
                    status=status.HTTP_200_OK,
                )

            # Create Stripe verification session
            stripe_session = stripe.identity.VerificationSession.create(
                type="document",
                metadata={"lawyer_profile_id": str(lawyer_profile.id)},
                return_url=serializer.validated_data["return_url"],
                options={
                    "document": {
                        "allowed_types": ["driving_license", "id_card", "passport"],
                        "require_matching_selfie": True,
                    }
                },
            )

            # Create new KYC record (no update_or_create since we already checked)
            kyc_verification = KYCVerification.objects.create(
                lawyer_profile=lawyer_profile,
                stripe_verification_session_id=stripe_session.id,
                status=stripe_session.status,
            )

            return Response(
                {
                    "verification_session_id": stripe_session.id,
                    "url": stripe_session.url,
                    "status": stripe_session.status,
                },
                status=status.HTTP_201_CREATED,
            )

        except LawyerProfile.DoesNotExist:
            return Response(
                {"error": "Lawyer profile not found"}, status=status.HTTP_404_NOT_FOUND
            )
        except stripe.error.StripeError as e:
            return Response(
                {"error": "Failed to create verification session"},
                status=status.HTTP_400_BAD_REQUEST,
            )
