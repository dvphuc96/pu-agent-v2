"""Keep sender identity and public evidence separate from similarly named companies."""

from __future__ import annotations

import re
from email.utils import parseaddr
from urllib.parse import urlparse

RESEARCH_POLICY_VERSION = "company-boundary-v2"


def domain_of(url):
    return (urlparse(url).hostname or "").lower().removeprefix("www.")


def same_domain(url, target):
    host = domain_of(url)
    return bool(target and (host == target or host.endswith("." + target)))


def candidate_website(email):
    body = email.get("body_text") or email.get("snippet") or ""
    match = re.search(
        r"(?im)^\s*(?:website(?:\s+công\s+ty)?|company\s+website|web)\s*:\s*(https?://[^\s<>\"()]+)",
        body,
    )
    if match:
        url = match[1].rstrip(".,;")
        parsed = urlparse(url)
        if parsed.hostname and not parsed.username and not parsed.password:
            return f"{parsed.scheme}://{parsed.netloc}"
    sender = parseaddr(email.get("sender_email", ""))[1]
    domain = sender.rpartition("@")[2].lower()
    return "https://" + domain if domain else ""


def partner_identity(email, proposed_company="", website=""):
    body = email.get("body_text") or email.get("snippet") or ""
    sender = parseaddr(email.get("sender_email", ""))[1]
    domain = sender.rpartition("@")[2].lower()
    # A self-introduction is stronger attribution than an unrelated signature.
    intro, *signature = re.split(
        r"(?im)^\s*(?:trân trọng|best regards|kind regards|sincerely|regards)\s*[,!]?\s*$",
        body,
        maxsplit=1,
    )
    declared = ""
    patterns = [
        r"(?im)(?:quản lý|giám đốc|đại diện|manager|director)[^\n.]{0,100}?(?:tại|at)\s+([^\n.,;<>]{2,100})",
        r"(?im)(?:chúng tôi|bên em)\s+(?:là|đến từ|thuộc)\s+((?:công ty|tập đoàn|doanh nghiệp)\s+[^\n.;<>]{2,100})",
    ]
    for pattern in patterns:
        match = re.search(pattern, intro)
        if match:
            declared = match[1].strip()
            break
    name = declared or proposed_company.strip() or domain
    conflicts = []
    if signature:
        for line in signature[0].splitlines():
            if "|" in line:
                organization = line.rsplit("|", 1)[1].strip()
                if organization and organization.casefold() != name.casefold():
                    conflicts.append(
                        f"Phần giới thiệu ghi {name}, chữ ký ghi {organization}; cần xác minh đơn vị người gửi đại diện."
                    )
    website = website or candidate_website(email)
    target_domain = domain_of(website)
    affiliation_warnings = []
    contact = re.search(r"(?:tôi là|mình là|I am|I'm)\s+([^,\n.]{2,80})", intro, re.IGNORECASE)
    declared_contact = contact[1].strip() if contact else ""
    sender_name = email.get("sender_name", "").strip()
    if declared_contact and sender_name:
        import unicodedata
        def folded(value):
            return ''.join(c for c in unicodedata.normalize('NFD', value.casefold().replace('đ', 'd')) if not unicodedata.combining(c))
        if folded(declared_contact) != folded(sender_name):
            affiliation_warnings.append(
                f"Tên hiển thị người gửi là {sender_name}, phần tự giới thiệu ghi {declared_contact}; cần xác nhận đúng người liên hệ."
            )
    signature_emails = re.findall(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", signature[0] if signature else "")
    for address in dict.fromkeys(signature_emails):
        if address.casefold() != sender.casefold():
            affiliation_warnings.append(
                f"Địa chỉ gửi là {sender}, chữ ký ghi {address}; chưa xác minh địa chỉ liên hệ thay thế."
            )
    if (
        domain
        and target_domain
        and domain != target_domain
        and not domain.endswith("." + target_domain)
    ):
        affiliation_warnings.append(
            f"Người gửi dùng miền {domain}, website công ty được dẫn là {target_domain}. Chưa xác minh người gửi có quyền đại diện cho {name}."
        )
    return {
        "name": name,
        "name_origin": "self_introduction"
        if declared
        else "model"
        if proposed_company.strip()
        else "sender_domain",
        "sender_domain": domain,
        "sender_email": sender,
        "declared_contact": declared_contact,
        "signature_emails": list(dict.fromkeys(signature_emails)),
        "website": website,
        "research_domain": target_domain,
        "affiliation_warnings": affiliation_warnings,
        "status": "conflicting" if conflicts else "candidate",
        "conflicts": list(dict.fromkeys(conflicts)),
        "policy_version": RESEARCH_POLICY_VERSION,
    }


def source_relation(source, target_domain):
    """Names alone never join entities; require a domain or an explicit backlink."""
    url = source.get("url") or ""
    if same_domain(url, target_domain):
        return "sender_domain"
    metadata = source.get("metadata") or {}
    if any(
        same_domain(link, target_domain)
        for link in metadata.get("links", [])
        if isinstance(link, str)
    ):
        return "links_to_sender_domain"
    text = source.get("content") or source.get("excerpt") or ""
    if target_domain and re.search(
        r"(?<![\w.-])(?:www\.)?" + re.escape(target_domain) + r"(?![\w.-])", text, re.IGNORECASE
    ):
        return "mentions_sender_domain"
    return "unverified_entity"


def scoped_sources(sources, website):
    target = domain_of(website)
    accepted, rejected = [], []
    for source in sources:
        if source.get("source_type") in {"web", "news"}:
            relation = source_relation(source, target)
            if relation == "unverified_entity":
                rejected.append(source)
                continue
            source = {
                **source,
                "metadata": {**source.get("metadata", {}), "identity_relation": relation},
            }
        accepted.append(source)
    return accepted, rejected
