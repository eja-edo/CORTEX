#!/usr/bin/env python3
"""
Reader / content extractor - dùng để crawl và convert nội dung web sang markdown,
phục vụ tổng hợp tài liệu cho pentest report.

Usage:
    python render.py https://example.com/article
    python render.py https://a.com https://b.com --out results.json
    python render.py --file urls.txt --out-dir ./extracted --concurrency 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from markdownify import MarkdownConverter
from readability import Document

try:
    import trafilatura
    HAS_TRAFILATURA = True
except ImportError:
    HAS_TRAFILATURA = False


class DocsMarkdownConverter(MarkdownConverter):
    """Converter tuỳ chỉnh: giữ lại ngôn ngữ syntax-highlight khi convert
    <pre><code class="language-xxx"> thành fenced code block ```xxx,
    thay vì mất hết thông tin ngôn ngữ như markdownify mặc định."""

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
    # Không set Accept-Encoding thủ công -> để httpx tự quảng cáo đúng những gì
    # nó thực sự giải nén được (tránh lỗi nhận response nén mà không decode nổi).
}

MAIN_CONTENT_SELECTORS = [
    ('[role="main"]', None),
    ("main", None),
    ("article", None),
    ("div", "document"),           # Sphinx cũ
    ("div", "body"),                # Sphinx
    ("div", "content"),
    ("div", "markdown-body"),       # GitHub README/wiki
    ("div", "theme-doc-markdown"),  # Docusaurus
    ("div", "markdown-section"),    # Docsify
    ("div", "md-content__inner"),   # MkDocs Material
    ("div", "wiki-content"),        # Confluence
    ("div", "page-body"),           # Notion-style export
    ("div", "swagger-ui"),          # Swagger/OpenAPI docs
    ("section", "prose"),           # Tailwind-docs style (Redoc, Stoplight...)
]

# Một số docs platform để nội dung trong id thay vì class -> thử thêm theo id
MAIN_CONTENT_IDS = ["content", "main-content", "main", "docs-content", "readme"]

STRIP_INSIDE_MAIN = ["script", "style", "iframe", "noscript", "svg", "nav", "aside", "form", "button"]
STRIP_INSIDE_MAIN_CLASSES = [
    "headerlink", "edit-this-page", "breadcrumb", "breadcrumbs",
    "related", "sidebar", "toctree-l1-active-hidden",
]
REMOVE_TAGS_GENERIC = ["script", "style", "iframe", "noscript", "svg", "footer", "nav", "aside", "form", "button"]

MIN_CONTENT_LENGTH = 200
# Lỗi có thể tạm thời, đáng thử lại (rate-limit, server quá tải, bot-check tạm thời)
RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}

# Lỗi vĩnh viễn với chính request này -> retry vô ích, nên fail nhanh với thông báo rõ
STATUS_MESSAGES = {
    401: "Cần đăng nhập (401 Unauthorized) - link private hoặc yêu cầu auth, script không xử lý được",
    403: "Bị từ chối truy cập (403 Forbidden) - có thể do: (a) trang yêu cầu đăng nhập, "
         "(b) IP/User-Agent bị chặn bởi WAF/anti-bot, hoặc (c) region-block",
    404: "Không tìm thấy trang (404 Not Found) - kiểm tra lại URL",
    410: "Trang đã bị gỡ vĩnh viễn (410 Gone)",
    451: "Trang bị chặn vì lý do pháp lý (451 Unavailable For Legal Reasons)",
}

# markdown link/heading syntax để loại khi tính "plain text density"
_MD_SYNTAX_RE = re.compile(r"[#*_`>\-\[\]()!|]")

# ---- Jina AI Reader fallback (https://jina.ai/reader) ----
# Cách dùng: prefix URL gốc bằng https://r.jina.ai/ -> Jina tự fetch + render
# (kể cả JS/SPA) + convert sang markdown ở phía server của họ. Free tier có
# rate-limit; nếu có API key thì truyền qua Authorization header để tăng hạn mức.
JINA_READER_BASE = "https://r.jina.ai/"

