"""Web search and webpage retrieval."""

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
    """Search across available engines using the DDGS metasearch package.

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

    try:
        from ddgs import DDGS
    except ImportError:
        return {
            "ok": False,
            "query": cleaned_query,
            "results": [],
            "error": "The search extension is missing. Install dependencies with pip install -r requirements.txt.",
            "offline": False,
        }

    try:
        matches = DDGS(timeout=max(1, int(timeout))).text(
            cleaned_query,
            max_results=max(1, min(int(max_results), 10)),
            backend="auto",
        )
    except Exception as error:
        message = str(error).strip()
        offline = any(
            term in message.lower()
            for term in ("connect", "network", "dns", "resolve", "timeout", "internet")
        )
        return {
            "ok": False,
            "query": cleaned_query,
            "results": [],
            "error": "Internet connection is unavailable." if offline else (message or "Search provider failed."),
            "offline": offline,
        }

    results = []
    for item in matches or []:
        title = (item.get("title") or "").strip()
        url = (item.get("href") or item.get("url") or "").strip()
        if title and url.startswith(("http://", "https://")):
            results.append({
                "title": title,
                "url": url,
                "snippet": (item.get("body") or item.get("snippet") or "").strip(),
            })

    return {
        "ok": bool(results),
        "query": cleaned_query,
        "results": results,
        "error": None if results else "No search results were returned.",
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
