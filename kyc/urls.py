from django.urls import path

from . import views

app_name = "kyc"

urlpatterns = [
    path("verification/", views.KYCVerificationView.as_view(), name="kyc-verification"),
]
