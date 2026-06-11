from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Load initial data for profiles app"

    def handle(self, *args, **options):
        self.stdout.write("Loading initial categories...")
        call_command("loaddata", "categories")

        self.stdout.write("Loading initial languages...")
        call_command("loaddata", "languages")

        self.stdout.write(self.style.SUCCESS("Successfully loaded all initial data"))
