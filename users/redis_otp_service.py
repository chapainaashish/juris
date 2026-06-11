# redis_otp_service.py - Redis-based OTP management service

import json
import random
import string
from datetime import timedelta
from typing import Dict, Optional, Tuple

from django.conf import settings
from django.core.cache import cache
from django.core.mail import send_mail
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.html import strip_tags
from django_redis import get_redis_connection
from twilio.rest import Client


class RedisOTPService:
    """
    Redis-based OTP service for handling various types of OTP operations:
    - 2FA SMS OTP
    - Email change verification
    - Password reset OTP
    """

    # Redis key prefixes
    SMS_OTP_PREFIX = "sms_otp"
    EMAIL_CHANGE_PREFIX = "email_change"
    PASSWORD_RESET_PREFIX = "password_reset"

    # Default settings
    DEFAULT_OTP_LENGTH = 6
    DEFAULT_VALIDITY_MINUTES = 15
    DEFAULT_COOLDOWN_SECONDS = 60
    DEFAULT_MAX_ATTEMPTS = 5
    DEFAULT_LOCKOUT_MINUTES = 30

    @staticmethod
    def _get_redis_client():
        """Get Redis client instance"""
        try:
            return get_redis_connection("default")
        except Exception:
            return None

    @staticmethod
    def _generate_otp(length: int = DEFAULT_OTP_LENGTH) -> str:
        """Generate a numeric OTP of specified length"""
        return "".join(random.choices(string.digits, k=length))

    @staticmethod
    def _get_key(prefix: str, user_id: int, suffix: str = "") -> str:
        """Generate Redis key for OTP data"""
        key = f"{prefix}:{user_id}"
        if suffix:
            key += f":{suffix}"
        return key

    @classmethod
    def _store_otp_data(
        cls,
        user_id: int,
        prefix: str,
        otp: str,
        validity_minutes: int = DEFAULT_VALIDITY_MINUTES,
        additional_data: Optional[Dict] = None,
    ) -> bool:
        """Store OTP data in Redis with expiration"""
        try:
            redis_client = cls._get_redis_client()
            if not redis_client:
                return False

            now = timezone.now()
            expires_at = now + timedelta(minutes=validity_minutes)

            otp_data = {
                "otp": otp,
                "created_at": now.isoformat(),
                "expires_at": expires_at.isoformat(),
                "attempt_count": 0,
                "last_sent": now.isoformat(),
                **(additional_data or {}),
            }

            key = cls._get_key(prefix, user_id)

            # Store with TTL (add extra 5 minutes buffer for cleanup)
            ttl_seconds = (validity_minutes + 5) * 60
            redis_client.setex(key, ttl_seconds, json.dumps(otp_data))

            return True
        except Exception as e:
            print(f"Error storing OTP data: {str(e)}")
            return False

    @classmethod
    def _get_otp_data(cls, user_id: int, prefix: str) -> Optional[Dict]:
        """Retrieve OTP data from Redis - FIXED VERSION"""
        try:
            redis_client = cls._get_redis_client()
            if not redis_client:
                return None

            key = cls._get_key(prefix, user_id)
            if settings.DEBUG:
                print(f"DEBUG: Getting OTP data with key: {key}")

            data = redis_client.get(key)

            if not data:
                if settings.DEBUG:
                    print("DEBUG: No data found in Redis")
                return None

            # Handle bytes
            if isinstance(data, bytes):
                data = data.decode("utf-8")

            # Parse JSON
            parsed_data = json.loads(data)

            if settings.DEBUG:
                print(f"DEBUG: Retrieved and parsed OTP data: {parsed_data}")

            return parsed_data

        except Exception as e:
            if settings.DEBUG:
                print(f"DEBUG: Error retrieving OTP data: {str(e)}")
            return None

    @classmethod
    def _delete_otp_data(cls, user_id: int, prefix: str) -> bool:
        """Delete OTP data from Redis - FIXED VERSION"""
        try:
            redis_client = cls._get_redis_client()
            if not redis_client:
                return False

            key = cls._get_key(prefix, user_id)
            result = redis_client.delete(key)

            if settings.DEBUG:
                print(f"DEBUG: Deleted OTP data with key {key}, result: {result}")

            return bool(result)
        except Exception as e:
            if settings.DEBUG:
                print(f"DEBUG: Error deleting OTP data: {str(e)}")
            return False

    @classmethod
    def _is_otp_valid(cls, otp_data: Dict) -> bool:
        """Check if OTP data is still valid (not expired)"""
        if not otp_data:
            return False

        try:
            expires_at = timezone.datetime.fromisoformat(otp_data["expires_at"])
            return expires_at > timezone.now()
        except (KeyError, ValueError):
            return False

    @classmethod
    def _can_resend_otp(
        cls, otp_data: Dict, cooldown_seconds: int = DEFAULT_COOLDOWN_SECONDS
    ) -> bool:
        """Check if OTP can be resent (cooldown check)"""
        if not otp_data or not otp_data.get("last_sent"):
            return True

        try:
            last_sent = timezone.datetime.fromisoformat(otp_data["last_sent"])
            time_elapsed = timezone.now() - last_sent
            return time_elapsed.total_seconds() >= cooldown_seconds
        except (KeyError, ValueError):
            return True

    @classmethod
    def _increment_attempt(cls, user_id: int, prefix: str) -> bool:
        """Increment OTP attempt counter - FIXED VERSION"""
        if settings.DEBUG:
            print(
                f"DEBUG: _increment_attempt called for user {user_id}, prefix {prefix}"
            )

        try:
            # Get Redis client directly for more control
            redis_client = cls._get_redis_client()
            if not redis_client:
                if settings.DEBUG:
                    print("DEBUG: No Redis client available")
                return False

            key = cls._get_key(prefix, user_id)
            if settings.DEBUG:
                print(f"DEBUG: Redis key: {key}")

            # Get current data
            current_data = redis_client.get(key)
            if not current_data:
                if settings.DEBUG:
                    print("DEBUG: No current data found in Redis")
                return False

            # Parse JSON data
            try:
                if isinstance(current_data, bytes):
                    current_data = current_data.decode("utf-8")
                otp_data = json.loads(current_data)
                if settings.DEBUG:
                    print(f"DEBUG: Current OTP data: {otp_data}")
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                if settings.DEBUG:
                    print(f"DEBUG: Error parsing current data: {e}")
                return False

            # Increment attempt count
            otp_data["attempt_count"] = otp_data.get("attempt_count", 0) + 1

            if settings.DEBUG:
                print(
                    f"DEBUG: Incremented attempt count to: {otp_data['attempt_count']}"
                )

            # Calculate remaining TTL
            try:
                expires_at = timezone.datetime.fromisoformat(otp_data["expires_at"])
                remaining_seconds = int((expires_at - timezone.now()).total_seconds())

                if settings.DEBUG:
                    print(f"DEBUG: Remaining seconds: {remaining_seconds}")

                # Only update if there's still time left
                if remaining_seconds > 0:
                    # Store updated data with remaining TTL
                    redis_client.setex(key, remaining_seconds, json.dumps(otp_data))

                    if settings.DEBUG:
                        print(
                            "DEBUG: Successfully updated Redis with new attempt count"
                        )
                        # Verify the update
                        verify_data = redis_client.get(key)
                        if verify_data:
                            verify_parsed = json.loads(
                                verify_data.decode("utf-8")
                                if isinstance(verify_data, bytes)
                                else verify_data
                            )
                            print(
                                f"DEBUG: Verified new attempt count: {verify_parsed.get('attempt_count')}"
                            )

                    return True
                else:
                    if settings.DEBUG:
                        print("DEBUG: OTP expired, deleting data")
                    # OTP expired, delete it
                    redis_client.delete(key)
                    return False
            except (KeyError, ValueError) as e:
                if settings.DEBUG:
                    print(f"DEBUG: Error calculating expiry: {e}")
                return False

        except Exception as e:
            if settings.DEBUG:
                print(f"DEBUG: Error incrementing attempt: {str(e)}")
            return False

    # 2FA SMS OTP METHODS
    @classmethod
    def get_lockout_info(cls, user_id: int) -> Dict:
        """Get lockout information for a user"""
        otp_data = cls._get_otp_data(user_id, cls.SMS_OTP_PREFIX)

        if not otp_data:
            return {
                "is_locked": False,
                "attempts_left": cls.DEFAULT_MAX_ATTEMPTS,
                "lockout_expires_at": None,
                "lockout_expires_in_minutes": 0,
            }

        # Check if OTP is expired
        if not cls._is_otp_valid(otp_data):
            cls._delete_otp_data(user_id, cls.SMS_OTP_PREFIX)
            return {
                "is_locked": False,
                "attempts_left": cls.DEFAULT_MAX_ATTEMPTS,
                "lockout_expires_at": None,
                "lockout_expires_in_minutes": 0,
            }

        current_attempts = otp_data.get("attempt_count", 0)
        attempts_left = max(0, cls.DEFAULT_MAX_ATTEMPTS - current_attempts)
        is_locked = current_attempts >= cls.DEFAULT_MAX_ATTEMPTS

        lockout_expires_at = None
        lockout_expires_in_minutes = 0

        if is_locked:
            try:
                expires_at = timezone.datetime.fromisoformat(otp_data["expires_at"])
                lockout_expires_at = expires_at.isoformat()
                lockout_expires_in_minutes = max(
                    0, int((expires_at - timezone.now()).total_seconds() / 60)
                )
            except (KeyError, ValueError):
                pass

        return {
            "is_locked": is_locked,
            "attempts_left": attempts_left,
            "lockout_expires_at": lockout_expires_at,
            "lockout_expires_in_minutes": lockout_expires_in_minutes,
        }

    @classmethod
    def send_sms_otp(cls, user, force: bool = False) -> Tuple[bool, str]:
        """Send SMS OTP for 2FA authentication - WITH LOCKOUT HANDLING"""
        # Check if user has initiated login
        if not user.has_initiate_login:
            return False, "Authentication required before requesting OTP."

        # Check existing OTP data
        otp_data = cls._get_otp_data(user.id, cls.SMS_OTP_PREFIX)

        if otp_data and not force:
            # Check if user is locked out
            current_attempts = otp_data.get("attempt_count", 0)
            if current_attempts >= cls.DEFAULT_MAX_ATTEMPTS:
                if cls._is_otp_valid(otp_data):
                    try:
                        expires_at = timezone.datetime.fromisoformat(
                            otp_data["expires_at"]
                        )
                        remaining_minutes = int(
                            (expires_at - timezone.now()).total_seconds() / 60
                        )
                        return (
                            False,
                            f"Too many failed attempts. Your account is temporarily locked. Try again in {remaining_minutes} minutes.",
                        )
                    except (KeyError, ValueError):
                        pass
                else:
                    # OTP expired, allow new attempt
                    cls._delete_otp_data(user.id, cls.SMS_OTP_PREFIX)
                    otp_data = None

            # Check cooldown for resend
            if otp_data and not cls._can_resend_otp(otp_data):
                try:
                    last_sent = timezone.datetime.fromisoformat(otp_data["last_sent"])
                    remaining = int(
                        cls.DEFAULT_COOLDOWN_SECONDS
                        - (timezone.now() - last_sent).total_seconds()
                    )
                    return (
                        False,
                        f"Please wait {remaining} seconds before requesting another verification code.",
                    )
                except (KeyError, ValueError):
                    pass

        # Check if user has phone number
        if not user.phone_number:
            return (
                False,
                "No phone number associated with this account. Please add a phone number to use 2FA.",
            )

        # Clear any existing OTP data before creating new one
        if force or not otp_data:
            cls._delete_otp_data(user.id, cls.SMS_OTP_PREFIX)

        # Generate new OTP
        otp = cls._generate_otp()

        # Store OTP data
        success = cls._store_otp_data(
            user.id,
            cls.SMS_OTP_PREFIX,
            otp,
            validity_minutes=settings.OTP_VALIDITY_MINUTES,
        )

        if not success:
            return False, "Error storing verification code. Please try again later."

        # Send SMS
        message = f"Your verification code is: {otp}. This code will expire in {settings.OTP_VALIDITY_MINUTES} minutes."

        try:
            if settings.DEBUG:
                print(f"SMS to {user.phone_number}: {message}")
            else:
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                client.messages.create(
                    body=message,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=user.phone_number,
                )

            return True, "Verification code sent successfully"
        except Exception as e:
            print(f"Error sending SMS: {str(e)}")
            # Clean up stored OTP if SMS failed
            cls._delete_otp_data(user.id, cls.SMS_OTP_PREFIX)
            return False, "Error sending verification code. Please try again later."

    @classmethod
    def verify_sms_otp(cls, user, otp: str) -> bool:
        """Verify SMS OTP for 2FA authentication - WITH LOCKOUT HANDLING"""
        if settings.DEBUG:
            print(f"DEBUG: verify_sms_otp called for user {user.id} with OTP: {otp}")

        # Check if user has initiated login
        if not user.has_initiate_login:
            if settings.DEBUG:
                print("DEBUG: User has not initiated login")
            return False

        otp_data = cls._get_otp_data(user.id, cls.SMS_OTP_PREFIX)

        if settings.DEBUG:
            print(f"DEBUG: Retrieved OTP data: {otp_data}")

        if not otp_data:
            if settings.DEBUG:
                print("DEBUG: No OTP data found")
            return False

        # Check if OTP is expired
        if not cls._is_otp_valid(otp_data):
            if settings.DEBUG:
                print("DEBUG: OTP has expired, deleting data")
            cls._delete_otp_data(user.id, cls.SMS_OTP_PREFIX)
            return False

        # Check attempt limits BEFORE verifying
        current_attempts = otp_data.get("attempt_count", 0)
        if settings.DEBUG:
            print(
                f"DEBUG: Current attempts: {current_attempts}, Max: {cls.DEFAULT_MAX_ATTEMPTS}"
            )

        if current_attempts >= cls.DEFAULT_MAX_ATTEMPTS:
            if settings.DEBUG:
                print("DEBUG: Max attempts exceeded - user is locked out")
            return False

        # Get stored OTP and compare
        stored_otp = otp_data.get("otp")
        if settings.DEBUG:
            print(f"DEBUG: Stored OTP: '{stored_otp}', Provided OTP: '{otp}'")
            print(
                f"DEBUG: OTP types - Stored: {type(stored_otp)}, Provided: {type(otp)}"
            )
            print(f"DEBUG: OTP match: {stored_otp == otp}")

        # Verify OTP (ensure both are strings and strip whitespace)
        if str(stored_otp).strip() == str(otp).strip():
            if settings.DEBUG:
                print("DEBUG: OTP verification successful, cleaning up")

            # Success - clean up
            cls._delete_otp_data(user.id, cls.SMS_OTP_PREFIX)

            # Reset user login state
            user.has_initiate_login = False
            user.save()

            if settings.DEBUG:
                print("DEBUG: User login state reset")

            return True
        else:
            if settings.DEBUG:
                print("DEBUG: OTP verification failed, incrementing attempts")

            # FAILED - Increment attempt counter
            success = cls._increment_attempt(user.id, cls.SMS_OTP_PREFIX)

            if settings.DEBUG:
                print(f"DEBUG: Attempt increment success: {success}")
                # Check updated data
                updated_data = cls._get_otp_data(user.id, cls.SMS_OTP_PREFIX)
                if updated_data:
                    new_attempt_count = updated_data.get("attempt_count", 0)
                    print(f"DEBUG: New attempt count: {new_attempt_count}")

                    # If this was the last attempt, mark as locked
                    if new_attempt_count >= cls.DEFAULT_MAX_ATTEMPTS:
                        print("DEBUG: User is now locked out after this failed attempt")
                else:
                    print("DEBUG: No OTP data found after increment attempt")

            return False

    @classmethod
    def get_sms_otp_attempts_left(cls, user_id: int) -> int:
        """Get remaining SMS OTP attempts - FIXED VERSION"""
        if settings.DEBUG:
            print(f"DEBUG: get_sms_otp_attempts_left called for user {user_id}")

        otp_data = cls._get_otp_data(user_id, cls.SMS_OTP_PREFIX)

        if settings.DEBUG:
            print(f"DEBUG: OTP data for attempts calculation: {otp_data}")

        if not otp_data:
            if settings.DEBUG:
                print(
                    f"DEBUG: No OTP data, returning max attempts: {cls.DEFAULT_MAX_ATTEMPTS}"
                )
            return cls.DEFAULT_MAX_ATTEMPTS

        # Check if OTP is still valid
        if not cls._is_otp_valid(otp_data):
            if settings.DEBUG:
                print("DEBUG: OTP expired, deleting and returning max attempts")
            cls._delete_otp_data(user_id, cls.SMS_OTP_PREFIX)
            return cls.DEFAULT_MAX_ATTEMPTS

        current_attempts = otp_data.get("attempt_count", 0)
        remaining = max(0, cls.DEFAULT_MAX_ATTEMPTS - current_attempts)

        if settings.DEBUG:
            print(
                f"DEBUG: Current attempts: {current_attempts}, Remaining: {remaining}"
            )

        return remaining

    # EMAIL CHANGE VERIFICATION METHODS

    @classmethod
    def send_email_change_verification(
        cls, user, new_email: str, force: bool = False
    ) -> Tuple[bool, str]:
        """Send email change verification code"""
        # Check existing verification data
        otp_data = cls._get_otp_data(user.id, cls.EMAIL_CHANGE_PREFIX)

        if otp_data and not force:
            # Check if user is locked out
            if otp_data.get("attempt_count", 0) >= cls.DEFAULT_MAX_ATTEMPTS:
                if cls._is_otp_valid(otp_data):
                    return False, "Too many failed attempts. Please try again later."
                else:
                    # Expired, allow new attempt
                    cls._delete_otp_data(user.id, cls.EMAIL_CHANGE_PREFIX)
                    otp_data = None

            # Check cooldown
            if otp_data and not cls._can_resend_otp(otp_data):
                try:
                    last_sent = timezone.datetime.fromisoformat(otp_data["last_sent"])
                    remaining = int(
                        cls.DEFAULT_COOLDOWN_SECONDS
                        - (timezone.now() - last_sent).total_seconds()
                    )
                    return (
                        False,
                        f"Please wait {remaining} seconds before requesting another verification code.",
                    )
                except (KeyError, ValueError):
                    pass

        # Generate verification code
        verification_code = cls._generate_otp()

        # Store verification data
        additional_data = {"new_email": new_email}
        success = cls._store_otp_data(
            user.id,
            cls.EMAIL_CHANGE_PREFIX,
            verification_code,
            validity_minutes=15,  # Email change codes expire in 15 minutes
            additional_data=additional_data,
        )

        if not success:
            return False, "Error storing verification code. Please try again later."

        # Send email
        subject = "Verify Your New Email Address"
        message = f"""
    Hello {user.first_name or user.email},

    You have requested to change your email address. Please use the verification code below:

    Verification Code: {verification_code}

    This code will expire in 15 minutes.

    If you did not request this change, please ignore this email or contact support.

    Best regards,
    Juris
        """.strip()

        try:
            if settings.DEBUG:
                print(
                    f"Email change verification code for {new_email}: {verification_code}"
                )
            else:
                # FIX: Use DEFAULT_FROM_EMAIL instead of EMAIL_HOST_USER
                send_mail(
                    subject,
                    message,
                    settings.DEFAULT_FROM_EMAIL,  # CHANGED THIS LINE
                    [new_email],
                    fail_silently=False,
                )

            return True, "Verification code sent to your new email address."
        except Exception as e:
            print(f"Error sending email verification: {str(e)}")
            # Clean up stored code if email failed
            cls._delete_otp_data(user.id, cls.EMAIL_CHANGE_PREFIX)
            return False, "Error sending verification code. Please try again later."

    @classmethod
    def verify_email_change_code(cls, user, code: str) -> Tuple[bool, str]:
        """Verify email change verification code"""
        otp_data = cls._get_otp_data(user.id, cls.EMAIL_CHANGE_PREFIX)

        if not otp_data:
            return (
                False,
                "No email change request found. Please start the process again.",
            )

        # Check if code is expired
        if not cls._is_otp_valid(otp_data):
            cls._delete_otp_data(user.id, cls.EMAIL_CHANGE_PREFIX)
            return False, "Verification code has expired. Please request a new one."

        # Check attempt limits
        if otp_data.get("attempt_count", 0) >= cls.DEFAULT_MAX_ATTEMPTS:
            return False, "Too many failed attempts. Please try again later."

        # Verify code
        if otp_data.get("otp") == code:
            # Success - update user email
            new_email = otp_data.get("new_email")
            if new_email:
                user.email = new_email
                user.username = new_email
                user.save()

            # Clean up
            cls._delete_otp_data(user.id, cls.EMAIL_CHANGE_PREFIX)

            return True, "Email address successfully changed."
        else:
            # Increment attempt counter
            cls._increment_attempt(user.id, cls.EMAIL_CHANGE_PREFIX)

            attempts_left = (
                cls.DEFAULT_MAX_ATTEMPTS - otp_data.get("attempt_count", 0) - 1
            )
            if attempts_left > 0:
                return (
                    False,
                    f"Invalid verification code. You have {attempts_left} attempts remaining.",
                )
            else:
                return False, "Invalid verification code. Too many failed attempts."

    @classmethod
    def get_email_change_data(cls, user_id: int) -> Optional[Dict]:
        """Get email change request data"""
        return cls._get_otp_data(user_id, cls.EMAIL_CHANGE_PREFIX)

    # PASSWORD RESET OTP METHODS

    @classmethod
    def send_password_reset_otp(cls, user, force: bool = False) -> Tuple[bool, str]:
        """Send password reset OTP via SMS"""
        # Check existing OTP data
        otp_data = cls._get_otp_data(user.id, cls.PASSWORD_RESET_PREFIX)

        if otp_data and not force:
            # Check cooldown
            if not cls._can_resend_otp(otp_data):
                try:
                    last_sent = timezone.datetime.fromisoformat(otp_data["last_sent"])
                    remaining = int(
                        cls.DEFAULT_COOLDOWN_SECONDS
                        - (timezone.now() - last_sent).total_seconds()
                    )
                    return (
                        False,
                        f"Please wait {remaining} seconds before requesting another code.",
                    )
                except (KeyError, ValueError):
                    pass

        # Generate OTP
        otp = cls._generate_otp()

        # Store OTP data
        success = cls._store_otp_data(
            user.id,
            cls.PASSWORD_RESET_PREFIX,
            otp,
            validity_minutes=settings.OTP_VALIDITY_MINUTES,
        )

        if not success:
            return False, "Error storing verification code. Please try again later."

        # Send SMS
        message = f"Your password reset code is: {otp}. This code will expire in {settings.OTP_VALIDITY_MINUTES} minutes."

        try:
            if settings.DEBUG:
                print(f"SMS to {user.phone_number}: {message}")
            else:
                client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
                client.messages.create(
                    body=message,
                    from_=settings.TWILIO_PHONE_NUMBER,
                    to=user.phone_number,
                )

            return True, "Password reset code sent successfully."
        except Exception as e:
            print(f"Error sending SMS: {str(e)}")
            # Clean up stored OTP if SMS failed
            cls._delete_otp_data(user.id, cls.PASSWORD_RESET_PREFIX)
            return False, "Error sending verification code. Please try again later."

    @classmethod
    def verify_password_reset_otp(cls, user, otp: str) -> Tuple[bool, str]:
        """Verify password reset OTP"""
        otp_data = cls._get_otp_data(user.id, cls.PASSWORD_RESET_PREFIX)

        if not otp_data:
            return (
                False,
                "No password reset request found. Please start the process again.",
            )

        # Check if OTP is expired
        if not cls._is_otp_valid(otp_data):
            cls._delete_otp_data(user.id, cls.PASSWORD_RESET_PREFIX)
            return False, "Verification code has expired. Please request a new one."

        # Check attempt limits
        if otp_data.get("attempt_count", 0) >= cls.DEFAULT_MAX_ATTEMPTS:
            return False, "Too many failed attempts. Please request a new code."

        # Verify OTP
        if otp_data.get("otp") == otp:
            # Don't delete yet - will be deleted after password is successfully reset
            return True, "OTP verified successfully."
        else:
            # Increment attempt counter
            cls._increment_attempt(user.id, cls.PASSWORD_RESET_PREFIX)

            attempts_left = (
                cls.DEFAULT_MAX_ATTEMPTS - otp_data.get("attempt_count", 0) - 1
            )
            return False, f"Invalid OTP. {attempts_left} attempts remaining."

    @classmethod
    def clear_password_reset_otp(cls, user_id: int) -> bool:
        """Clear password reset OTP after successful password reset"""
        return cls._delete_otp_data(user_id, cls.PASSWORD_RESET_PREFIX)

    # UTILITY METHODS

    @classmethod
    def cleanup_expired_otps(cls):
        """Cleanup expired OTP data - can be called by a periodic task"""
        try:
            redis_client = cls._get_redis_client()
            if not redis_client:
                return

            # Redis automatically handles TTL expiration, but we can implement
            # custom cleanup logic here if needed

            prefixes = [
                cls.SMS_OTP_PREFIX,
                cls.EMAIL_CHANGE_PREFIX,
                cls.PASSWORD_RESET_PREFIX,
            ]

            for prefix in prefixes:
                pattern = f"{prefix}:*"
                keys = redis_client.keys(pattern)

                for key in keys:
                    try:
                        data = redis_client.get(key)
                        if data:
                            otp_data = json.loads(data)
                            if not cls._is_otp_valid(otp_data):
                                redis_client.delete(key)
                    except (json.JSONDecodeError, KeyError):
                        # Invalid data, delete key
                        redis_client.delete(key)

        except Exception as e:
            print(f"Error during OTP cleanup: {str(e)}")

    @classmethod
    def get_user_otp_status(cls, user_id: int) -> Dict:
        """Get comprehensive OTP status for a user"""
        status = {}

        # SMS OTP status
        sms_data = cls._get_otp_data(user_id, cls.SMS_OTP_PREFIX)
        status["sms_otp"] = {
            "active": bool(sms_data and cls._is_otp_valid(sms_data)),
            "attempts_left": (
                cls.get_sms_otp_attempts_left(user_id)
                if sms_data
                else cls.DEFAULT_MAX_ATTEMPTS
            ),
            "expires_at": sms_data.get("expires_at") if sms_data else None,
        }

        # Email change status
        email_data = cls._get_otp_data(user_id, cls.EMAIL_CHANGE_PREFIX)
        status["email_change"] = {
            "active": bool(email_data and cls._is_otp_valid(email_data)),
            "new_email": email_data.get("new_email") if email_data else None,
            "expires_at": email_data.get("expires_at") if email_data else None,
        }

        # Password reset status
        reset_data = cls._get_otp_data(user_id, cls.PASSWORD_RESET_PREFIX)
        status["password_reset"] = {
            "active": bool(reset_data and cls._is_otp_valid(reset_data)),
            "expires_at": reset_data.get("expires_at") if reset_data else None,
        }

        return status
