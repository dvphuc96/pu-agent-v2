"""Regression cases from the Vinamilk briefing, using synthetic evidence only."""

import subprocess
from datetime import datetime, time
from io import BytesIO
from zoneinfo import ZoneInfo

import pytest

from pu.orchestration.inbox_chat import inline_report
from pu.reporting.availability import AvailabilityPolicy, free_windows
from pu.reporting.pdf_text import _parse, extract_pdf
from pu.reporting.research_plan import build_research_plan, topic_for_path


def test_query_separates_company_and_domain_and_investor_path_is_scale():
    queries = [query for _, query in build_research_plan("Vinamilk", "vinamilk.com.vn")]
    assert all('"vinamilk.com.vn Vinamilk"' not in query for query in queries)
    assert any('site:vinamilk.com.vn "Vinamilk"' in query for query in queries)
    assert any(query.startswith('"Vinamilk"') and 'site:' not in query for query in queries)
    assert topic_for_path("/investor-relations/annual-report.pdf") == ("scale_operations",)
    assert topic_for_path("/products/kem") == ("products_markets",)


def test_catalogue_cannot_exhaust_reads_before_corporate_evidence(tmp_path, monkeypatch):
    from pu.ops.briefing import BriefingService
    from pu.reporting.collection import CollectionConfig, collect_partner_sources

    service = BriefingService(tmp_path)
    workspace = service.repo.create("Synthetic Dairy", "https://dairy.example", "person@dairy.example")
    root = workspace["website"]
    annual, technology = root + "/investor/annual-report.pdf", root + "/technology"
    catalogue = [root + f"/products/item-{index}" for index in range(20)]
    fetched, searched = [], []

    def fetch(url):
        fetched.append(url)
        return {"url": url, "title": "Synthetic Dairy", "content": "Synthetic Dairy company evidence.",
                "source_type": "web", "metadata": {"links": [*catalogue, annual, technology]} if url == root else {}}

    def search(query, max_results):
        searched.append(query)
        return [{"url": annual, "title": "Annual report"},
                {"url": technology, "title": "Technology"},
                *[{"url": url, "title": "Product"} for url in catalogue]]

    monkeypatch.setattr("pu.reporting.collection.fetch_source", fetch)
    monkeypatch.setattr("pu.reporting.collection.search_results", search)
    collect_partner_sources(service.repo, workspace["id"], config=CollectionConfig(max_read_attempts=8))
    assert annual in fetched and technology in fetched
    assert sum("/products/" in url for url in fetched) <= 1
    assert searched and len(fetched) <= 8
    calendar = next(source for source in service.repo.sources(workspace["id"]) if source["source_type"] == "calendar")
    assert calendar["metadata"]["collection_performance"]["topic_coverage"]["scale_operations"] >= 1


def test_friday_slots_avoid_lunch_preserve_week_and_offer_multiple_choices():
    reference = datetime(2026, 10, 16, 11, 8, tzinfo=ZoneInfo("Asia/Ho_Chi_Minh"))
    slots = free_windows([], start=reference, days=3, duration=45)
    assert len(slots) == 3
    assert slots[0]["window"] == "13:30–14:15"
    for index, slot in enumerate(slots):
        start, end = datetime.fromisoformat(slot["start"]), datetime.fromisoformat(slot["end"])
        assert start.date() == reference.date()
        assert time(13, 30) <= start.time() < end.time() <= time(17, 30)
        assert (start - reference).total_seconds() >= 3600
        if index:
            assert datetime.fromisoformat(slots[index - 1]["end"]) <= start


def test_availability_policy_busy_weekend_and_last_hour():
    zone = ZoneInfo("Asia/Ho_Chi_Minh")
    assert not free_windows([], start=datetime(2026, 10, 16, 17, tzinfo=zone), days=3, duration=45)
    assert not free_windows([], start=datetime(2026, 10, 17, 9, tzinfo=zone), days=2, duration=45)
    start = datetime(2026, 10, 16, 8, tzinfo=zone)
    events = [{"start": "2026-10-16T00:00:00+07:00", "end": "2026-10-17T00:00:00+07:00"}]
    assert not free_windows(events, start=start, days=1, duration=45)
    slots = free_windows([], start=start, days=1, duration=45,
                         policy=AvailabilityPolicy(lead_minutes=0, max_slots=1))
    assert len(slots) == 1 and slots[0]["window"] == "09:00–09:45"


def test_chat_retains_cited_ninth_source_and_specific_conflict_without_duplicate_warning():
    sources = [{"id": f"W{i}", "title": f"Nguồn {i}", "source_type": "web",
                "url": f"https://example.com/page-{i}"} for i in range(1, 10)]
    payload = {
        "title": "Vinamilk", "executive_summary": "Giới thiệu có nguồn [W9].",
        "sections": {"public_research": "- Bối cảnh công nghệ [W9].",
                     "email_need": "Theo email, thử nghiệm tại một phòng ban [W10] ."},
        "sources": [*sources, {"id": "W10", "source_type": "email", "title": "Email"}],
        "missing_information": ["Chưa xác minh quyền đại diện.", "Chưa có mẫu tài liệu."],
        "contradictions": [{"description": "Hai nguồn nêu khác nhau về phạm vi pilot.", "source_ids": ["W8", "W9"]}],
        "metadata": {"partner_identity": {"affiliation_warnings": ["Chưa xác minh quyền đại diện."]}},
        "evaluation": {"release_allowed": False, "status_details": {"semantic_review": "unavailable"}},
    }
    text = inline_report(payload)
    assert "[9](https://example.com/page-9)" in text
    assert "- [9] [Nguồn 9](https://example.com/page-9)" in text
    assert "phòng ban ." not in text and "phòng ban." in text
    assert text.count("Chưa xác minh quyền đại diện.") == 1
    assert text.count("Theo email, thử nghiệm") == 1
    assert "Hai nguồn nêu khác nhau về phạm vi pilot." in text
    assert "các nguồn có thông tin mâu thuẫn" not in text
    assert "Chưa hoàn tất bước đối chiếu" in text


def _pdf_bytes(*, encrypted=False, pages=1, with_text=True):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=200, height=200)
        if with_text:
            stream = DecodedStreamObject()
            stream.set_data(b"BT /F1 12 Tf 10 10 Td (Synthetic company report) Tj ET")
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                     NameObject("/Subtype"): NameObject("/Type1"),
                                     NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("test-password")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_extraction_isolated_and_page_attributed():
    result = extract_pdf(_pdf_bytes())
    assert "[Trang 1]" in result["content"]
    assert "Synthetic company report" in result["content"]
    assert result["page_count"] == 1


@pytest.mark.parametrize("options", [{"encrypted": True}, {"pages": 61}, {"with_text": False}])
def test_pdf_rejects_encryption_large_page_count_and_empty_text(options):
    with pytest.raises(ValueError):
        _parse(_pdf_bytes(**options))


def test_pdf_parser_timeout_and_invalid_header_are_closed_failures(monkeypatch):
    with pytest.raises(ValueError):
        extract_pdf(b"not a PDF")
    with pytest.raises(ValueError):
        extract_pdf(b"%PDF-" + b" " * 2_000_000)

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 8)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(ValueError, match="giới hạn"):
        extract_pdf(b"%PDF-1.4\n")
