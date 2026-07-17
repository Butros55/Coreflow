"""Pagination defaults."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any

from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response


class DefaultPagination(PageNumberPagination):
    """Page-number pagination with a client-controllable, bounded page size."""

    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200  # Bounded: an unbounded page_size is a cheap DoS.

    def get_paginated_response(self, data: Any) -> Response:
        # DRF only calls this after paginate_queryset() has set both attributes.
        # Asserting the invariant documents it and satisfies the type checker,
        # rather than sprinkling `# type: ignore` over each access.
        assert self.page is not None
        assert self.request is not None
        return Response(
            OrderedDict(
                [
                    ("count", self.page.paginator.count),
                    ("num_pages", self.page.paginator.num_pages),
                    ("page", self.page.number),
                    ("page_size", self.get_page_size(self.request)),
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ]
            )
        )

    def get_paginated_response_schema(self, schema: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "object",
            "required": ["count", "results"],
            "properties": {
                "count": {"type": "integer", "example": 123},
                "num_pages": {"type": "integer", "example": 3},
                "page": {"type": "integer", "example": 1},
                "page_size": {"type": "integer", "example": 50},
                "next": {"type": "string", "nullable": True, "format": "uri"},
                "previous": {"type": "string", "nullable": True, "format": "uri"},
                "results": schema,
            },
        }


class LargePagination(DefaultPagination):
    """For board/kanban style endpoints that legitimately need more rows at once."""

    page_size = 200
    max_page_size = 500
