"""Serializers for authentication and workspace management."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import authenticate
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from apps.accounts.models import User, Workspace, WorkspaceMembership
from apps.core.exceptions import InvalidCredentials


class UserSerializer(serializers.ModelSerializer[User]):
    full_name = serializers.CharField(read_only=True)
    initials = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "full_name",
            "initials",
            "avatar_color",
            "locale",
            "time_zone",
            "is_active",
            "date_joined",
        ]
        read_only_fields = ["id", "email", "is_active", "date_joined"]


class WorkspaceSummarySerializer(serializers.ModelSerializer[Workspace]):
    """Lightweight workspace shape for the workspace switcher."""

    role = serializers.SerializerMethodField()

    class Meta:
        model = Workspace
        fields = ["id", "name", "slug", "role"]

    def get_role(self, obj: Workspace) -> str | None:
        # Populated by the view via prefetch to avoid an N+1 across the switcher.
        role_map: dict[Any, str] = self.context.get("role_map", {})
        return role_map.get(obj.pk)


class WorkspaceSerializer(serializers.ModelSerializer[Workspace]):
    """Full workspace/company profile."""

    class Meta:
        model = Workspace
        fields = [
            "id",
            "name",
            "slug",
            "legal_name",
            "legal_form",
            "owner_name",
            "email",
            "phone",
            "website",
            "address_street",
            "address_zip",
            "address_city",
            "address_country_code",
            "tax_number",
            "vat_id",
            "small_business",
            "bank_name",
            "bank_iban",
            "bank_bic",
            "default_currency",
            "default_hourly_rate",
            "default_payment_term_days",
            "time_rounding_increment_minutes",
            "time_rounding_strategy",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "slug", "created_at", "updated_at"]


class MembershipSerializer(serializers.ModelSerializer[WorkspaceMembership]):
    user = UserSerializer(read_only=True)

    class Meta:
        model = WorkspaceMembership
        fields = ["id", "user", "role", "is_active", "is_default", "joined_at"]
        read_only_fields = ["id", "user", "joined_at"]


class LoginSerializer(serializers.Serializer[dict[str, Any]]):
    email = serializers.EmailField()
    password = serializers.CharField(style={"input_type": "password"}, trim_whitespace=False)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        request = self.context.get("request")
        user = authenticate(
            request=request,
            username=attrs["email"].lower().strip(),
            password=attrs["password"],
        )
        # Deliberately identical response for "no such user", "wrong password"
        # and "inactive": distinguishing them lets an attacker enumerate accounts.
        if user is None or not user.is_active:
            raise InvalidCredentials
        attrs["user"] = user
        return attrs


class SessionSerializer(serializers.Serializer[dict[str, Any]]):
    """The /auth/session payload: who am I, where am I, what may I do."""

    user = UserSerializer(read_only=True)
    workspace = WorkspaceSerializer(read_only=True)
    workspaces = WorkspaceSummarySerializer(many=True, read_only=True)
    role = serializers.CharField(read_only=True)
    permissions = serializers.DictField(read_only=True)


class PasswordChangeSerializer(serializers.Serializer[dict[str, Any]]):
    current_password = serializers.CharField(style={"input_type": "password"})
    new_password = serializers.CharField(style={"input_type": "password"}, min_length=12)

    def validate_current_password(self, value: str) -> str:
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError(_("Current password is incorrect."))
        return value

    def validate_new_password(self, value: str) -> str:
        from django.contrib.auth.password_validation import validate_password

        validate_password(value, self.context["request"].user)
        return value
