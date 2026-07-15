"""Web content Reader - fetch URL, extract main content, convert to markdown.

Extracted from render.py for shared use across the codebase.
"""

from __future__ import annotations

import asyncio
import re
import sys
import time
import unicodedata
from typing import Dict, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter
from readability import Document
import trafilatura



class DocsMarkdownConverter(MarkdownConverter):
    def convert_pre(self, el, text, convert_as_inline=False, **kwargs):
        code_el = el.find("code")
        lang = ""
        classes = (code_el.get("class") or []) if code_el else (el.get("class") or [])
        for c in classes:
            for prefix in ("language-", "lang-", "highlight-"):
                if c.startswith(prefix):
                    lang = c[len(prefix):]
                    break
            if lang:
                break
        code_text = (code_el.get_text() if code_el else el.get_text()).strip("\n")
        return f"\n```{lang}\n{code_text}\n```\n"


def md(html: str, **options) -> str:
    return DocsMarkdownConverter(**options).convert(html)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/137.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
}

MAIN_CONTENT_SELECTORS = [
    ('[role="main"]', None),
    ("main", None),
    ("article", None),
    ("div", "document"),
    ("div", "body"),
    ("div", "content"),
    ("div", "markdown-body"),
    ("div", "theme-doc-markdown"),
    ("div", "markdown-section"),
    ("div", "md-content__inner"),
    ("div", "wiki-content"),
    ("div", "page-body"),
    ("div", "swagger-ui"),
    ("section", "prose"),
]

MAIN_CONTENT_IDS = ["content", "main-content", "main", "docs-content", "readme"]

STRIP_INSIDE_MAIN = ["script", "style", "iframe", "noscript", "svg", "nav", "aside", "form", "button"]
STRIP_INSIDE_MAIN_CLASSES = [
    "headerlink", "edit-this-page", "breadcrumb", "breadcrumbs",
    "related", "sidebar", "toctree-l1-active-hidden",
]
REMOVE_TAGS_GENERIC = ["script", "style", "iframe", "noscript", "svg", "footer", "nav", "aside", "form", "button"]

MIN_CONTENT_LENGTH = 200
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

STATUS_MESSAGES = {
    401: "Cần đăng nhập (401 Unauthorized) - link private hoặc yêu cầu auth",
    403: "Bị từ chối truy cập (403 Forbidden) - có thể do WAF/anti-bot hoặc region-block",
    404: "Không tìm thấy trang (404 Not Found)",
    410: "Trang đã bị gỡ vĩnh viễn (410 Gone)",
    451: "Trang bị chặn vì lý do pháp lý (451 Unavailable For Legal Reasons)",
}

_MD_SYNTAX_RE = re.compile(r"[#*_`>\-\[\]()!|]")

JINA_READER_BASE = "https://r.jina.ai/"

QUALITY_MIN_LENGTH = 150
QUALITY_MIN_WORD_COUNT = 30
QUALITY_MAX_REPLACEMENT_CHAR_RATIO = 0.01
QUALITY_MIN_PLAIN_TEXT_RATIO = 0.25


class QualityEvaluator:
    @staticmethod
    def evaluate(markdown: str) -> tuple[bool, str]:
        if not markdown or len(markdown.strip()) < QUALITY_MIN_LENGTH:
            return False, f"nội dung quá ngắn ({len(markdown or '')} ký tự < {QUALITY_MIN_LENGTH})"

        word_count = len(markdown.split())
        if word_count < QUALITY_MIN_WORD_COUNT:
            return False, f"quá ít từ ({word_count} từ < {QUALITY_MIN_WORD_COUNT})"

        replacement_ratio = markdown.count("\ufffd") / max(len(markdown), 1)
        if replacement_ratio > QUALITY_MAX_REPLACEMENT_CHAR_RATIO:
            return False, f"phát hiện ký tự lỗi encoding ({replacement_ratio:.1%} là U+FFFD)"

        plain = _MD_SYNTAX_RE.sub("", markdown)
        plain_ratio = len(plain) / max(len(markdown), 1)
        if plain_ratio < QUALITY_MIN_PLAIN_TEXT_RATIO:
            return False, f"nội dung chủ yếu là markdown syntax/link, ít text thật ({plain_ratio:.1%})"

        return True, "ok"


class ExtractionError(Exception):
    pass


