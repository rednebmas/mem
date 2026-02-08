"""Browser history source - noise-filtered item lists."""

from collections import defaultdict

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'lib'))

from browser_db import read_all, extract_search_query, get_domain
from .shared import is_noise_entry, format_time_range
from .base import Source


def _filter_and_dedupe(entries, search_urls):
    """Remove noise titles, search result pages, and deduplicate by page title."""
    seen_titles = set()
    filtered = []
    for e in entries:
        if e["url"] in search_urls:
            continue
        title = e["title"].strip()
        if not title or title in seen_titles:
            continue
        if is_noise_entry(e["url"], title):
            continue
        seen_titles.add(title)
        filtered.append(e)
    return filtered


def _extract_all_searches(entries):
    """Extract unique search queries and collect their source URLs."""
    seen = set()
    queries = []
    search_urls = set()
    for e in entries:
        sq = extract_search_query(e["url"])
        if sq:
            search_urls.add(e["url"])
            if sq not in seen:
                seen.add(sq)
                queries.append(sq)
    return queries, search_urls


def _group_by_domain(entries):
    by_domain = defaultdict(list)
    for e in entries:
        domain = get_domain(e["url"])
        by_domain[domain].append(e["title"])
    return sorted(by_domain.items(), key=lambda x: -len(x[1]))


class BrowserSource(Source):
    name = "browser"
    description = "Browser history from Chrome and Safari"
    platform_required = "Darwin"

    def collect(self, since_dt, until_dt=None):
        all_entries = read_all(since_dt, until_dt=until_dt)
        if not all_entries:
            return None

        searches, search_urls = _extract_all_searches(all_entries)
        filtered = _filter_and_dedupe(all_entries, search_urls)
        if not filtered and not searches:
            return None

        lines = [f"# Browser ({format_time_range(since_dt)}, {len(filtered)} unique pages after filtering)"]

        if searches:
            lines.append(f"\nSearches ({len(searches)}):")
            for sq in searches:
                lines.append(f'- "{sq}"')

        for domain, titles in _group_by_domain(filtered):
            lines.append(f"\n{domain} ({len(titles)} pages):")
            for title in titles:
                lines.append(f'- "{title}"')

        return "\n".join(lines)
