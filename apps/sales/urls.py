from django.urls import path
from .views import BranchSalesListCreateView, BranchSalesCSVImportView, SalesIngestView

urlpatterns = [
    path("branches/<int:branch_pk>/sales/", BranchSalesListCreateView.as_view(), name="branch-sales"),
    path("branches/<int:branch_pk>/sales/import/", BranchSalesCSVImportView.as_view(), name="branch-sales-import"),
    path("ingest/sales/", SalesIngestView.as_view(), name="sales-ingest"),
]