class Reader:

    def __init__(
        self,
        timeout: int = 20,
        max_retries: int = 3,
        debug: bool = False,
        jina_api_key: Optional[str] = None,
    ):
        self.client = httpx.Client(headers=HEADERS, timeout=timeout, follow_redirects=True)
        self.max_retries = max_retries
        self.debug = debug
        self.jina_api_key = jina_api_key
        self.timeout = timeout

    def _log(self, msg: str) -> None:
        if self.debug:
            print(f"[debug] {msg}", file=sys.stderr)

    def _get_with_retry(self, url: str) -> httpx.Response:
        last_exc = None
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.client.get(url)
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt == self.max_retries:
                    raise ExtractionError(
                        f"Lỗi mạng khi fetch {url}: {exc!r} (đã thử {attempt+1} lần)"
                    ) from exc
                wait = (2 ** attempt) + 0.5
                self._log(f"lỗi mạng: {exc!r}, retry sau {wait:.1f}s")
                time.sleep(wait)
                continue

            if resp.status_code < 400:
                return resp

            if resp.status_code in RETRYABLE_STATUS and attempt < self.max_retries:
                wait = (2 ** attempt) + 0.5
                self._log(f"status={resp.status_code}, retry sau {wait:.1f}s (lần {attempt+1})")
                time.sleep(wait)
                continue

            reason = STATUS_MESSAGES.get(resp.status_code)
            if reason:
                raise ExtractionError(f"{url} -> {reason}")
            raise ExtractionError(
                f"{url} -> HTTP {resp.status_code} {resp.reason_phrase} "
                f"(đã thử {attempt+1} lần)"
            )
        raise ExtractionError(f"Không fetch được {url} sau {self.max_retries+1} lần thử")

    def _fetch_via_jina(self, url: str) -> Dict:
        jina_url = JINA_READER_BASE + url
        headers = {"Accept": "text/plain", "X-Return-Format": "markdown"}
        if self.jina_api_key:
            headers["Authorization"] = f"Bearer {self.jina_api_key}"

        resp = self.client.get(jina_url, headers=headers, timeout=max(self.timeout, 40))
        resp.raise_for_status()
        raw = resp.text

        title_match = re.search(r"^Title:\s*(.+)$", raw, re.MULTILINE)
        title = title_match.group(1).strip() if title_match else ""
        content_match = re.search(r"^Markdown Content:\s*\n(.*)", raw, re.DOTALL | re.MULTILINE)
        markdown = content_match.group(1) if content_match else raw

        return {
            "url": url,
            "title": title,
            "markdown": self.clean(markdown),
            "length": len(markdown),
            "raw_html_length": None,
            "method_used": "jina_reader_fallback",
            "candidate_lengths": {},
            "last_updated": None,
            "breadcrumb": None,
        }

    def fetch(self, url: str) -> Dict:
        try:
            result = self._fetch_and_extract(url)
        except Exception as exc:
            self._log(f"Pipeline local lỗi ({exc!r}) -> fallback Jina Reader")
            try:
                return self._fetch_via_jina(url)
            except Exception as jina_exc:
                raise ExtractionError(
                    f"Pipeline local lỗi ({exc}); Jina Reader fallback cũng lỗi ({jina_exc!r})"
                ) from jina_exc

        ok, reason = QualityEvaluator.evaluate(result["markdown"])
        if ok:
            return result

        self._log(f"Chất lượng chưa đạt ({reason}) -> fallback Jina Reader")
        try:
            jina_result = self._fetch_via_jina(url)
        except Exception as exc:
            self._log(f"Jina fallback lỗi ({exc!r}) -> dùng kết quả gốc dù chất lượng thấp")
            result["quality_warning"] = reason
            return result

        jina_ok, jina_reason = QualityEvaluator.evaluate(jina_result["markdown"])
        if jina_ok or len(jina_result["markdown"]) > len(result["markdown"]):
            jina_result["quality_fallback_reason"] = reason
            return jina_result

        result["quality_warning"] = f"{reason} (Jina fallback cũng không tốt hơn: {jina_reason})"
        return result

    def _fetch_and_extract(self, url: str) -> Dict:
        response = self._get_with_retry(url)

        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            raise ExtractionError(
                f"Content-Type '{content_type}' không phải HTML cho {url} "
                f"(có thể là PDF/JSON/ảnh -> cần pipeline xử lý riêng)"
            )

        if response.encoding is None:
            response.encoding = response.apparent_encoding
        html = response.text

        if not html or len(html.strip()) < 50:
            raise ExtractionError(f"Response body rỗng hoặc quá ngắn cho {url}")

        candidates: Dict[str, str] = {}

        main_md, main_title = self._extract_main_container(html, url)
        if main_md:
            candidates["main_container"] = main_md
        self._log(f"main_container length = {len(main_md) if main_md else 0}")

        rb_title, rb_md = self._extract_readability(html, url)
        candidates["readability"] = rb_md
        self._log(f"readability length = {len(rb_md)}")


        traf_md = trafilatura.extract(
            html, url=url, output_format="markdown",
            include_links=True, include_images=True, favor_recall=True,
        )
        traf_md = self.clean(traf_md) if traf_md else ""
        candidates["trafilatura"] = traf_md
        self._log(f"trafilatura length = {len(traf_md)}")

        if not any(candidates.values()):
            body_text_len = self._body_text_length(html)
            hint = (
                " (raw HTML có rất ít text -> trang có thể là SPA cần JavaScript "
                "render, httpx không chạy được JS; cân nhắc dùng Playwright)"
                if body_text_len < MIN_CONTENT_LENGTH else ""
            )
            raise ExtractionError(f"Không extract được nội dung nào cho {url}.{hint}")

        best_key = max(candidates, key=lambda k: self._quality_score(candidates[k]))
        markdown = candidates[best_key]
        self._log(f"scores = {[(k, round(self._quality_score(v),1)) for k,v in candidates.items()]}")
        self._log(f"=> chọn '{best_key}'")

        title = main_title or rb_title or ""
        metadata = self._extract_metadata(html)

        return {
            "url": url,
            "title": title,
            "markdown": markdown,
            "length": len(markdown),
            "raw_html_length": len(html),
            "method_used": best_key,
            "candidate_lengths": {k: len(v) for k, v in candidates.items()},
            **metadata,
        }

    @staticmethod
    def _extract_metadata(html: str) -> Dict:
        soup = BeautifulSoup(html, "lxml")
        last_updated = None
        for meta_name in ("article:modified_time", "og:updated_time", "last-modified"):
            tag = soup.find("meta", attrs={"property": meta_name}) or soup.find(
                "meta", attrs={"name": meta_name}
            )
            if tag and tag.get("content"):
                last_updated = tag["content"]
                break
        if not last_updated:
            time_tag = soup.find("time")
            if time_tag and (time_tag.get("datetime") or time_tag.get_text(strip=True)):
                last_updated = time_tag.get("datetime") or time_tag.get_text(strip=True)

        breadcrumb = None
        bc_el = soup.find(attrs={"aria-label": "breadcrumb"}) or soup.find(class_=re.compile("breadcrumb"))
        if bc_el:
            parts = [a.get_text(strip=True) for a in bc_el.find_all("a")]
            if parts:
                breadcrumb = " > ".join(parts)

        return {"last_updated": last_updated, "breadcrumb": breadcrumb}

    @staticmethod
    def _quality_score(markdown: str) -> float:
        if not markdown:
            return 0.0
        plain = _MD_SYNTAX_RE.sub("", markdown)
        link_count = markdown.count("](")
        density_penalty = 1.0
        if len(plain) > 0:
            link_char_ratio = (link_count * 8) / max(len(plain), 1)
            if link_char_ratio > 0.85:
                density_penalty = 0.7
        return len(plain) * density_penalty

    @staticmethod
    def _body_text_length(html: str) -> int:
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style"]):
            tag.decompose()
        body = soup.body or soup
        return len(body.get_text(strip=True))

    def _extract_main_container(self, html: str, url: str) -> tuple[Optional[str], Optional[str]]:
        soup = BeautifulSoup(html, "lxml")
        title_tag = soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else None

        best_container = None
        best_len = 0
        for tag, cls in MAIN_CONTENT_SELECTORS:
            found_list = soup.find_all(tag, class_=cls) if cls else soup.select(tag)
            for found in found_list:
                text_len = len(found.get_text(strip=True))
                if text_len > best_len:
                    best_len = text_len
                    best_container = found

        for id_name in MAIN_CONTENT_IDS:
            found = soup.find(id=id_name)
            if found is not None:
                text_len = len(found.get_text(strip=True))
                if text_len > best_len:
                    best_len = text_len
                    best_container = found

        if best_container is None or best_len <= MIN_CONTENT_LENGTH:
            return None, title

        container = best_container
        for t in container(STRIP_INSIDE_MAIN):
            t.decompose()
        for cls in STRIP_INSIDE_MAIN_CLASSES:
            for t in container.find_all(class_=cls):
                t.decompose()

        for a in container.find_all("a", href=True):
            a["href"] = urljoin(url, a["href"])
        for img in container.find_all("img", src=True):
            img["src"] = urljoin(url, img["src"])

        markdown = md(str(container), heading_style="ATX")
        return self.clean(markdown), title

    def _extract_readability(self, html: str, url: str) -> tuple[str, str]:
        doc = Document(html, url=url)
        title = doc.short_title()
        article = doc.summary(html_partial=True)

        soup = BeautifulSoup(article, "lxml")
        for tag in soup(REMOVE_TAGS_GENERIC):
            tag.decompose()

        markdown = md(str(soup), heading_style="ATX")
        markdown = self.clean(markdown)
        return title, markdown

    @staticmethod
    def clean(text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        return text.strip()

    def close(self):
        self.client.close()


class AsyncReader:
    def __init__(
        self, concurrency: int = 5, delay: float = 0.3, timeout: int = 20,
        debug: bool = False, jina_api_key: Optional[str] = None,
    ):
        self.concurrency = concurrency
        self.delay = delay
        self.timeout = timeout
        self.debug = debug
        self.jina_api_key = jina_api_key

    async def fetch_all(self, urls: List[str]) -> List[Dict]:
        sem = asyncio.Semaphore(self.concurrency)
        results: List[Dict] = [None] * len(urls)

        async def worker(i: int, u: str):
            async with sem:
                loop = asyncio.get_event_loop()
                reader = Reader(timeout=self.timeout, debug=self.debug, jina_api_key=self.jina_api_key)
                try:
                    r = await loop.run_in_executor(None, reader.fetch, u)
                except Exception as exc:
                    r = {"url": u, "error": str(exc)}
                finally:
                    reader.close()
                await asyncio.sleep(self.delay)
                results[i] = r

        await asyncio.gather(*(worker(i, u) for i, u in enumerate(urls)))
        return results
