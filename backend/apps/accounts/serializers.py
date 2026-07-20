"""Serializers for authentication and workspace management."""

from __future__ import annotations

import re
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


class WorkspaceCreateSerializer(serializers.Serializer[dict[str, object]]):
    """Input for creating a workspace — the rest is filled in Einstellungen."""

    name = serializers.CharField(max_length=120)
    legal_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    small_business = serializers.BooleanField(required=False, default=False)


_IBAN_RE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
_BIC_RE = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")


class WorkspaceSerializer(serializers.ModelSerializer[Workspace]):
    """Full workspace/company profile.

    Sloppy-but-unambiguous input is normalised instead of rejected: a website
    without scheme gets ``https://``, IBAN/BIC lose spaces and casing. That
    happens in ``to_internal_value`` — field validation (URLField!) runs before
    ``validate_<field>`` hooks, so fixing values there would be too late.
    """

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

    def to_internal_value(self, data: Any) -> Any:
        if hasattr(data, "items"):
            data = dict(data.items())
            website = data.get("website")
            if isinstance(website, str):
                website = website.strip()
                if website and "://" not in website:
                    website = f"https://{website}"
                data["website"] = website
            for key in ("bank_iban", "bank_bic", "vat_id"):
                value = data.get(key)
                if isinstance(value, str):
                    data[key] = value.replace(" ", "").upper()
            for key in ("email", "tax_number", "phone"):
                value = data.get(key)
                if isinstance(value, str):
                    data[key] = value.strip()
        return super().to_internal_value(data)

    def validate_bank_iban(self, value: str) -> str:
        if value and not _IBAN_RE.match(value):
            raise serializers.ValidationError(
                "Bitte eine gültige IBAN eingeben (z. B. DE89 3704 0044 0532 0130 00)."
            )
        return value

    def validate_bank_bic(self, value: str) -> str:
        if value and not _BIC_RE.match(value):
            raise serializers.ValidationError(
                "Bitte einen gültigen BIC eingeben (8 oder 11 Zeichen, z. B. GENODEM1GLS)."
            )
        return value

    def validate_default_payment_term_days(self, value: int) -> int:
        if value > 180:
            raise serializers.ValidationError("Zahlungsziel darf höchstens 180 Tage betragen.")
        return value


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
