from django.urls import path

from . import views

urlpatterns = [
    # Appointment Management
    path("create/", views.CreateAppointmentView.as_view(), name="create_appointment"),
    path(
        "<uuid:appointment_id>/",
        views.AppointmentDetailView.as_view(),
        name="appointment_detail",
    ),
    path(
        "<uuid:appointment_id>/reschedule/",
        views.RescheduleAppointmentView.as_view(),
        name="reschedule_appointment",
    ),
    path(
        "<uuid:appointment_id>/cancel/",
        views.CancelAppointmentView.as_view(),
        name="cancel_appointment",
    ),
    path(
        "<uuid:appointment_id>/refund-status/",
        views.RefundStatusView.as_view(),
        name="refund_status",
    ),
    # Agora Video Call Session Management
    path(
        "<uuid:appointment_id>/session/",
        views.get_session_details,
        name="session_details",
    ),
    path(
        "<uuid:appointment_id>/session/join/",
        views.join_session,
        name="join_session",
    ),
    path(
        "<uuid:appointment_id>/session/leave/",
        views.leave_session,
        name="leave_session",
    ),
    path(
        "<uuid:appointment_id>/session/end/",
        views.end_session,
        name="end_session",
    ),
    path(
        "<uuid:appointment_id>/session/status/",
        views.session_status,
        name="session_status",
    ),
    # Appointment Lists with Filters
    path(
        "lawyer/", views.LawyerAppointmentListView.as_view(), name="lawyer_appointments"
    ),
    path(
        "client/", views.ClientAppointmentListView.as_view(), name="client_appointments"
    ),
    # Stats and Analytics
    path("stats/", views.appointment_stats, name="appointment_stats"),
    # Manual completion endpoint
    path(
        "<uuid:appointment_id>/complete/",
        views.mark_appointment_completed,
        name="mark_appointment_completed",
    ),
]
