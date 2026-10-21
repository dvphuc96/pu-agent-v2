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
        pdf_path = self.root / f"{report.report_id}.pdf"
        self.renderer.write_pdf(self.renderer.render_print_html(report, evaluation), pdf_path)
        if pdf_path.is_file():
            self._copy_owned(pdf_path.name, pdf_path.read_bytes())

    def read_bytes(self, report_id: str, ext: str) -> bytes:
        """Return one artifact for the current principal, or raise KeyError."""
        from pu.identity.files import OwnershipDenied, _local_owner, owner_for_home, owner_root

        owner = owner_for_home(self.home)
        name = f"{report_id}.{ext}"
        sidecar = self.root / f"{report_id}.json.owner"
        recorded = sidecar.read_text(encoding="utf-8").strip() if sidecar.is_file() else ""
        if recorded and owner and recorded != owner:
            raise OwnershipDenied("artifact belongs to another user")
        if owner:
            owned = owner_root(self.home, owner) / "reports" / name
            if owned.is_file():
                return owned.read_bytes()
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
            root = self.root
        items = []
        for path in sorted(root.glob("report-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            sidecar = self.root / f"{path.stem}.json.owner"
            if owner and sidecar.is_file() and sidecar.read_text(encoding="utf-8").strip() != owner:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            items.append(data)
            if len(items) >= limit:
                break
        return items

    def _put(self, name: str, data: bytes) -> None:
        (self.root / name).write_bytes(data)
        self._copy_owned(name, data)
        if name.endswith(".json"):
            self._write_sidecar(name[: -len(".json")])

    def _copy_owned(self, name: str, data: bytes) -> None:
        from pu.identity.files import _record, owner_for_home, owner_root

        owner = owner_for_home(self.home)
        if not owner:
            return
        target = owner_root(self.home, owner) / "reports" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        _record(self.home, f"reports/{name}", owner)

    def _write_sidecar(self, report_id: str) -> None:
        from pu.identity.files import owner_for_home

        owner = owner_for_home(self.home)
        if not owner:
            return
        (self.root / f"{report_id}.json.owner").write_text(owner, encoding="utf-8")
