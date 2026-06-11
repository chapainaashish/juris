from django.contrib import admin

from .models import Availability, Unavailability


@admin.register(Availability)
class AvailabilityAdmin(admin.ModelAdmin):
    list_display = ("lawyer", "day_of_week", "start_time", "end_time", "offering", "is_active")
    list_filter = ("day_of_week", "is_active", "lawyer")
    search_fields = ("lawyer__vendor_profile__business_name",)
    ordering = ("lawyer", "day_of_week", "start_time")


@admin.register(Unavailability)
class UnavailabilityAdmin(admin.ModelAdmin):
    list_display = ("lawyer", "date", "start_time", "end_time", "is_all_day", "unavailability_type")
    list_filter = ("unavailability_type", "is_all_day", "date")
    search_fields = ("lawyer__vendor_profile__business_name",)
    ordering = ("date", "start_time")
