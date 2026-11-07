"""Lightweight, zero-dependency web search and webpage retrieval using DuckDuckGo."""

import html
import re
from urllib import parse as urlparse
from urllib import request as urlrequest
from urllib.error import HTTPError, URLError

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
MAX_PAGE_TEXT_CHARS = 4000


def search(query, max_results=5, timeout=5):
    """Perform a lightweight DuckDuckGo web search.

    Returns a dict with:
      - ok (bool)
      - query (str)
      - results (list of {title, url, snippet})
      - error (str or None)
      - offline (bool)
    """
    cleaned_query = (query or "").strip()
    if not cleaned_query:
        return {
            "ok": False,
            "query": "",
            "results": [],
            "error": "Search query cannot be empty.",
            "offline": False,
        }

    url = "https://html.duckduckgo.com/html/?q=" + urlparse.quote(cleaned_query)
    request = urlrequest.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    )

    try:
        with urlrequest.urlopen(request, timeout=timeout) as response:
            content = response.read().decode("utf-8", "replace")
    except (URLError, TimeoutError, OSError) as error:
        return {
            "ok": False,
            "query": cleaned_query,
            "results": [],
            "error": "Internet connection is unavailable. Operating in local-only mode.",
            "offline": True,
        }
    except HTTPError as error:
        return {
            "ok": False,
            "query": cleaned_query,
            "results": [],
            "error": f"Search engine returned HTTP {error.code}.",
            "offline": False,
        }

    results = []
    # Extract web-result containers
    blocks = re.findall(
        r'<div[^>]*class=\"[^\"]*web-result[^\"]*\"[^>]*>(.*?)(?=<div[^>]*class=\"[^\"]*web-result|\Z)',
        content,
        re.DOTALL,
    )

    for block in blocks:
        title_match = re.search(
            r'<a[^>]*class=\"[^\"]*result__a[^\"]*\"[^>]*href=\"([^\"]*)\"[^>]*>(.*?)</a>',
            block,
            re.DOTALL,
        )
        if not title_match:
            continue
        raw_url, raw_title = title_match.group(1), title_match.group(2)
        title = html.unescape(re.sub(r"<[^>]+>", "", raw_title)).strip()

        actual_url = raw_url
        if "uddg=" in raw_url:
            m = re.search(r"uddg=([^&]+)", raw_url)
            if m:
                actual_url = urlparse.unquote(m.group(1))
        elif raw_url.startswith("//"):
            actual_url = "https:" + raw_url

        # Skip tracking and sponsor links
        if "duckduckgo.com/y.js" in actual_url or "bing.com/aclick" in actual_url:
            continue

        snippet_match = re.search(
            r'<a[^>]*class=\"[^\"]*result__snippet[^\"]*\"[^>]*>(.*?)</a>',
            block,
            re.DOTALL,
        )
        snippet = ""
        if snippet_match:
            snippet = html.unescape(re.sub(r"<[^>]+>", "", snippet_match.group(1))).strip()

        if title and actual_url.startswith(("http://", "https://")):
            results.append({
                "title": title,
                "url": actual_url,
                "snippet": snippet,
            })
            if len(results) >= max_results:
                break

    return {
        "ok": True,
        "query": cleaned_query,
        "results": results,
        "error": None,
        "offline": False,
    }


def fetch_page_text(url, timeout=6):
    """Retrieve and extract clean, readable text from a webpage."""
    parsed = urlparse.urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return {"ok": False, "error": "Invalid webpage URL.", "url": url}

    request = urlrequest.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain"},
    )
    try:
        with urlrequest.urlopen(request, timeout=timeout) as response:
            content_type = response.headers.get("Content-Type", "")
            if "text" not in content_type and "html" not in content_type and "json" not in content_type:
                return {"ok": False, "error": "Unsupported media format.", "url": url}
            raw = response.read(150000).decode("utf-8", "replace")
    except (URLError, TimeoutError, OSError) as error:
        return {"ok": False, "error": f"Failed to retrieve page: {error}", "url": url}
    except HTTPError as error:
        return {"ok": False, "error": f"Page returned HTTP {error.code}.", "url": url}

    # Strip scripts, styles, forms, and SVGs
    text = re.sub(r"<(script|style|svg|noscript|header|footer|nav)[^>]*>.*?</\1>", " ", raw, flags=re.DOTALL | re.IGNORECASE)
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > MAX_PAGE_TEXT_CHARS:
        text = text[:MAX_PAGE_TEXT_CHARS].rstrip() + "… [truncated]"

    return {
        "ok": True,
        "url": url,
        "text": text or "No readable text content found.",
    }
