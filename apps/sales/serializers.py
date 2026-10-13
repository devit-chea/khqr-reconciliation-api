from rest_framework import serializers
from .models import DailySalesRecord


class DailySalesRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = DailySalesRecord
        fields = ["id", "branch", "date", "expected_total", "currency", "source", "created_by", "created_at"]
        read_only_fields = ["id", "created_by", "created_at"]

    def create(self, validated_data):
        validated_data["created_by"] = self.context["request"].user
        return super().create(validated_data)
