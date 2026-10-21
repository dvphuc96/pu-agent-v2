"""Expose differing explicit founding milestones without deciding legal identity."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from pu.reporting.citations import canonical_public_url


def company_profile_checks(sources):
    by_domain = {}
    seen = set()
    for source in reversed(sources):
        if source.derived or source.metadata.get('snippet_only') or source.source_type != 'web':
            continue
        path = urlparse(source.url or '').path.lower().strip('/')
        profile_pages = {'', 'jp', 'ja', 'en', 'about', 'about-us', 'company', 'company-profile', 'profile', 'gioi-thieu', 've-chung-toi', 'contact', 'lien-he'}
        if path.rsplit('/', 1)[-1] not in profile_pages or source.metadata.get('is_news'):
            continue
        domain = (urlparse(source.url or '').hostname or '').lower().removeprefix('www.')
        if not domain:
            continue
        key = canonical_public_url(source.url)
        if key in seen:
            continue
        seen.add(key)
        years = re.findall(r'(?:thành lập|founded|established|設立)\D{0,35}?((?:19|20)\d{2})', source.excerpt, re.IGNORECASE)
        for year in years:
            by_domain.setdefault(domain, {}).setdefault(year, source.id)
    result = []
    for domain, years in sorted(by_domain.items()):
        if len(years) <= 1:
            continue
        refs = list(dict.fromkeys(years.values()))
        if len(refs) <= 1:
            continue
        milestones = ', '.join(f'{year} [{ref}]' for year, ref in sorted(years.items()))
        result.append({'code':'founding_milestone_difference','domain':domain,'source_ids':refs,'years':sorted(years),
                       'message':f'Các trang trên {domain} nêu mốc thành lập khác nhau: {milestones}. Chưa xác minh đây là cùng pháp nhân hoặc cùng cách tính mốc thành lập; cần đối chiếu trước khi dùng năm thành lập như dữ kiện thống nhất.'})
    return result
