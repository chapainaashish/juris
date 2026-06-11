from django.urls import path
from django_channels_jwt.views import AsgiValidateTokenView

from . import views

urlpatterns = [
    # USER MANAGEMENT URLs
    path("check-email", views.CheckEmailView.as_view(), name="check-email"),
    path("update-phone", views.UpdatePhoneView.as_view(), name="update-phone"),
    # AUTHENTICATION URLs
    path("login", views.LoginView.as_view(), name="login"),
    path("logout", views.LogoutView.as_view(), name="logout"),
    path("signup", views.SignupView.as_view(), name="signup"),
    path("google-login", views.GoogleLoginView.as_view(), name="google-login"),
    path("token/refresh", views.CustomTokenRefreshView.as_view(), name="token_refresh"),
    path("ws", AsgiValidateTokenView.as_view()),
    # EMAIL VERIFICATION URLs
    path(
        "verify-email/<uidb64>/<token>/",
        views.VerifyEmailView.as_view(),
        name="verify-email",
    ),
    # TWO-FACTOR AUTHENTICATION URLs
    path("verify-otp", views.VerifyOTPView.as_view(), name="verify_otp"),
    path("toggle-2fa", views.Toggle2FAView.as_view(), name="toggle_2fa"),
    path("resend-otp", views.ResendOTPView.as_view(), name="resend_otp"),
    # EMAIL CHANGE URLs
    path(
        "change-email/request",
        views.ChangeEmailRequestView.as_view(),
        name="change-email-request",
    ),
    path(
        "change-email/verify",
        views.VerifyEmailChangeView.as_view(),
        name="verify-email-change",
    ),
    path(
        "change-email/resend",
        views.ResendEmailChangeCodeView.as_view(),
        name="resend-email-change",
    ),
    # PASSWORD MANAGEMENT URLs
    path("change-password", views.ChangePasswordView.as_view(), name="change-password"),
    path("forgot-password", views.ForgotPasswordView.as_view(), name="forgot-password"),
    path("reset-password", views.ResetPasswordView.as_view(), name="reset-password"),
    path(
        "resend-reset-otp",
        views.ResendPasswordResetOTPView.as_view(),
        name="resend-reset-otp",
    ),
    path("otp-status", views.OTPStatusView.as_view(), name="otp-status"),
    # PROFILE MANAGEMENT URLs
    path("profile", views.UserProfileView.as_view(), name="user-profile"),
    path("profile/update", views.UpdateProfileView.as_view(), name="update-profile"),
]
