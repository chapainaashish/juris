from django.utils import timezone

from .models import ProfileCompletionSession, VendorProfile


def cleanup_expired_sessions():
    """Clean up expired profile completion sessions"""
    expired_sessions = ProfileCompletionSession.objects.filter(
        is_completed=False, expires_at__lt=timezone.now()
    )

    count = expired_sessions.count()
    if count > 0:
        print(f"Cleaning up {count} expired profile completion sessions")

        for session in expired_sessions:
            if session.address:
                if not VendorProfile.objects.filter(address=session.address).exists():
                    session.address.delete()

    expired_sessions.delete()
