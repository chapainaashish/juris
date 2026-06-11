import json

from django.conf import settings
from django.core.cache import cache
from django_redis import get_redis_connection
from rest_framework_simplejwt.tokens import RefreshToken


class RedisTokenStore:
    """
    A Redis-based token store for JWT tokens for improved performance.
    This avoids database queries for token verification and blacklisting.
    """

    @staticmethod
    def store_tokens(user, refresh_token=None):
        """
        Store user tokens in Redis atomically using pipeline
        :param user: User object
        :param refresh_token: Optional refresh token object, will create new if not provided
        :return: Dictionary with access and refresh token strings
        """
        if refresh_token is None:
            refresh_token = RefreshToken.for_user(user)

        access_token = str(refresh_token.access_token)
        refresh_token_str = str(refresh_token)

        # Store user tokens with user ID as part of the key
        user_key = f"user_tokens:{user.id}"

        # Store token data with expiry matching the token lifetime
        token_data = {
            "access_token": access_token,
            "refresh_token": refresh_token_str,
            "user_id": user.id,
        }

        # Calculate the token expiry time based on settings
        access_expiry = int(
            settings.SIMPLE_JWT["ACCESS_TOKEN_LIFETIME"].total_seconds()
        )
        refresh_expiry = int(
            settings.SIMPLE_JWT["REFRESH_TOKEN_LIFETIME"].total_seconds()
        )

        # Get old token data to clean up
        old_token_data = cache.get(user_key)
        if old_token_data:
            try:
                if isinstance(old_token_data, str):
                    old_token_data = json.loads(old_token_data)

                # Clean up old tokens
                if old_token_data.get("access_token"):
                    cache.delete(f"access_token:{old_token_data['access_token']}")
                if old_token_data.get("refresh_token"):
                    cache.delete(f"refresh_token:{old_token_data['refresh_token']}")
            except:
                pass

        # Store new tokens
        cache.set(f"access_token:{access_token}", str(user.id), access_expiry)
        cache.set(f"refresh_token:{refresh_token_str}", str(user.id), refresh_expiry)
        cache.set(user_key, json.dumps(token_data), refresh_expiry)

        return {"access_token": access_token, "refresh_token": refresh_token_str}

    @staticmethod
    def validate_token(token, token_type="access"):
        """
        Validate if a token exists and is not blacklisted
        :param token: Token string
        :param token_type: Type of token ('access' or 'refresh')
        :return: User ID if valid, None otherwise
        """
        key = f"{token_type}_token:{token}"
        user_id = cache.get(key)
        return user_id if user_id else None

    @classmethod
    def invalidate_user_tokens(cls, user_id):
        """
        Invalidate all tokens for a user (logout from all devices)
        :param user_id: User ID
        """
        user_key = f"user_tokens:{user_id}"
        token_data = cache.get(user_key)

        if token_data:
            try:
                if isinstance(token_data, str):
                    token_data = json.loads(token_data)

                if token_data.get("access_token"):
                    cache.delete(f"access_token:{token_data['access_token']}")
                if token_data.get("refresh_token"):
                    cache.delete(f"refresh_token:{token_data['refresh_token']}")
            except:
                pass

            cache.delete(user_key)

    @classmethod
    def blacklist_token(cls, token, token_type="refresh"):
        """
        Blacklist a token by removing it from Redis
        :param token: Token string
        :param token_type: Type of token ('access' or 'refresh')
        """
        if token_type == "access":
            key = f"access_token:{token}"
            cache.delete(key)
        elif token_type == "refresh":
            refresh_key = f"refresh_token:{token}"
            user_id = cache.get(refresh_key)

            if user_id:
                cache.delete(refresh_key)
                user_key = f"user_tokens:{user_id}"
                token_data = cache.get(user_key)

                if token_data:
                    try:
                        if isinstance(token_data, str):
                            token_data = json.loads(token_data)

                        if token_data and token_data.get("refresh_token") == token:
                            access_token = token_data.get("access_token")
                            if access_token:
                                cache.delete(f"access_token:{access_token}")
                            cache.delete(user_key)
                    except:
                        pass
