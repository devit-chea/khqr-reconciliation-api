from django.urls import path
from .views import (
    ReconciliationListView,
    ReconciliationDetailView,
    ReconciliationExportView,
    ReconciliationResolveView,
    ReconciliationSummaryView,
    TransactionListView,
    TransactionReviewView,
    TriggerReconciliationView,
)

urlpatterns = [
    path("reconciliation/", ReconciliationListView.as_view(), name="reconciliation-list"),
    path("reconciliation/export/", ReconciliationExportView.as_view(), name="reconciliation-export"),
    path("reconciliation/summary/", ReconciliationSummaryView.as_view(), name="reconciliation-summary"),
    path("reconciliation/<int:pk>/", ReconciliationDetailView.as_view(), name="reconciliation-detail"),
    path("reconciliation/<int:pk>/resolve/", ReconciliationResolveView.as_view(), name="reconciliation-resolve"),
    path("reconciliation/trigger/", TriggerReconciliationView.as_view(), name="reconciliation-trigger"),
    path("transactions/", TransactionListView.as_view(), name="transaction-list"),
    path("transactions/<int:pk>/", TransactionReviewView.as_view(), name="transaction-review"),
]
