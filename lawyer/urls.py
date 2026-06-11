from django.urls import path

from . import views

app_name = "lawyer"

urlpatterns = [
    # LAWYER CATEGORY URLS
    path("categories/", views.LawyerCategoryListView.as_view(), name="category-list"),
    path(
        "categories/<uuid:pk>/",
        views.LawyerCategoryDetailView.as_view(),
        name="category-detail",
    ),
    path(
        "subcategories/",
        views.LawyerSubcategoryListView.as_view(),
        name="subcategory-list",
    ),
    path(
        "subcategories/<uuid:pk>/",
        views.LawyerSubcategoryDetailView.as_view(),
        name="subcategory-detail",
    ),
    # LAWYER PROFILE URLS
    path(
        "profiles/",
        views.LawyerProfileListView.as_view(),
        name="profile-list",
    ),
    path(
        "profiles/<uuid:pk>/",
        views.LawyerProfileDetailView.as_view(),
        name="profile-detail",
    ),
    path(
        "profiles/edit/",
        views.LawyerProfileUpdateView.as_view(),
        name="lawyer-profile-update",
    ),
    # LAWYER OFFERING URLS
    path(
        "offerings/",
        views.LawyerOfferingListCreateView.as_view(),
        name="offering-list-create",
    ),
    path(
        "offerings/<uuid:pk>/",
        views.LawyerOfferingDetailView.as_view(),
        name="offering-detail",
    ),
    path(
        "offerings/<uuid:pk>/edit/",
        views.LawyerOfferingDetailView.as_view(),
        name="offering-edit",
    ),
    path(
        "offerings/<uuid:pk>/delete/",
        views.LawyerOfferingDetailView.as_view(),
        name="offering-delete",
    ),
    # OFFERING TYPE URLS
    path(
        "offerings/<uuid:offering_id>/offering-types/",
        views.OfferingTypeListCreateView.as_view(),
        name="offering-type-list-create",
    ),
    path(
        "offering-types/<uuid:pk>/",
        views.OfferingTypeDetailView.as_view(),
        name="offering-type-detail",
    ),
    path(
        "offering-types/<uuid:pk>/edit/",
        views.OfferingTypeDetailView.as_view(),
        name="offering-type-edit",
    ),
    path(
        "offering-types/<uuid:pk>/delete/",
        views.OfferingTypeDetailView.as_view(),
        name="offering-type-delete",
    ),
    # PRICE CALCULATION URLS
    path("calculate-price/", views.calculate_appointment_price, name="calculate-price"),
    path(
        "pricing-plans/<uuid:pricing_plan_id>/details/",
        views.get_pricing_plan_details,
        name="pricing-plan-details",
    ),
    # DASHBOARD & ANALYTICS URLS
    path("dashboard/", views.lawyer_dashboard, name="lawyer-dashboard"),
    path("analytics/pricing/", views.pricing_analytics, name="pricing-analytics"),
    path("pricing-summary/", views.lawyer_pricing_summary, name="pricing-summary"),
    # PUBLIC URLS (for client browsing)
    path(
        "public/offerings/",
        views.PublicLawyerOfferingListView.as_view(),
        name="public-offering-list",
    ),
    path(
        "public/offerings/<uuid:pk>/",
        views.PublicLawyerOfferingDetailView.as_view(),
        name="public-offering-detail",
    ),
    # UTILITY URLS
    path("info/system/", views.system_info, name="system-info"),
]
