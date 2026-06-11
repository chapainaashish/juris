from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

# Create a router for viewsets
router = DefaultRouter()
router.register(r"media", views.MediaViewSet, basename="media")
router.register(r"certificates", views.CertificateViewSet, basename="certificate")
router.register(
    r"service-categories", views.ServiceCategoryViewSet, basename="service-category"
)
router.register(r"services", views.ServiceViewSet, basename="service")

urlpatterns = [
    # Profile setup session management
    path(
        "setup/start",
        views.StartProfileCompletionView.as_view(),
        name="profile-start",
    ),
    path(
        "setup/progress",
        views.ProfileProgressView.as_view(),
        name="profile-progress",
    ),
    # Profile setup steps
    path("setup/category", views.CategoryStepView.as_view(), name="profile-category"),
    path(
        "setup/business-name",
        views.BusinessNameStepView.as_view(),
        name="profile-business-name",
    ),
    path("setup/address", views.AddressStepView.as_view(), name="profile-address"),
    path(
        "setup/languages",
        views.LanguagesStepView.as_view(),
        name="profile-languages",
    ),
    path("setup/avatar", views.AvatarStepView.as_view(), name="profile-avatar"),
    path(
        "setup/legal-info",
        views.LegalInfoStepView.as_view(),
        name="profile-legal-info",
    ),
    path(
        "setup/additional-info",
        views.AdditionalInfoStepView.as_view(),
        name="profile-additional-info",
    ),
    path(
        "setup/complete",
        views.CompleteProfileView.as_view(),
        name="profile-complete",
    ),
    # CORE DATA ENDPOINTS (Categories, languages, etc.)
    path("languages", views.LanguageListView.as_view(), name="language-list"),
    path("categories", views.CategoryListView.as_view(), name="category-list"),
    path(
        "bar-associations",
        views.BarAssociationListView.as_view(),
        name="bar-association-list",
    ),
    # Main profile endpoints
    path("me", views.VendorProfileDetailView.as_view(), name="profile-detail"),
    path("me/update", views.VendorProfileUpdateView.as_view(), name="profile-update"),
    # Dedicated management endpoints for specific profile components
    path("me/address", views.AddressDetailView.as_view(), name="vendor-address"),
    path(
        "me/legal-info", views.VendorLegalInfoView.as_view(), name="vendor-legal-info"
    ),
    # Profile media uploads (for existing profiles)
    path(
        "me/avatar",
        views.ProfileAvatarUpdateView.as_view(),
        name="profile-avatar-update",
    ),
    # CLOUDINARY SIGNATURE ENDPOINTS (File upload utilities)
    path(
        "cloudinary/signature",
        views.CloudinarySignatureView.as_view(),
        name="cloudinary-signature",
    ),
    path(
        "cloudinary/media-signature",
        views.CloudinaryMediaSignatureView.as_view(),
        name="cloudinary-media-signature",
    ),
    path(
        "cloudinary/certificate-signature",
        views.CloudinaryCertificateSignatureView.as_view(),
        name="cloudinary-certificate-signature",
    ),
    path("", include(router.urls)),
]
