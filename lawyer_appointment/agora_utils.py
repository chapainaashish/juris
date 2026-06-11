import hashlib
import time

from agora_token_builder import RtcTokenBuilder
from django.conf import settings


class AgoraTokenGenerator:
    """Utility class for generating Agora RTC tokens"""

    ROLE_MAP = {
        "publisher": 1,  # Host (can publish audio/video)
        "subscriber": 2,  # Audience (can only receive)
    }

    @staticmethod
    def generate_rtc_token(channel_name, uid, role="publisher", expire_time_hours=24):
        """
        Generate Agora RTC token for video/audio calls

        Args:
            channel_name (str): Channel name for the session
            uid (int): User ID (integer)
            role (str): 'publisher' or 'subscriber' (default: 'publisher')
            expire_time_hours (int): Token expiration time in hours

        Returns:
            tuple: (token, expiration_timestamp)
        """
        app_id = settings.AGORA_APP_ID
        app_certificate = settings.AGORA_APP_CERTIFICATE

        if not app_id or not app_certificate:
            raise ValueError("Agora App ID and Certificate must be set in settings.")

        # Convert role to Agora SDK role
        sdk_role = AgoraTokenGenerator.ROLE_MAP.get(role, 1)

        # Expiration
        current_timestamp = int(time.time())
        expire_timestamp = current_timestamp + (expire_time_hours * 3600)

        # Build token
        token = RtcTokenBuilder.buildTokenWithUid(
            app_id,
            app_certificate,
            channel_name,
            uid,
            sdk_role,
            expire_timestamp,
        )

        return token, expire_timestamp

    @staticmethod
    def generate_uid_for_user(user_id):
        """
        Generate a consistent Agora UID for a user
        Args:
            user_id: any unique identifier (int, UUID, etc.)
        Returns:
            int: Agora-compatible UID
        """
        user_str = str(user_id)
        hash_object = hashlib.md5(user_str.encode())
        uid = int(hash_object.hexdigest()[:8], 16)
        # Making UID is within Agora's acceptable range (1 to 2^32-1)
        uid = (uid % (2**31 - 1)) + 1
        return uid
