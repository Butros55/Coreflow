"""Users, workspaces and membership roles.

Coreflow is built for a single freelancer but is workspace-scoped from day one:
retrofitting tenancy onto a schema that assumed a single tenant means touching
every table and every query. The cost now is one FK per model; the cost later
would be a migration of the entire system.
"""

from __future__ import annotations

from typing import Any, ClassVar

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import BaseModel, UUIDModel


class WorkspaceRole(models.TextChoices):
    """Roles ordered from most to least privileged.

    Semantics (enforced in apps.accounts.permissions):

    * OWNER  — everything, including billing-relevant settings, integration
               credentials, workspace deletion, and member management.
    * ADMIN  — everything except workspace deletion and owner transfer.
    * MEMBER — full read/write on domain data (clients, projects, tasks, time),
               no settings or integration credential access.
    * READONLY — read-only on domain data. Cannot mutate anything.
    """

    OWNER = "owner", _("Owner")
    ADMIN = "admin", _("Admin")
    MEMBER = "member", _("Member")
    READONLY = "readonly", _("Read-only")


# Higher number = more privilege. Used for "at least this role" checks.
ROLE_RANK: dict[str, int] = {
    WorkspaceRole.READONLY: 10,
    WorkspaceRole.MEMBER: 20,
    WorkspaceRole.ADMIN: 30,
    WorkspaceRole.OWNER: 40,
}


class UserManager(BaseUserManager["User"]):
    use_in_migrations = True

    def _create_user(self, email: str, password: str | None, **extra: Any) -> User:
        if not email:
            raise ValueError("Users must have an email address.")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_user(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", False)
        extra.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra)

    def create_superuser(self, email: str, password: str | None = None, **extra: Any) -> User:
        extra.setdefault("is_staff", True)
        extra.setdefault("is_superuser", True)
        if extra.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra)


class User(UUIDModel, AbstractBaseUser, PermissionsMixin):
    """Email-identified user. There is no separate username."""

    email = models.EmailField(_("email address"), unique=True, db_index=True)
    first_name = models.CharField(_("first name"), max_length=150, blank=True)
    last_name = models.CharField(_("last name"), max_length=150, blank=True)

    is_active = models.BooleanField(_("active"), default=True)
    is_staff = models.BooleanField(_("staff status"), default=False)
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)

    # Presentation preferences
    avatar_color = models.CharField(
        max_length=7,
        blank=True,
        help_text=_("Hex colour used for the avatar fallback, e.g. #6366f1."),
    )
    locale = models.CharField(max_length=10, default="de-DE")
    time_zone = models.CharField(max_length=64, default="Europe/Berlin")

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = []

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")
        ordering = ["email"]

    def __str__(self) -> str:
        return self.email

    def clean(self) -> None:
        super().clean()
        self.email = self.email.lower().strip()

    @property
    def full_name(self) -> str:
        name = f"{self.first_name} {self.last_name}".strip()
        return name or self.email

    @property
    def initials(self) -> str:
        if self.first_name or self.last_name:
            return f"{self.first_name[:1]}{self.last_name[:1]}".upper() or self.email[:2].upper()
        return self.email[:2].upper()

    def get_full_name(self) -> str:
        return self.full_name

    def get_short_name(self) -> str:
        return self.first_name or self.email.split("@")[0]

    def role_in(self, workspace: Workspace) -> str | None:
        """Return this user's role string in a workspace, or None if not a member."""
        membership = self.memberships.filter(workspace=workspace, is_active=True).first()
        return membership.role if membership else None


class Workspace(BaseModel):
    """A tenant: one company/organisation's data.

    ``slug`` is stable and human-readable; it is safe in URLs and log lines.
    """

    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=80, unique=True, db_index=True)

    # Company profile (Settings → Unternehmensprofil)
    legal_name = models.CharField(max_length=255, blank=True)
    legal_form = models.CharField(max_length=100, blank=True)
    owner_name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=50, blank=True)
    website = models.URLField(blank=True)

    address_street = models.CharField(max_length=255, blank=True)
    address_zip = models.CharField(max_length=20, blank=True)
    address_city = models.CharField(max_length=120, blank=True)
    address_country_code = models.CharField(max_length=2, default="DE")

    tax_number = models.CharField(max_length=50, blank=True, help_text=_("Steuernummer"))
    vat_id = models.CharField(max_length=50, blank=True, help_text=_("USt-IdNr."))
    # Mirrors the Lexware profile flag when the integration is connected; until
    # then it is a local setting. Drives whether invoices carry VAT.
    small_business = models.BooleanField(
        default=False, help_text=_("Kleinunternehmerregelung nach §19 UStG")
    )

    bank_name = models.CharField(max_length=120, blank=True)
    bank_iban = models.CharField(max_length=42, blank=True)
    bank_bic = models.CharField(max_length=11, blank=True)

    default_currency = models.CharField(max_length=3, default="EUR")
    default_hourly_rate = models.DecimalField(max_digits=10, decimal_places=2, default=95)
    default_payment_term_days = models.PositiveSmallIntegerField(default=14)

    # Time rounding applied to new time entries.
    time_rounding_increment_minutes = models.PositiveSmallIntegerField(
        default=0, help_text=_("0 = no rounding. Otherwise round to this many minutes.")
    )
    time_rounding_strategy = models.CharField(
        max_length=10,
        default="nearest",
        choices=[("nearest", _("Nearest")), ("up", _("Up")), ("down", _("Down"))],
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name = _("workspace")
        verbose_name_plural = _("workspaces")

    def __str__(self) -> str:
        return self.name

    @property
    def owner(self) -> User | None:
        membership = self.memberships.filter(role=WorkspaceRole.OWNER, is_active=True).first()
        return membership.user if membership else None


class WorkspaceMembership(BaseModel):
    """Join table binding a user to a workspace with a role."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(
        max_length=20, choices=WorkspaceRole.choices, default=WorkspaceRole.MEMBER
    )
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(
        default=False, help_text=_("Workspace selected on login when none is specified.")
    )
    invited_at = models.DateTimeField(null=True, blank=True)
    joined_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["workspace__name", "user__email"]
        constraints = [
            models.UniqueConstraint(fields=["workspace", "user"], name="unique_workspace_member"),
            # At most one default workspace per user, enforced in the database
            # rather than in save() — concurrent requests would race otherwise.
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(is_default=True),
                name="unique_default_workspace_per_user",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "is_active"]),
            models.Index(fields=["workspace", "role"]),
        ]

    def __str__(self) -> str:
        return f"{self.user.email} @ {self.workspace.name} ({self.role})"

    @property
    def rank(self) -> int:
        return ROLE_RANK.get(self.role, 0)

    def has_at_least(self, role: str) -> bool:
        return self.rank >= ROLE_RANK.get(role, 0)

    def clean(self) -> None:
        super().clean()
        if self.role == WorkspaceRole.OWNER:
            clashing = WorkspaceMembership.objects.filter(
                workspace=self.workspace, role=WorkspaceRole.OWNER, is_active=True
            ).exclude(pk=self.pk)
            if clashing.exists():
                raise ValidationError(
                    {"role": _("This workspace already has an owner. Transfer ownership instead.")}
                )
