from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"plans", views.SubscriptionPlanViewSet)
router.register(
    r"payment-methods", views.PaymentMethodViewSet, basename="payment-methods"
)
router.register(r"notifications", views.NotificationViewSet, basename="notifications")

urlpatterns = [
    path(
        "",
        views.VendorSubscriptionView.as_view(),
        name="vendor-subscription",
    ),
    path("", include(router.urls)),
    path(
        "start-trial", views.InitTrialView.as_view(), name="start-trial"
    ),  # not needed now as we are activating subscription in signals
    path(
        "activate",
        views.SubscriptionActivateView.as_view(),
        name="activate-subscription",
    ),
    path(
        "cancel",
        views.SubscriptionCancelView.as_view(),
        name="cancel-subscription",
    ),
    path(
        "reactivate",
        views.SubscriptionReactivateView.as_view(),
        name="reactivate-subscription",
    ),
    path(
        "retry-payment",
        views.RetryFailedPaymentView.as_view(),
        name="retry-payment",
    ),
    path(
        "payment-methods/add",
        views.AddPaymentMethodView.as_view(),
        name="add-payment-method",
    ),
    path(
        "payment-methods/<int:pk>/set-primary",
        views.SetPrimaryPaymentMethodView.as_view(),
        name="set-primary-payment-method",
    ),
    path(
    "apply-voucher",
    views.ApplyVoucherToActiveSubscriptionView.as_view(),
    name="apply-voucher",
    ),
    path("invoices", views.SubscriptionInvoiceView.as_view(), name="invoices"),
    path(
        "vouchers/validate",
        views.VoucherValidateView.as_view(),
        name="validate-voucher",
    ),
]
