from django.urls import path

from . import views

app_name = "lawyer_wallet"

urlpatterns = [
    # Wallet endpoints
    path("wallet/", views.WalletDetailView.as_view(), name="wallet_detail"),
    path("wallet/stats/", views.wallet_stats, name="wallet_stats"),
    # Transaction endpoints
    path(
        "lawyer/transactions/",
        views.LawyerTransactionsListView.as_view(),
        name="lawyer_transactions",
    ),
    path(
        "client/transactions/",
        views.ClientTransactionsListView.as_view(),
        name="client_transactions",
    ),
    path(
        "transactions/<uuid:id>/",
        views.TransactionDetailView.as_view(),
        name="transaction_detail",
    ),
    # Withdrawal endpoints
    path("withdraw/", views.WithdrawView.as_view(), name="lawyer_withdraw"),
]
