from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from .models import Business, UserProfile


class BusinessSerializer(serializers.ModelSerializer):
    bakong_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_bakong_credentials = serializers.SerializerMethodField()
    telegram_bot_token = serializers.CharField(write_only=True, required=False, allow_blank=True)
    has_telegram_credentials = serializers.SerializerMethodField()

    class Meta:
        model = Business
        fields = [
            "id", "name", "bakong_account_id", "bakong_token", "has_bakong_credentials",
            "telegram_bot_token", "telegram_chat_id", "has_telegram_credentials",
            "daily_digest_enabled", "sales_reminder_enabled",
            "bakong_last_polled_at", "bakong_last_error", "bakong_last_error_at",
            "created_at",
        ]
        read_only_fields = ["id", "bakong_last_polled_at", "bakong_last_error", "bakong_last_error_at", "created_at"]

    def get_has_bakong_credentials(self, obj):
        return bool(obj._bakong_token)

    def get_has_telegram_credentials(self, obj):
        return bool(obj._telegram_bot_token and obj.telegram_chat_id)

    def create(self, validated_data):
        token = validated_data.pop("bakong_token", "")
        telegram_token = validated_data.pop("telegram_bot_token", "")
        business = Business(**validated_data)
        business.set_bakong_token(token)
        business.set_telegram_bot_token(telegram_token)
        business.save()
        return business

    def update(self, instance, validated_data):
        token = validated_data.pop("bakong_token", None)
        telegram_token = validated_data.pop("telegram_bot_token", None)
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        if token is not None:
            instance.set_bakong_token(token)
        if telegram_token is not None:
            instance.set_telegram_bot_token(telegram_token)
        instance.save()
        return instance


class UserProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)
    business_name = serializers.CharField(source="business.name", read_only=True)

    class Meta:
        model = UserProfile
        fields = ["id", "username", "email", "business", "business_name", "role"]
        read_only_fields = ["id", "username", "email", "business_name"]


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        user = self.user
        data["username"] = user.username
        data["is_superuser"] = user.is_superuser
        try:
            profile = user.profile
            data["business_id"] = profile.business.id
            data["business_name"] = profile.business.name
            data["role"] = profile.role
        except Exception:
            data["business_id"] = None
            data["business_name"] = None
            data["role"] = "superuser" if user.is_superuser else None
        return data


class TeamMemberSerializer(serializers.ModelSerializer):
    """A user in the caller's business. Create takes username/password/email;
    updates may change role, is_active, or reset the password."""

    username = serializers.CharField(source="user.username")
    email = serializers.EmailField(source="user.email", required=False, allow_blank=True)
    is_active = serializers.BooleanField(source="user.is_active", required=False)
    last_login = serializers.DateTimeField(source="user.last_login", read_only=True)
    password = serializers.CharField(write_only=True, required=False, min_length=8, style={"input_type": "password"})

    class Meta:
        model = UserProfile
        fields = ["id", "username", "email", "role", "is_active", "last_login", "password"]

    def validate_username(self, value):
        User = get_user_model()
        qs = User.objects.filter(username__iexact=value)
        if self.instance is not None:
            qs = qs.exclude(pk=self.instance.user_id)
        if qs.exists():
            raise serializers.ValidationError("That username is taken.")
        return value

    def validate_password(self, value):
        validate_password(value)
        return value

    def validate(self, attrs):
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Required for new users."})
        return attrs

    def create(self, validated_data):
        user_data = validated_data.pop("user")
        password = validated_data.pop("password")
        user = get_user_model().objects.create_user(
            username=user_data["username"], email=user_data.get("email", ""), password=password,
            is_active=user_data.get("is_active", True),
        )
        return UserProfile.objects.create(user=user, **validated_data)

    def update(self, instance, validated_data):
        user_data = validated_data.pop("user", {})
        password = validated_data.pop("password", None)
        user = instance.user
        for attr, value in user_data.items():
            setattr(user, attr, value)
        if password:
            user.set_password(password)
        user.save()
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        return instance
