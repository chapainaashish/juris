from django.core.management.base import BaseCommand

from profiles.signals import cleanup_expired_sessions


class Command(BaseCommand):
    help = "Clean up expired profile completion sessions"

    def handle(self, *args, **options):
        self.stdout.write("Starting session cleanup...")
        cleanup_expired_sessions()
        self.stdout.write(
            self.style.SUCCESS("Successfully cleaned up expired sessions")
        )