# ---- Ngưỡng đánh giá chất lượng kết quả extract ----
QUALITY_MIN_LENGTH = 150
QUALITY_MIN_WORD_COUNT = 30
QUALITY_MAX_REPLACEMENT_CHAR_RATIO = 0.01  # tỉ lệ ký tự lỗi encoding (U+FFFD) cho phép
QUALITY_MIN_PLAIN_TEXT_RATIO = 0.25  # plain-text / tổng markdown, quá thấp = toàn syntax/link rác


class QualityEvaluator:
    """Đánh giá 1 kết quả extract có 'đủ tốt' để dùng hay không. Nếu không,
    Reader sẽ fallback sang Jina AI Reader."""

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

            # Không retryable, hoặc đã hết lượt retry -> raise lỗi rõ ràng, không retry vô ích
            reason = STATUS_MESSAGES.get(resp.status_code)
            if reason:
                raise ExtractionError(f"{url} -> {reason}")
            raise ExtractionError(
                f"{url} -> HTTP {resp.status_code} {resp.reason_phrase} "
                f"(đã thử {attempt+1} lần)"
            )
        raise ExtractionError(f"Không fetch được {url} sau {self.max_retries+1} lần thử")  # pragma: no cover

    def _fetch_via_jina(self, url: str) -> Dict:
        """Fallback qua Jina AI Reader (https://jina.ai/reader). Jina tự fetch
        + render (kể cả JS/SPA) + convert markdown ở server của họ, nên có thể
        cứu được các case mà pipeline local (httpx + readability/trafilatura)
        không xử lý được (bot-block, SPA, encoding lạ...)."""
        jina_url = JINA_READER_BASE + url
        headers = {"Accept": "text/plain", "X-Return-Format": "markdown"}
        if self.jina_api_key:
            headers["Authorization"] = f"Bearer {self.jina_api_key}"

        resp = self.client.get(jina_url, headers=headers, timeout=max(self.timeout, 40))
        resp.raise_for_status()
        raw = resp.text

        # Jina reader mặc định trả về dạng:
        #   Title: ...
        #   URL Source: ...
        #   Markdown Content:
        #   <nội dung>
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
        """Fetch + extract, có 2 lớp fallback sang Jina AI Reader:
        1) Nếu pipeline local lỗi (network, HTTP status, không extract được gì).
        2) Nếu extract "thành công" nhưng QualityEvaluator đánh giá chất lượng kém.
        Nếu Jina cũng lỗi/kém hơn, trả về kết quả tốt nhất đang có kèm cảnh báo."""
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

        # Cả 2 đều không đạt -> trả kết quả gốc (thường có nhiều metadata hơn) kèm cảnh báo
        result["quality_warning"] = f"{reason} (Jina fallback cũng không tốt hơn: {jina_reason})"
        return result

    def _fetch_and_extract(self, url: str) -> Dict:
        response = self._get_with_retry(url)

        content_type = response.headers.get("content-type", "")
        if "html" not in content_type.lower():
            raise ExtractionError(
                f"Content-Type '{content_type}' không phải HTML cho {url} "
                f"(có thể là PDF/JSON/ảnh -> cần pipeline xử lý riêng, không dùng reader này)"
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

        if HAS_TRAFILATURA:
            traf_md = trafilatura.extract(
                html, url=url, output_format="markdown",
                include_links=True, include_images=True, favor_recall=True,
            )
            traf_md = self.clean(traf_md) if traf_md else ""
            candidates["trafilatura"] = traf_md
            self._log(f"trafilatura length = {len(traf_md)}")
        else:
            self._log("trafilatura chưa cài -> bỏ qua")

        if not any(candidates.values()):
            # Không candidate nào lấy được gì đáng kể -> khả năng cao trang cần JS render
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
        """Lấy thêm ngày cập nhật cuối / breadcrumb, hữu ích để trích dẫn nguồn
        trong report (vd: "theo tài liệu X, cập nhật ngày Y")."""
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
        """Điểm chất lượng = lượng plain-text thật (bỏ ký tự markdown syntax),
        trừ hao nhẹ nếu mật độ link cực cao (dấu hiệu menu/nav rác). Ngưỡng
        được nới lỏng so với bản trước vì tài liệu kỹ thuật thường có rất
        nhiều link tham chiếu chéo hợp lệ (glossary, API reference...)."""
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

        # Thử tất cả selector khớp, chọn cái có nhiều text nhất (không dừng ở match đầu tiên)
        best_container = None
        best_len = 0
        for tag, cls in MAIN_CONTENT_SELECTORS:
            found_list = soup.find_all(tag, class_=cls) if cls else soup.select(tag)
            for found in found_list:
                text_len = len(found.get_text(strip=True))
                if text_len > best_len:
                    best_len = text_len
                    best_container = found

        # Một số docs platform dùng id thay vì class
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
    """Batch fetch nhiều URL song song, có giới hạn concurrency + politeness delay,
    tái sử dụng logic extract của Reader (chạy trong thread pool vì BeautifulSoup/
    readability là CPU-bound, sync)."""

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
        results: List[Dict] = [None] * len(urls)  # type: ignore

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
                await asyncio.sleep(self.delay)  # tránh spam quá nhanh 1 domain
                results[i] = r

        await asyncio.gather(*(worker(i, u) for i, u in enumerate(urls)))
        return results


def main():
    parser = argparse.ArgumentParser(description="Extract nội dung web sang markdown")
    parser.add_argument("urls", nargs="*", help="URL cần extract")
    parser.add_argument("--file", help="File chứa danh sách URL (mỗi dòng 1 URL)")
    parser.add_argument("--out", help="Ghi kết quả (JSON) ra file thay vì stdout")
    parser.add_argument("--out-dir", help="Ghi mỗi kết quả thành 1 file .md riêng trong thư mục này")
    parser.add_argument("--concurrency", type=int, default=5)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--jina-api-key", default="jina_0ce9686c636a41b18ca29d0b9ee4012bgf56WT5xXc4xuyLxWitps4GXw41V",
        help="API key cho Jina Reader (tăng rate-limit khi fallback); mặc định đọc từ env JINA_API_KEY",
    )
    args = parser.parse_args()

    urls = list(args.urls)
    if args.file:
        urls += [l.strip() for l in Path(args.file).read_text().splitlines() if l.strip()]
    if not urls:
        urls = ["https://docs.python.org/3/tutorial/index.html"]  # default demo

    if len(urls) == 1:
        reader = Reader(debug=args.debug, jina_api_key=args.jina_api_key)
        try:
            results = [reader.fetch(urls[0])]
        except ExtractionError as exc:
            results = [{"url": urls[0], "error": str(exc)}]
        except Exception as exc:
            results = [{"url": urls[0], "error": f"Lỗi không mong đợi: {exc!r}"}]
        finally:
            reader.close()
    else:
        results = asyncio.run(
            AsyncReader(
                concurrency=args.concurrency, debug=args.debug, jina_api_key=args.jina_api_key
            ).fetch_all(urls)
        )

    if args.out_dir:
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        for i, r in enumerate(results):
            if "error" in r:
                print(f"[LỖI] {r['url']}: {r['error']}", file=sys.stderr)
                continue
            safe_name = re.sub(r"[^a-zA-Z0-9]+", "_", r["title"] or f"page_{i}")[:80]
            header_lines = [f"# {r['title']}", "", f"Source: {r['url']}"]
            if r.get("last_updated"):
                header_lines.append(f"Last updated: {r['last_updated']}")
            if r.get("breadcrumb"):
                header_lines.append(f"Path: {r['breadcrumb']}")
            (out_dir / f"{safe_name}.md").write_text(
                "\n".join(header_lines) + f"\n\n{r['markdown']}", encoding="utf-8"
            )
        print(f"Đã ghi {len(results)} file vào {out_dir}")
    elif args.out:
        Path(args.out).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Đã ghi kết quả vào {args.out}")
    else:
        for r in results:
            if "error" in r:
                print(f"[LỖI] {r['url']}: {r['error']}")
                continue
            print(r["title"])
            print(f"method_used={r['method_used']}  candidate_lengths={r['candidate_lengths']}")
            if r.get("quality_fallback_reason"):
                print(f"[Jina fallback được dùng vì]: {r['quality_fallback_reason']}")
            if r.get("quality_warning"):
                print(f"[CẢNH BÁO chất lượng]: {r['quality_warning']}")
            print(f"last_updated={r.get('last_updated')}  breadcrumb={r.get('breadcrumb')}")
            print(f"raw_html_length={r['raw_html_length']}  markdown_length={r['length']}")
            print("=" * 60)
            print(r["markdown"])
            print()


if __name__ == "__main__":
    main()