"""Export/import endpoints for the whole workspace."""

from __future__ import annotations

import json

from django.core.serializers.json import DjangoJSONEncoder
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.permissions import IsWorkspaceAdmin, resolve_workspace
from apps.core.audit import record_audit
from apps.core.portability import ImportError_, export_workspace, import_workspace


class ExportWorkspaceView(APIView):
    """Download the signed-in workspace as one JSON file. Admin only."""

    permission_classes = [IsWorkspaceAdmin]

    def get(self, request: Request) -> HttpResponse:
        workspace = resolve_workspace(request)
        if workspace is None:
            return HttpResponse(status=http_status.HTTP_403_FORBIDDEN)

        payload = export_workspace(workspace)
        record_audit(
            request,
            "workspace.exported",
            workspace=workspace,
            target=workspace,
            summary=f"{sum(payload['counts'].values())} Objekte",
        )
        filename = f"coreflow-export-{workspace.slug}-{timezone.localdate().isoformat()}.json"
        response = HttpResponse(
            json.dumps(payload, cls=DjangoJSONEncoder, ensure_ascii=False, indent=2),
            content_type="application/json; charset=utf-8",
        )
        response["Content-Disposition"] = f'attachment; filename="{filename}"'
        return response


class ImportWorkspaceView(APIView):
    """Restore an export file into the signed-in workspace. Admin only.

    Upsert semantics: same ids are overwritten, new ids created, everything is
    re-pinned to THIS workspace. Data of other workspaces is never touched.
    """

    permission_classes = [IsWorkspaceAdmin]
    parser_classes = [MultiPartParser, JSONParser]

    def post(self, request: Request) -> Response:
        workspace = resolve_workspace(request)
        if workspace is None:
            return Response({"detail": "Kein Workspace."}, status=http_status.HTTP_403_FORBIDDEN)

        upload = request.FILES.get("file")
        if upload is not None:
            try:
                payload = json.load(upload)
            except (json.JSONDecodeError, UnicodeDecodeError):
                return Response(
                    {"error": {"code": "invalid_file", "message": "Keine gültige JSON-Datei."}},
                    status=http_status.HTTP_400_BAD_REQUEST,
                )
        else:
            payload = request.data

        try:
            result = import_workspace(workspace, payload, request.user)
        except ImportError_ as exc:
            return Response(
                {"error": {"code": "invalid_export", "message": str(exc)}},
                status=http_status.HTTP_400_BAD_REQUEST,
            )

        record_audit(
            request,
            "workspace.imported",
            workspace=workspace,
            target=workspace,
            summary=f"{sum(result['imported'].values())} Objekte importiert",
        )
        return Response(result)
