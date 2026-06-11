import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core import signing
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.shortcuts import redirect
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.html import strip_tags
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from social_core.exceptions import AuthAlreadyAssociated, AuthForbidden, MissingBackend
from social_django.utils import load_backend, load_strategy

from .models import (
    PasswordResetToken,
)
from .redis_otp_service import RedisOTPService
from .redis_token_store import RedisTokenStore
from .serializers import (
    ChangeEmailRequestSerializer,
    ChangePasswordSerializer,
    CheckEmailSerializer,
    ForgotPasswordSerializer,
    LoginSerializer,
    OTPStatusSerializer,
    ResendPasswordResetOTPSerializer,
    ResetPasswordSerializer,
    SignupSerializer,
    Toggle2FASerializer,
    UpdatePhoneSerializer,
    UpdateProfileSerializer,
    UserSerializer,
    VerifyEmailChangeSerializer,
    VerifyOTPSerializer,
)
from .tokens import email_verification_token

User = get_user_model()


def set_refresh_token_cookie(response, refresh_token):
    """Helper function to set the refresh token as an HttpOnly cookie using Django settings"""
    response.set_cookie(
        key=getattr(settings, "AUTH_COOKIE", "refresh_token"),
        value=refresh_token,
        httponly=getattr(settings, "AUTH_COOKIE_HTTP_ONLY", True),
        secure=getattr(settings, "AUTH_COOKIE_SECURE", not settings.DEBUG),
        samesite=getattr(settings, "AUTH_COOKIE_SAMESITE", "Strict"),
        max_age=getattr(settings, "AUTH_COOKIE_MAX_AGE", 7 * 24 * 60 * 60),
        path=getattr(settings, "AUTH_COOKIE_PATH", "/"),
    )
    return response


def delete_refresh_token_cookie(response):
    """Helper function to delete the refresh token cookie using Django settings"""
    response.delete_cookie(
        getattr(settings, "AUTH_COOKIE", "refresh_token"),
        path=getattr(settings, "AUTH_COOKIE_PATH", "/"),
    )
    return response


def get_refresh_token_from_cookies(request):
    """Helper function to get refresh token from cookies using Django settings"""
    cookie_name = getattr(settings, "AUTH_COOKIE", "refresh_token")
    return request.COOKIES.get(cookie_name)


# USER MANAGEMENT VIEWS


