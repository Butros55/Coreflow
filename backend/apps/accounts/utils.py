"""Small helpers shared by view code."""

from __future__ import annotations

from typing import TYPE_CHECKING

from rest_framework.exceptions import NotAuthenticated

from apps.accounts.models import User

if TYPE_CHECKING:
    from rest_framework.request import Request


def require_user(request: Request) -> User:
    """Narrow ``request.user`` from ``User | AnonymousUser`` to ``User``.

    Views behind ``IsAuthenticated`` already guarantee a real user, but the type
    system cannot see that, and a bare ``cast`` would paper over the case where a
    view's permission classes are later loosened by mistake. This asserts the
    invariant once, and fails as a clean 401 rather than an AttributeError deep
    in a query if it is ever violated.
    """
    user = request.user
    if not isinstance(user, User) or not user.is_authenticated:
        raise NotAuthenticated
    return user
