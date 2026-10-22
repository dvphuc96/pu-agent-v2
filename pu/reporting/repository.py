"""Local-first report artifact repository."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pu.reporting.models import StructuredReport
from pu.reporting.render import ReportRenderer


class FileReportRepository:
    def __init__(self, home: Path, renderer: ReportRenderer | None = None):
        self.home = home
        self.root = home / "reports"
        self.root.mkdir(parents=True, exist_ok=True)
        self.renderer = renderer or ReportRenderer()

    def save(self, report: StructuredReport, evaluation: Any | None = None) -> None:
        payload = report.to_dict()
        if evaluation is not None:
            payload["evaluation"] = evaluation.to_dict() if hasattr(evaluation, "to_dict") else evaluation
        self._put(f"{report.report_id}.json", json.dumps(payload, ensure_ascii=False, indent=2).encode())
        self._put(f"{report.report_id}.md", report.markdown.encode())
        # Human-readable artifacts: .html always (pure stdlib), .pdf when the
        # optional extra is installed. Presentation must never fail a save.
        # The browser gets the two-pane NotebookLM view; the PDF pipeline gets
        # the flat print layout (xhtml2pdf has no grid support).
        html_text = self.renderer.render_html(report, evaluation)
        self._put(f"{report.report_id}.html", html_text.encode())
        pdf_path = self._artifact_root() / f"{report.report_id}.pdf"
        self.renderer.write_pdf(self.renderer.render_print_html(report, evaluation), pdf_path)
        if pdf_path.is_file():
            from pu.identity.files import _record, owner_for_home

            owner = owner_for_home(self.home)
            if owner:
                _record(self.home, f"reports/{pdf_path.name}", owner)

    def read_bytes(self, report_id: str, ext: str) -> bytes:
        """Return one artifact for the current principal, or raise KeyError."""
        from pu.identity.files import OwnershipDenied, _local_owner, owner_for_home, owner_root

        owner = owner_for_home(self.home)
        name = f"{report_id}.{ext}"
        if owner:
            owned = owner_root(self.home, owner) / "reports" / name
            if owned.is_file():
                return owned.read_bytes()
        owners = self.home / "owners"
        if owners.is_dir():
            for child in owners.iterdir():
                if child.is_dir() and (child / "reports" / name).is_file() and child.name != owner:
                    raise OwnershipDenied("artifact belongs to another user")
        sidecar = self.root / f"{report_id}.json.owner"
        recorded = sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else ""
        if recorded and owner and recorded != owner:
            raise OwnershipDenied("artifact belongs to another user")
        legacy = self.root / name
        if not legacy.is_file():
            raise KeyError("artifact")
        if not recorded and owner:
            local = _local_owner(self.home)
            if local and owner != local:
                raise OwnershipDenied("artifact belongs to another user")
        return legacy.read_bytes()

    def list(self, limit: int = 50) -> list[dict]:
        from pu.identity.files import owner_for_home, owner_root

        owner = owner_for_home(self.home)
        root = owner_root(self.home, owner) / "reports" if owner else self.root
        if not root.is_dir():
            return []
        items = []
        for path in sorted(root.glob("report-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items.append(data)
            if len(items) >= limit:
                break
        return items

    def _artifact_root(self) -> Path:
        from pu.identity.files import owner_for_home, owner_root

        owner = owner_for_home(self.home)
        if not owner:
            return self.root
        root = owner_root(self.home, owner) / "reports"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _put(self, name: str, data: bytes) -> None:
        from pu.identity.files import _record, owner_for_home

        root = self._artifact_root()
        (root / name).write_bytes(data)
        owner = owner_for_home(self.home)
        if owner:
            _record(self.home, f"reports/{name}", owner)

    def _copy_owned(self, name: str, data: bytes) -> None:
        self._put(name, data)