class CheckEmailView(APIView):
    """Check if an email is available for registration"""

    permission_classes = [AllowAny]

    def post(self, request):
        """
        Check if an email is available for registration.
        Returns whether the email exists in the system and an appropriate message.
        """
        serializer = CheckEmailSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            exists = User.objects.filter(email=email).exists()

            return Response(
                {
                    "available": not exists,
                    "message": (
                        "Email is not available."
                        if exists
                        else "Email is available for registration."
                    ),
                },
                status=status.HTTP_200_OK,
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UpdatePhoneView(APIView):
    """Update authenticated user's phone number"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Update the authenticated user's phone number.
        Validates that the phone number is not already in use by another account.
        """
        serializer = UpdatePhoneSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            phone_number = serializer.validated_data["phone_number"]

            # Check if phone number is already used by another user
            if (
                User.objects.exclude(id=user.id)
                .filter(phone_number=phone_number)
                .exists()
            ):
                return Response(
                    {
                        "success": False,
                        "detail": "This phone number is already associated with another account.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Update user's phone number
            user.phone_number = phone_number
            user.save()

            return Response(
                {
                    "success": True,
                    "detail": "Phone number updated successfully.",
                    "user": UserSerializer(user).data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )


# AUTHENTICATION VIEWS


class SignupView(APIView):
    """User registration with email verification"""

    permission_classes = [AllowAny]

    def post(self, request):
        """
        Create a new user account.
        Sends a verification email to the provided email address.
        """
        serializer = SignupSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()

            # Use environment variable for expiration time
            user.email_verification_valid_until = timezone.now() + timedelta(
                hours=settings.EMAIL_VERIFICATION_VALID_UNTIL_HOURS
            )
            user.save()

            uid = urlsafe_base64_encode(force_bytes(user.pk))
            token = email_verification_token.make_token(user)

            # Use environment variable for verification link
            verification_link = f"{settings.FRONTEND_URL}/email/verify/{uid}/{token}/"

            # Send verification email in production
            if not settings.DEBUG:
                context = {
                    "user": user,
                    "site_name": settings.SITE_NAME,
                    "verification_link": verification_link,
                    "expires_time": f"{settings.EMAIL_VERIFICATION_VALID_UNTIL_HOURS} hour{'s' if settings.EMAIL_VERIFICATION_VALID_UNTIL_HOURS != 1 else ''}",
                }

                subject = "Confirm your email address - Juris"
                html_message = render_to_string(
                    "users/emails/email_verification.html", context
                )
                plain_message = strip_tags(html_message)

                send_mail(
                    subject,
                    plain_message,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    html_message=html_message,
                    fail_silently=False,
                )
            else:
                print(verification_link)

            return Response(
                {
                    "success": True,
                    "detail": f"User created. Verification email sent. The link will expire in {settings.EMAIL_VERIFICATION_VALID_UNTIL_HOURS} hours.",
                },
                status=status.HTTP_201_CREATED,
            )

        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )


class LoginView(APIView):
    """User login with optional 2FA"""

    permission_classes = [AllowAny]

    def post(self, request):
        """
        Authenticates a user and returns access tokens.
        If 2FA is enabled, creates a signed token instead of storing in session.
        If email is not verified, sends a new verification email.
        """
        serializer = LoginSerializer(data=request.data)
        if serializer.is_valid():
            email = serializer.validated_data["email"]
            password = serializer.validated_data["password"]

            user = authenticate(username=email, password=password)

            if not user:
                # Increment password attempt counter if user exists
                try:
                    user_obj = User.objects.get(email=email)
                    user_obj.password_attempt += 1
                    user_obj.save()
                except User.DoesNotExist:
                    pass

                return Response(
                    {"success": False, "detail": "Invalid credentials"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # Reset password attempts on successful login
            user.password_attempt = 0
            user.save()

            # Check if the previous verification link has expired or doesn't exist
            if not user.is_email_verified:
                needs_new_verification = (
                    not user.email_verification_valid_until
                    or user.email_verification_valid_until < timezone.now()
                )

                # Set new expiration time from settings
                if needs_new_verification:
                    user.email_verification_valid_until = timezone.now() + timedelta(
                        hours=settings.EMAIL_VERIFICATION_VALID_UNTIL_HOURS
                    )
                    user.save()

                # Generate verification token
                uid = urlsafe_base64_encode(force_bytes(user.pk))
                token = email_verification_token.make_token(user)

                # Use environment variable for verification link
                verification_link = (
                    f"{settings.FRONTEND_URL}/email/verify/{uid}/{token}/"
                )

                # Send verification email in production
                if not settings.DEBUG:
                    context = {
                        "user": user,
                        "site_name": settings.SITE_NAME,
                        "verification_link": verification_link,
                        "expires_time": f"{settings.EMAIL_VERIFICATION_VALID_UNTIL_HOURS} hour{'s' if settings.EMAIL_VERIFICATION_VALID_UNTIL_HOURS != 1 else ''}",
                    }

                    subject = "Confirm your email address - Juris"
                    html_message = render_to_string(
                        "users/emails/email_verification.html", context
                    )
                    plain_message = strip_tags(html_message)

                    send_mail(
                        subject,
                        plain_message,
                        settings.DEFAULT_FROM_EMAIL,
                        [user.email],
                        html_message=html_message,
                        fail_silently=False,
                    )
                else:
                    print(verification_link)

                return Response(
                    {
                        "success": False,
                        "detail": f"Email not verified. A new verification email has been sent. The link will expire in {settings.EMAIL_VERIFICATION_VALID_UNTIL_HOURS} hours.",
                    },
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # Check if 2FA is enabled for the user
            if user.is_2fa_enabled:
                if not user.phone_number:
                    return Response(
                        {
                            "success": False,
                            "detail": "2FA is enabled but no phone number is associated with your account. Please contact support.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Initialize login for OTP verification
                user.has_initiate_login = True
                user.save()

                # Send OTP via SMS using Redis service
                success, message = RedisOTPService.send_sms_otp(user, force=True)

                if not success:
                    return Response(
                        {
                            "success": False,
                            "detail": message,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Create signed token with better data structure
                token_payload = {
                    "user_id": user.id,
                    "timestamp": timezone.now().isoformat(),
                    "action": "2fa_verification",  # Add action type for clarity
                }

                verification_token = signing.dumps(
                    token_payload,
                    salt="2fa-verification",
                )

                if settings.DEBUG:
                    print(
                        f"DEBUG: Created verification token for user {user.id}: {verification_token}"
                    )
                    print(f"DEBUG: Token payload: {token_payload}")

                return Response(
                    {
                        "success": False,
                        "require_2fa": True,
                        "detail": "2FA is enabled. Verification code has been sent to your phone.",
                        "verification_token": verification_token,
                    },
                    status=status.HTTP_200_OK,
                )

            # If 2FA is not enabled, proceed with login
            tokens = RedisTokenStore.store_tokens(user)

            # Create response with access token only (refresh token goes in cookie)
            response = Response(
                {
                    "success": True,
                    "access_token": tokens["access_token"],
                    "user": UserSerializer(user).data,
                }
            )

            # Set refresh token as HttpOnly cookie
            response = set_refresh_token_cookie(response, tokens["refresh_token"])

            return response

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OTPStatusView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # OTP status from Redis for sms/email_change/password_reset
        status_dict = RedisOTPService.get_user_otp_status(request.user.id)

        # Enrich with user state
        status_dict.update(
            {
                "user_2fa_enabled": bool(
                    getattr(request.user, "is_2fa_enabled", False)
                ),
                "user_has_phone": bool(request.user.phone_number),
            }
        )

        data = OTPStatusSerializer(status_dict).data
        return Response(data, status=status.HTTP_200_OK)


class GoogleLoginView(APIView):
    """Google OAuth2 authentication"""

    permission_classes = [AllowAny]

    def post(self, request):
        """
        Authenticates a user with a Google OAuth2 token.
        If 2FA is enabled, creates a signed token instead of storing in session.
        """
        # Get the 'access_token' from the request
        access_token = request.data.get("access_token")

        if not access_token:
            return Response(
                {"success": False, "detail": "Invalid token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Load the Google backend
            strategy = load_strategy(request)
            backend = load_backend(strategy, "google-oauth2", redirect_uri=None)

            # Get the user info from Google
            user = backend.do_auth(access_token)

            if user and user.is_active:
                # Mark the user as email verified since Google verified it
                if not user.is_email_verified:
                    user.is_email_verified = True
                    user.save()

                # Check if 2FA is enabled for the user
                if user.is_2fa_enabled:
                    # Initialize login for OTP verification
                    user.has_initiate_login = True
                    user.save()

                    # Send OTP via SMS using Redis service
                    success, message = RedisOTPService.send_sms_otp(user, force=True)

                    if not success:
                        return Response(
                            {
                                "success": False,
                                "detail": message,
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    # Create signed token instead of session storage
                    verification_token = signing.dumps(
                        {"user_id": user.id, "timestamp": timezone.now().isoformat()},
                        salt="2fa-verification",
                    )

                    return Response(
                        {
                            "success": False,
                            "require_2fa": True,
                            "detail": "2FA is enabled. Verification code has been sent to your phone.",
                            "verification_token": verification_token,
                        },
                        status=status.HTTP_200_OK,
                    )

                # Create JWT tokens if 2FA is not enabled
                tokens = RedisTokenStore.store_tokens(user)

                # Create response with access token only (refresh token goes in cookie)
                response = Response(
                    {
                        "success": True,
                        "access_token": tokens["access_token"],
                        "user": UserSerializer(user).data,
                    }
                )

                # Set refresh token as HttpOnly cookie
                response = set_refresh_token_cookie(response, tokens["refresh_token"])

                return response

            return Response(
                {"success": False, "detail": "Authentication failed"},
                status=status.HTTP_401_UNAUTHORIZED,
            )

        except (MissingBackend, AuthAlreadyAssociated, AuthForbidden) as e:
            return Response(
                {"success": False, "detail": str(e)}, status=status.HTTP_400_BAD_REQUEST
            )


class LogoutView(APIView):
    """User logout with token blacklisting"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Logout a user by blacklisting their refresh token.
        Optional 'logout_all' parameter will invalidate all tokens for this user.
        """
        # Get the refresh token from cookie instead of request body
        refresh_token = get_refresh_token_from_cookies(request)

        if refresh_token:
            # Blacklist the refresh token
            RedisTokenStore.blacklist_token(refresh_token, token_type="refresh")

        # Also invalidate all tokens for this user if requested
        logout_all = request.data.get("logout_all", False)
        if logout_all:
            RedisTokenStore.invalidate_user_tokens(request.user.id)

        # Create response and delete the refresh token cookie
        response = Response(
            {"success": True, "detail": "Successfully logged out."},
            status=status.HTTP_200_OK,
        )

        # Delete refresh token cookie
        response = delete_refresh_token_cookie(response)

        return response


class CustomTokenRefreshView(APIView):
    """Refresh JWT tokens"""

    permission_classes = [AllowAny]

    def post(self, request):
        """
        Get a new access token using a refresh token from cookies.
        The old refresh token is blacklisted and a new one is returned.
        """
        # Get refresh token from cookie
        refresh_token = get_refresh_token_from_cookies(request)

        if not refresh_token:
            return Response(
                {"success": False, "detail": "Refresh token is required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Parse and validate JWT signature/expiration
            token = RefreshToken(refresh_token)
            user_id = token.payload.get("user_id")

            if not user_id:
                return Response(
                    {"success": False, "detail": "Invalid token payload"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # Check if token exists in Redis (not blacklisted)
            redis_user_id = RedisTokenStore.validate_token(
                refresh_token, token_type="refresh"
            )

            if not redis_user_id:
                return Response(
                    {"success": False, "detail": "Token has been revoked or expired"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # Verify user_id matches between JWT and Redis
            if str(user_id) != str(redis_user_id):
                return Response(
                    {"success": False, "detail": "Token user mismatch"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # Get the user from database
            try:
                user = User.objects.get(id=user_id)
            except User.DoesNotExist:
                return Response(
                    {"success": False, "detail": "User not found"},
                    status=status.HTTP_401_UNAUTHORIZED,
                )

            # Blacklist the current refresh token
            RedisTokenStore.blacklist_token(refresh_token, token_type="refresh")

            # Generate new tokens
            tokens = RedisTokenStore.store_tokens(user)

            # Create response with new access token
            response = Response(
                {
                    "success": True,
                    "access_token": tokens["access_token"],
                    "user": UserSerializer(user).data,
                }
            )

            # Set new refresh token as HttpOnly cookie
            response = set_refresh_token_cookie(response, tokens["refresh_token"])

            return response

        except InvalidToken:
            return Response(
                {"success": False, "detail": "Invalid refresh token"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except TokenError as e:
            return Response(
                {"success": False, "detail": f"Token error: {str(e)}"},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except Exception as e:
            return Response(
                {"success": False, "detail": "Token refresh failed"},
                status=status.HTTP_401_UNAUTHORIZED,
            )


# EMAIL VERIFICATION VIEWS


class VerifyEmailView(APIView):
    """Email verification handler"""

    permission_classes = [AllowAny]

    def get(self, request, uidb64, token):
        """
        Verifies a user's email address and returns JSON response instead of redirect.
        """
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)

            # Check if verification link has expired
            if (
                user.email_verification_valid_until
                and user.email_verification_valid_until < timezone.now()
            ):
                return Response(
                    {
                        "success": False,
                        "error": "expired",
                        "message": "This verification link has expired.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            if email_verification_token.check_token(user, token):
                user.is_email_verified = True
                user.email_verification_valid_until = None
                user.save()

                return Response(
                    {
                        "success": True,
                        "message": "Your email has been successfully verified!",
                    },
                    status=status.HTTP_200_OK,
                )

            return Response(
                {
                    "success": False,
                    "error": "invalid",
                    "message": "Invalid verification link.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            return Response(
                {
                    "success": False,
                    "error": "invalid",
                    "message": "Invalid verification link.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


# EMAIL CHANGE VIEWS


class ChangeEmailRequestView(APIView):
    """Request email change with verification"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Request to change the authenticated user's email address.
        Sends a verification code to the new email address using Redis service.
        """
        serializer = ChangeEmailRequestSerializer(
            data=request.data, context={"request": request}
        )
        if serializer.is_valid():
            new_email = serializer.validated_data["new_email"]
            user = request.user

            # Send verification code using Redis service
            success, message = RedisOTPService.send_email_change_verification(
                user, new_email, force=True
            )

            if success:
                return Response(
                    {
                        "success": True,
                        "detail": message,
                        "new_email": new_email,
                    },
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {
                        "success": False,
                        "detail": message,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )


class VerifyEmailChangeView(APIView):
    """Verify email change with code"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Verify the email change using the verification code sent to the new email.
        Uses Redis service for verification.
        """
        serializer = VerifyEmailChangeSerializer(data=request.data)
        if serializer.is_valid():
            verification_code = serializer.validated_data["verification_code"]
            user = request.user

            # Verify the code using Redis service
            success, message = RedisOTPService.verify_email_change_code(
                user, verification_code
            )

            if success:
                # Refresh user data from database
                user.refresh_from_db()

                return Response(
                    {
                        "success": True,
                        "detail": message,
                        "user": UserSerializer(user).data,
                    },
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {
                        "success": False,
                        "detail": message,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )


class ResendEmailChangeCodeView(APIView):
    """Resend email change verification code"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Resend the verification code for email change using Redis service.
        """
        user = request.user

        # Get email change data from Redis
        email_change_data = RedisOTPService.get_email_change_data(user.id)

        if not email_change_data:
            return Response(
                {
                    "success": False,
                    "detail": "No email change request found. Please start the process again.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        new_email = email_change_data.get("new_email")
        if not new_email:
            return Response(
                {
                    "success": False,
                    "detail": "Invalid email change request. Please start the process again.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resend verification code using Redis service
        success, message = RedisOTPService.send_email_change_verification(
            user, new_email, force=False
        )

        if success:
            return Response(
                {
                    "success": True,
                    "detail": message,
                },
                status=status.HTTP_200_OK,
            )
        else:
            return Response(
                {
                    "success": False,
                    "detail": message,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


# TWO-FACTOR AUTHENTICATION VIEWS


class Toggle2FAView(APIView):
    """Enable/disable two-factor authentication"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Enable or disable two-factor authentication for the authenticated user.
        For enabling: sends OTP and returns verification token
        For disabling: can be done directly
        """
        serializer = Toggle2FASerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            enable = serializer.validated_data["enable"]
            phone_number = serializer.validated_data.get("phone_number")

            # ENABLING 2FA - Only send OTP, don't enable yet
            if enable:
                # Check/update phone number
                if phone_number:
                    # Check if phone number is already used by another user
                    if (
                        User.objects.exclude(id=user.id)
                        .filter(phone_number=phone_number)
                        .exists()
                    ):
                        return Response(
                            {
                                "success": False,
                                "detail": "This phone number is already associated with another account.",
                            },
                            status=status.HTTP_400_BAD_REQUEST,
                        )
                    # Update phone number (but don't enable 2FA yet)
                    user.phone_number = phone_number
                    user.save()
                elif not user.phone_number:
                    return Response(
                        {
                            "success": False,
                            "detail": "Phone number is required to enable 2FA.",
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Mark this as 2FA setup process (not login)
                user.has_initiate_login = True  # Reuse this flag temporarily
                user.save()

                # Send OTP for 2FA setup
                success, message = RedisOTPService.send_sms_otp(user, force=True)

                if not success:
                    return Response(
                        {
                            "success": False,
                            "detail": message,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Create verification token for 2FA setup
                verification_token = signing.dumps(
                    {
                        "user_id": user.id,
                        "timestamp": timezone.now().isoformat(),
                        "action": "2fa_setup",  # Different action to identify setup vs login
                    },
                    salt="2fa-verification",
                )

                if settings.DEBUG:
                    print(f"DEBUG: Created 2FA setup token for user {user.id}")

                # Return response with verification token
                return Response(
                    {
                        "success": True,
                        "detail": "Verification code sent to your phone. Please verify to enable 2FA.",
                        "require_verification": True,
                        "verification_token": verification_token,
                        "phone_number": user.phone_number,
                    },
                    status=status.HTTP_200_OK,
                )

            # DISABLING 2FA
            else:
                # For disabling, allow direct disable
                user.is_2fa_enabled = False
                user.save()

                return Response(
                    {
                        "success": True,
                        "detail": "2FA has been disabled.",
                        "user": UserSerializer(user).data,
                    },
                    status=status.HTTP_200_OK,
                )

        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )


class VerifyOTPView(APIView):
    """Verify OTP for two-factor authentication (login or setup)"""

    permission_classes = [AllowAny]

    def post(self, request):
        """
        Verifies a one-time password (OTP) for:
        - Two-factor authentication during login
        - Two-factor authentication setup/enablement
        """
        verification_token = request.data.get("verification_token")
        otp = request.data.get("otp")

        # Debug logging
        if settings.DEBUG:
            print(f"DEBUG: Received verification_token: {verification_token}")
            print(f"DEBUG: Received OTP: {otp}")

        if not verification_token or not otp:
            return Response(
                {"success": False, "detail": "Missing verification token or OTP"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Verify and decode the signed token
            try:
                token_data = signing.loads(
                    verification_token,
                    salt="2fa-verification",
                    max_age=900,  # 15 minutes
                )

                if settings.DEBUG:
                    print(f"DEBUG: Successfully decoded token_data: {token_data}")

            except signing.SignatureExpired:
                if settings.DEBUG:
                    print("DEBUG: Token signature expired")
                return Response(
                    {
                        "success": False,
                        "detail": "Verification token has expired. Please request a new code.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )
            except signing.BadSignature as e:
                if settings.DEBUG:
                    print(f"DEBUG: Bad signature error: {str(e)}")
                return Response(
                    {
                        "success": False,
                        "detail": "Invalid verification token.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            user_id = token_data.get("user_id")
            action = token_data.get("action", "2fa_verification")  # Get action type

            if not user_id:
                if settings.DEBUG:
                    print("DEBUG: No user_id in token data")
                return Response(
                    {"success": False, "detail": "Invalid token data"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except Exception as e:
            if settings.DEBUG:
                print(f"DEBUG: Unexpected error during token verification: {str(e)}")
            return Response(
                {"success": False, "detail": "Token verification failed"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(id=user_id)

            if settings.DEBUG:
                print(f"DEBUG: Found user: {user.email}, action: {action}")

            # Verify the user has initiated the process
            if not user.has_initiate_login:
                return Response(
                    {
                        "success": False,
                        "detail": "Authentication required. Please start the process again.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except User.DoesNotExist:
            if settings.DEBUG:
                print(f"DEBUG: User with ID {user_id} not found")
            return Response(
                {"success": False, "detail": "User not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Verify OTP using Redis service
        if settings.DEBUG:
            print(f"DEBUG: Attempting to verify OTP: {otp} for user: {user.email}")

        otp_verification_result = RedisOTPService.verify_sms_otp(user, otp)

        if settings.DEBUG:
            print(f"DEBUG: OTP verification result: {otp_verification_result}")

        if otp_verification_result:
            # Check if this is 2FA setup or login
            if action == "2fa_setup":
                # This is 2FA SETUP - enable 2FA
                user.is_2fa_enabled = True
                user.has_initiate_login = False  # Reset the flag
                user.save()

                if settings.DEBUG:
                    print(f"DEBUG: 2FA enabled for user: {user.email}")

                return Response(
                    {
                        "success": True,
                        "detail": "2FA has been successfully enabled.",
                        "action": "2fa_setup",
                        "user": UserSerializer(user).data,
                    },
                    status=status.HTTP_200_OK,
                )
            else:
                # This is LOGIN with 2FA - generate tokens
                user.has_initiate_login = False  # Reset the flag
                user.save()

                tokens = RedisTokenStore.store_tokens(user)

                # Create response with access token
                response = Response(
                    {
                        "success": True,
                        "access_token": tokens["access_token"],
                        "action": "login",
                        "user": UserSerializer(user).data,
                    }
                )

                # Set refresh token as HttpOnly cookie
                response = set_refresh_token_cookie(response, tokens["refresh_token"])
                return response
        else:
            # Get remaining attempts
            attempts_left = RedisOTPService.get_sms_otp_attempts_left(user.id)

            if settings.DEBUG:
                print(f"DEBUG: OTP verification failed, attempts left: {attempts_left}")

            return Response(
                {
                    "success": False,
                    "detail": f"Invalid verification code. {attempts_left} attempts remaining.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


class ResendOTPView(APIView):
    """Resend OTP for two-factor authentication"""

    permission_classes = [AllowAny]

    def post(self, request):
        """
        Resends a verification code to the user's phone number for 2FA using Redis service.
        Uses signed token verification instead of session validation.
        """
        verification_token = request.data.get("verification_token")

        if not verification_token:
            return Response(
                {"success": False, "detail": "Missing verification token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            # Verify and decode the signed token
            token_data = signing.loads(
                verification_token, salt="2fa-verification", max_age=300  # 5 minutes
            )

            user_id = token_data["user_id"]

        except signing.BadSignature:
            return Response(
                {"success": False, "detail": "Invalid or expired verification token"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.get(id=user_id)

            action = token_data.get("action", "")
            is_setup_flow = action == "2fa_setup"

            # For login flow: require that the user has started the login process
            if not is_setup_flow and not user.has_initiate_login:
                return Response(
                    {
                        "success": False,
                        "detail": "Authentication required before requesting verification code. Please log in first.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # For login flow: 2FA must already be enabled
            if not is_setup_flow and not user.is_2fa_enabled:
                return Response(
                    {
                        "success": False,
                        "detail": "2FA is not enabled for this user.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Use Redis OTP service to resend
            success, message = RedisOTPService.send_sms_otp(user)

            if success:
                return Response(
                    {
                        "success": True,
                        "detail": "A new verification code has been sent to your phone.",
                    },
                    status=status.HTTP_200_OK,
                )
            else:
                return Response(
                    {
                        "success": False,
                        "detail": message,
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

        except User.DoesNotExist:
            return Response(
                {"success": False, "detail": "User not found."},
                status=status.HTTP_400_BAD_REQUEST,
            )


# PASSWORD MANAGEMENT VIEWS


class ChangePasswordView(APIView):
    """Change password for authenticated user"""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Change the authenticated user's password.
        Requires current password and new password confirmation.
        """
        serializer = ChangePasswordSerializer(data=request.data)
        if serializer.is_valid():
            user = request.user
            current_password = serializer.validated_data["current_password"]
            new_password = serializer.validated_data["new_password"]

            # Verify current password
            if not user.check_password(current_password):
                return Response(
                    {
                        "success": False,
                        "errors": {
                            "current_password": ["Current password is incorrect."]
                        },
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Validate new password
            try:
                validate_password(new_password, user)
            except ValidationError as e:
                return Response(
                    {"success": False, "errors": {"new_password": list(e.messages)}},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Set new password
            user.set_password(new_password)
            user.save()

            # Invalidate all existing tokens for security
            RedisTokenStore.invalidate_user_tokens(user.id)

            return Response(
                {
                    "success": True,
                    "detail": "Password changed successfully. Please log in again with your new password.",
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )


class ForgotPasswordView(APIView):
    """Send password reset email or SMS based on identifier type"""

    permission_classes = [AllowAny]

    def post(self, request):
        """
        Send a password reset email or SMS based on the identifier provided.
        If email is provided, sends email with reset link.
        If phone number is provided, sends SMS with OTP using Redis service.
        """
        serializer = ForgotPasswordSerializer(data=request.data)
        if serializer.is_valid():
            identifier = serializer.validated_data["identifier"]

            # Determine if identifier is email or phone
            user = None
            is_email = "@" in identifier

            try:
                if is_email:
                    user = User.objects.get(email=identifier)
                    return self._send_email_reset(user)
                else:
                    user = User.objects.get(phone_number=identifier)
                    return self._send_sms_reset(user)

            except User.DoesNotExist:
                # Return same message for security (don't reveal if email/phone exists)
                return Response(
                    {
                        "success": True,
                        "detail": "If an account exists with this information, you will receive password reset instructions.",
                        "reset_type": "email" if is_email else "sms",
                    },
                    status=status.HTTP_200_OK,
                )

        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )

    def _send_email_reset(self, user):
        """Send password reset email with link"""
        # Create or update password reset token
        token_obj, created = PasswordResetToken.objects.get_or_create(
            user=user,
            defaults={
                "token": secrets.token_urlsafe(32),
                "expires_at": timezone.now()
                + timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT),
            },
        )

        if not created:
            # Update existing token
            token_obj.token = secrets.token_urlsafe(32)
            token_obj.expires_at = timezone.now() + timedelta(
                seconds=settings.PASSWORD_RESET_TIMEOUT
            )
            token_obj.is_used = False
            token_obj.save()

        # Send password reset email
        reset_link = f"{settings.FRONTEND_URL}/reset-password?token={token_obj.token}"

        if not settings.DEBUG:
            # Email template context
            expires_hours = settings.PASSWORD_RESET_TIMEOUT // 3600
            context = {
                "user": user,
                "reset_link": reset_link,
                "site_name": settings.SITE_NAME,
                "expires_hours": expires_hours,
                "expires_time": (
                    f"{expires_hours} hour{'s' if expires_hours != 1 else ''}"
                    if expires_hours >= 1
                    else f"{settings.PASSWORD_RESET_TIMEOUT // 60} minutes"
                ),
            }

            subject = "Reset your password"
            html_message = render_to_string("users/emails/password_reset.html", context)
            plain_message = strip_tags(html_message)

            send_mail(
                subject,
                plain_message,
                settings.EMAIL_HOST_USER,
                [user.email],
                html_message=html_message,
                fail_silently=False,
            )
        else:
            print(f"Password reset link: {reset_link}")

        return Response(
            {
                "success": True,
                "detail": "If an account exists with this information, you will receive password reset instructions.",
                "reset_type": "email",
            },
            status=status.HTTP_200_OK,
        )

    def _send_sms_reset(self, user):
        """Send password reset OTP via SMS using Redis service"""
        # Use Redis OTP service to send password reset OTP
        success, message = RedisOTPService.send_password_reset_otp(user, force=True)

        if success:
            return Response(
                {
                    "success": True,
                    "detail": "If an account exists with this information, you will receive password reset instructions.",
                    "reset_type": "sms",
                },
                status=status.HTTP_200_OK,
            )
        else:
            return Response(
                {
                    "success": False,
                    "detail": message,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )


class ResetPasswordView(APIView):
    """Reset password using token (email) or OTP (SMS)"""

    permission_classes = [AllowAny]

    def post(self, request):
        """
        Reset password using either:
        - token (from email reset link)
        - otp + identifier (from SMS reset using Redis service)
        """
        serializer = ResetPasswordSerializer(data=request.data)
        if serializer.is_valid():
            new_password = serializer.validated_data["new_password"]
            token = serializer.validated_data.get("token")
            otp = serializer.validated_data.get("otp")
            identifier = serializer.validated_data.get("identifier")

            user = None

            # Email-based reset (using token)
            if token:
                try:
                    token_obj = PasswordResetToken.objects.get(
                        token=token, is_used=False, expires_at__gt=timezone.now()
                    )
                    user = token_obj.user

                    # Mark token as used after successful validation
                    token_obj.is_used = True
                    token_obj.save()

                except PasswordResetToken.DoesNotExist:
                    return Response(
                        {"success": False, "detail": "Invalid or expired reset token."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            # SMS-based reset (using OTP via Redis service)
            elif otp and identifier:
                try:
                    # Find user by identifier
                    if "@" in identifier:
                        user = User.objects.get(email=identifier)
                    else:
                        user = User.objects.get(phone_number=identifier)

                    # Verify OTP using Redis service
                    success, message = RedisOTPService.verify_password_reset_otp(
                        user, otp
                    )

                    if not success:
                        return Response(
                            {"success": False, "detail": message},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                except User.DoesNotExist:
                    return Response(
                        {"success": False, "detail": "Invalid reset request."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            else:
                return Response(
                    {
                        "success": False,
                        "detail": "Either token or (otp + identifier) must be provided.",
                    },
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Validate new password
            try:
                validate_password(new_password, user)
            except ValidationError as e:
                return Response(
                    {"success": False, "detail": list(e.messages)},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Set new password
            user.set_password(new_password)
            user.save()

            # Clear password reset OTP from Redis if it was SMS-based reset
            if otp and identifier:
                RedisOTPService.clear_password_reset_otp(user.id)

            # Invalidate all existing tokens for security
            RedisTokenStore.invalidate_user_tokens(user.id)

            return Response(
                {
                    "success": True,
                    "detail": "Password reset successfully. Please log in with your new password.",
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )


class ResendPasswordResetOTPView(APIView):
    """Resend password reset OTP for SMS-based reset"""

    permission_classes = [AllowAny]

    def post(self, request):
        """Resend password reset OTP to phone number using Redis service"""
        serializer = ResendPasswordResetOTPSerializer(data=request.data)
        if serializer.is_valid():
            identifier = serializer.validated_data["identifier"]

            try:
                # Find user by phone number
                user = User.objects.get(phone_number=identifier)

                # Resend OTP using Redis service
                success, message = RedisOTPService.send_password_reset_otp(
                    user, force=False
                )

                if success:
                    return Response(
                        {
                            "success": True,
                            "detail": "New verification code sent successfully.",
                        },
                        status=status.HTTP_200_OK,
                    )
                else:
                    return Response(
                        {
                            "success": False,
                            "detail": message,
                        },
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            except User.DoesNotExist:
                # Don't reveal if phone number exists
                return Response(
                    {
                        "success": True,
                        "detail": "If an account exists with this phone number, a new code has been sent.",
                    },
                    status=status.HTTP_200_OK,
                )

        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )


# PROFILE MANAGEMENT VIEWS


class UpdateProfileView(APIView):
    """Update user profile information"""

    permission_classes = [IsAuthenticated]

    def patch(self, request):
        """
        Update user profile fields like first_name, last_name.
        Only updates provided fields.
        """
        serializer = UpdateProfileSerializer(
            request.user, data=request.data, partial=True, context={"request": request}
        )

        if serializer.is_valid():
            serializer.save()
            return Response(
                {
                    "success": True,
                    "detail": "Profile updated successfully.",
                    "user": UserSerializer(request.user).data,
                },
                status=status.HTTP_200_OK,
            )

        return Response(
            {"success": False, "errors": serializer.errors},
            status=status.HTTP_400_BAD_REQUEST,
        )


class UserProfileView(APIView):
    """Get current user profile"""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        """
        Return the current user's profile information.
        """
        return Response(
            {"success": True, "user": UserSerializer(request.user).data},
            status=status.HTTP_200_OK,
        )
