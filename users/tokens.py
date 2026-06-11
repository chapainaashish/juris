import six
from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    def _make_hash_value(self, user, timestamp):
        """
        Include email_verification_valid_until in the token hash to invalidate
        the token if the expiration changes
        """
        expiry_timestamp = ""
        if user.email_verification_valid_until:
            expiry_timestamp = user.email_verification_valid_until.timestamp()

        return (
            six.text_type(user.pk)
            + six.text_type(timestamp)
            + six.text_type(user.is_email_verified)
            + six.text_type(expiry_timestamp)
        )


email_verification_token = EmailVerificationTokenGenerator()
