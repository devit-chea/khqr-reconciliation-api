from rest_framework import serializers
from .models import Branch


class BranchSerializer(serializers.ModelSerializer):
    business_name = serializers.CharField(source="business.name", read_only=True)

    class Meta:
        model = Branch
        fields = [
            "id", "business", "business_name", "name", "location", "bakong_account_id",
            "ingest_key_prefix", "ingest_key_created_at", "created_at",
        ]
        # business is set by the view for regular users; required only for superusers
        read_only_fields = ["id", "business_name", "ingest_key_prefix", "ingest_key_created_at", "created_at"]
        extra_kwargs = {"business": {"required": False}}
