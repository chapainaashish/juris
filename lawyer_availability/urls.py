from django.urls import path

from . import views

urlpatterns = [
    # Availability CRUD operations
    path(
        "availability/",
        views.AvailabilityListCreateView.as_view(),
        name="availability-list-create",
    ),
    path(
        "availability/<uuid:pk>/",
        views.AvailabilityDetailView.as_view(),
        name="availability-detail",
    ),
    path(
        "availability/by-offering/",
        views.availability_grouped_by_offering,
        name="availability-by-offering",
    ),
    # Bulk operations (lawyer-only)
    path(
        "availability/bulk-create/",
        views.bulk_create_availability,
        name="availability-bulk-create",
    ),
    path(
        "availability/clear-all/",
        views.clear_all_availability,
        name="availability-clear-all",
    ),
    path(
        "availability/copy-template/",
        views.copy_availability_template,
        name="availability-copy-template",
    ),
    # Availability viewing (public read access)
    path(
        "availability/weekly/",
        views.weekly_availability_view,
        name="availability-weekly",
    ),
    path(
        "availability/calendar/",
        views.availability_calendar,
        name="availability-calendar",
    ),
    path(
        "availability/check-time/",
        views.check_time_availability,
        name="availability-check-time",
    ),
    path(
        "availability/<uuid:lawyer_id>/<str:date>/",
        views.check_availability_for_date,
        name="check-availability-for-date",
    ),
    # Unavailability CRUD operations
    path(
        "unavailability/",
        views.UnavailabilityListCreateView.as_view(),
        name="unavailability-list-create",
    ),
    path(
        "unavailability/<uuid:pk>/",
        views.UnavailabilityDetailView.as_view(),
        name="unavailability-detail",
    ),
    path(
        "unavailability/stats/",
        views.unavailability_stats,
        name="unavailability-stats",
    ),
    path(
        "unavailability/clear-past/",
        views.clear_past_unavailability,
        name="unavailability-clear-past",
    ),
    # Public info endpoint
    path(
        "availability/types-info/",
        views.availability_types_info,
        name="availability-types-info",
    ),
]
