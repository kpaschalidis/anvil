import logging
import threading
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote_plus
import os
import time
import atexit

from scout.config import ProductHuntConfig
from scout.models import DocumentRef, Page, RawDocument, SearchTask, SourceEntity
from scout.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class ProductHuntError(Exception):
    pass


def _to_dt(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value).astimezone(timezone.utc)
    except Exception:
        return None


def _extract_slugs(hrefs: list[str], *, prefix: str) -> list[str]:
    slugs: list[str] = []
    seen: set[str] = set()
    for href in hrefs:
        if not isinstance(href, str) or not href:
            continue
        normalized = href
        if normalized.startswith("http"):
            if f"/{prefix}/" in normalized:
                normalized = f"/{prefix}/" + normalized.split(f"/{prefix}/", 1)[1]
        if not normalized.startswith(f"/{prefix}/"):
            continue
        slug = (
            normalized.split(f"/{prefix}/", 1)[1]
            .split("?", 1)[0]
            .split("#", 1)[0]
            .strip("/")
        )
        # Some links include nested paths like /products/<slug>/reviews
        # Normalize to the base slug.
        slug = slug.split("/", 1)[0].strip()
        if not slug:
            continue
        if slug not in seen:
            seen.add(slug)
            slugs.append(slug)
    return slugs


def _extract_post_slugs(hrefs: list[str]) -> list[str]:
    return _extract_slugs(hrefs, prefix="posts")


def _extract_product_slugs(hrefs: list[str]) -> list[str]:
    return _extract_slugs(hrefs, prefix="products")


class _PlaywrightThreadState(threading.local):
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None


class ProductHuntSource:
    name = "producthunt"
    _cleanup_registered: bool = False

    def __init__(self, config: ProductHuntConfig | None = None):
        self.config = config or ProductHuntConfig()
        self.rate_limiter = RateLimiter(
            requests_per_minute=self.config.rate_limit_per_minute,
            min_delay=self.config.request_delay_seconds,
        )
        self._tls = _PlaywrightThreadState()
        self._register_cleanup()

    def _register_cleanup(self) -> None:
        if ProductHuntSource._cleanup_registered:
            return
        ProductHuntSource._cleanup_registered = True

        def _cleanup() -> None:
            try:
                # Best-effort cleanup to avoid leaving Chrome/profile locks behind.
                if self._tls.context is not None:
                    try:
                        self._tls.context.close()
                    except Exception:
                        pass
                    self._tls.context = None
                if self._tls.browser is not None:
                    try:
                        self._tls.browser.close()
                    except Exception:
                        pass
                    self._tls.browser = None
                if self._tls.playwright is not None:
                    try:
                        self._tls.playwright.stop()
                    except Exception:
                        pass
                    self._tls.playwright = None
            except Exception:
                pass

        atexit.register(_cleanup)

    def discover(self, topic: str, limit: int = 10) -> list[SourceEntity]:
        return [
            SourceEntity(
                entity_id="producthunt:all",
                source=self.name,
                name="all",
                display_name="Product Hunt (Playwright scrape)",
                description="Scrape Product Hunt using Playwright (requires Playwright + chromium install)",
                metadata={"requires": ["playwright", "chromium"]},
            )
        ][:limit]

    def adapt_queries(self, queries: list[str], topic: str) -> list[SearchTask]:
        # Product Hunt scraping is relatively heavy; keep the search fanout small.
        queries = queries[:3]
        return [
            SearchTask(
                source=self.name,
                source_entity="all",
                mode="search",
                query=q,
            )
            for q in queries
        ]

    def _get_browser(self):
        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # pragma: no cover
            raise ProductHuntError(
                "Playwright is required for the Product Hunt source. "
                'Install with: `uv sync --extra fetch` (or `uv pip install -e ".[fetch]"`), '
                "then run: `uv run playwright install chromium`."
            ) from e

        if self._tls.playwright is None:
            self._tls.playwright = sync_playwright().start()
        if self._tls.browser is None:
            self._tls.browser = self._tls.playwright.chromium.launch(
                headless=self.config.headless,
                channel=self.config.channel,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--window-position=0,0",
                    "--window-size=1280,800",
                ],
            )
        return self._tls.browser

    def _get_context(self):
        if self._tls.context is not None:
            return self._tls.context
        if not self.config.headless:
            # Persistent context helps keep Cloudflare clearance cookies across tasks/runs.
            if self._tls.playwright is None:
                from playwright.sync_api import sync_playwright

                self._tls.playwright = sync_playwright().start()
            try:
                self._tls.context = self._tls.playwright.chromium.launch_persistent_context(
                    user_data_dir=self.config.user_data_dir,
                    headless=False,
                    channel=self.config.channel,
                    locale="en-US",
                    viewport=None,
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                    args=[
                        "--disable-blink-features=AutomationControlled",
                        "--window-position=0,0",
                        "--window-size=1280,800",
                    ],
                )
            except Exception as e:
                msg = str(e).lower()
                if (
                    "processsingleton" in msg
                    or "profile is already in use" in msg
                    or "singletonlock" in msg
                ):
                    fallback = (
                        f"{self.config.user_data_dir}_{os.getpid()}_{int(time.time())}"
                    )
                    logger.warning(
                        "Product Hunt profile directory appears locked/in-use. "
                        f"Retrying with a fresh profile dir: {fallback}"
                    )
                    self._tls.context = self._tls.playwright.chromium.launch_persistent_context(
                        user_data_dir=fallback,
                        headless=False,
                        channel=self.config.channel,
                        locale="en-US",
                        viewport=None,
                        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        args=[
                            "--disable-blink-features=AutomationControlled",
                            "--window-position=0,0",
                            "--window-size=1280,800",
                        ],
                    )
                else:
                    raise
        else:
            browser = self._get_browser()
            self._tls.context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="en-US",
            )
        return self._tls.context

    def _looks_like_cloudflare_block(self, *, title: str, html: str) -> bool:
        t = (title or "").strip().lower()
        if "just a moment" in t or "attention required" in t:
            return True
        h = (html or "").lower()
        if 'id="cf-challenge-running"' in h or "id='cf-challenge-running'" in h:
            return True
        if '<div class="cf-' in h and "challenge" in h:
            return True
        return False

    def _handle_cloudflare(self, page) -> None:
        if self.config.headless:
            raise ProductHuntError(
                "Product Hunt blocked automated browsing (Cloudflare). "
                "Try headful mode: set `SCOUT_PRODUCTHUNT_HEADLESS=0`."
            )

        try:
            page.bring_to_front()
        except Exception:
            pass

        logger.warning(
            "Product Hunt Cloudflare challenge detected. "
            "A browser window should be open — complete the challenge in that window, then return here."
        )

        try:
            page.wait_for_function(
                """
                () => {
                  const t = (document.title || '').toLowerCase();
                  if (t.includes('just a moment') || t.includes('attention required')) return false;
                  const h = (document.documentElement?.innerHTML || '').toLowerCase();
                  if (h.includes('cf-challenge') || h.includes('challenge-platform') || h.includes('cloudflare')) return false;
                  return true;
                }
                """,
                timeout=180_000,
            )
        except Exception as e:
            raise ProductHuntError(
                "Cloudflare challenge not completed in time. "
                "Re-run and complete it in the opened browser window."
            ) from e

    def search(self, task: SearchTask) -> Page[DocumentRef]:
        if task.mode != "search":
            raise ProductHuntError(f"Unknown search mode: {task.mode}")

        query = (task.query or "").strip()
        if not query:
            return Page(items=[], exhausted=True)

        url = f"https://www.producthunt.com/search?q={quote_plus(query)}"

        self.rate_limiter.wait()
        context = self._get_context()
        page = context.new_page()
        title_str = ""
        try:
            page.set_default_navigation_timeout(self.config.navigation_timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(750)
            title_str = page.title() or ""
            if self._looks_like_cloudflare_block(title=title_str, html=page.content()):
                self._handle_cloudflare(page)
            try:
                page.wait_for_function(
                    """
                    () => {
                      const main = document.querySelector('main');
                      if (!main) return false;
                      // Check for new button-based search results
                      const buttons = main.querySelectorAll("button[data-test*='spotlight-result-product-'], button[data-test*='spotlight-result-post-']");
                      if (buttons.length > 0) return true;
                      // Fallback to old anchor-based results
                      const links = main.querySelectorAll("a[href^='/products/'],a[href^='/posts/'],a[href*='producthunt.com/products/'],a[href*='producthunt.com/posts/']");
                      if (links.length > 0) return true;
                      const text = (main.innerText || '').toLowerCase();
                      return text.includes('no results');
                    }
                    """,
                    timeout=min(
                        15_000, max(3_000, int(self.config.navigation_timeout_ms))
                    ),
                )
            except Exception:
                pass

            product_slugs: list[str] = []
            post_slugs: list[str] = []

            product_ids = page.eval_on_selector_all(
                "main button[data-test*='spotlight-result-product-']",
                "els => els.map(e => e.getAttribute('data-test'))",
            )
            for data_test in product_ids or []:
                if data_test and "spotlight-result-product-" in data_test:
                    product_id = data_test.replace("spotlight-result-product-", "")
                    if product_id:
                        product_slugs.append(product_id)

            post_ids = page.eval_on_selector_all(
                "main button[data-test*='spotlight-result-post-']",
                "els => els.map(e => e.getAttribute('data-test'))",
            )
            for data_test in post_ids or []:
                if data_test and "spotlight-result-post-" in data_test:
                    post_id = data_test.replace("spotlight-result-post-", "")
                    if post_id:
                        post_slugs.append(post_id)

            if not product_slugs and not post_slugs:
                post_hrefs = page.eval_on_selector_all(
                    "main a[href^='/posts/'], main a[href*='producthunt.com/posts/']",
                    "els => els.map(e => e.getAttribute('href'))",
                )
                product_hrefs = page.eval_on_selector_all(
                    "main a[href^='/products/'], main a[href*='producthunt.com/products/']",
                    "els => els.map(e => e.getAttribute('href'))",
                )
                product_slugs = _extract_product_slugs(product_hrefs or [])
                post_slugs = _extract_post_slugs(post_hrefs or [])
        except Exception as e:
            logger.warning(f"Failed to scrape Product Hunt search results: {e}")
            return Page(items=[], exhausted=True)
        finally:
            try:
                page.close()
            except Exception:
                pass

        if not product_slugs and not post_slugs:
            logger.warning(
                "Product Hunt search returned 0 extractable links. "
                f"title={title_str!r} query={query!r}"
            )

        refs: list[DocumentRef] = []
        # Prefer product pages (search UI usually links to /products/*).
        combined: list[tuple[str, str]] = [("product", s) for s in product_slugs] + [
            ("post", s) for s in post_slugs
        ]
        combined = combined[: self.config.results_per_search]
        for rank, (kind, slug) in enumerate(combined):
            refs.append(
                DocumentRef(
                    ref_id=f"producthunt:{kind}:{slug}",
                    ref_type=kind,
                    source=self.name,
                    source_entity="all",
                    discovered_from_task_id=task.task_id,
                    rank=rank,
                    preview=slug,
                )
            )

        return Page(items=refs, exhausted=True, estimated_total=len(refs))

    def fetch(self, ref: DocumentRef, deep_comments: str = "auto") -> RawDocument:
        parts = ref.ref_id.split(":")
        if len(parts) < 3:
            raise ProductHuntError(f"Invalid ref_id: {ref.ref_id}")
        _, kind, slug = parts[0], parts[1], ":".join(parts[2:])
        if kind not in ("post", "product") or not slug:
            raise ProductHuntError(f"Invalid ref_id: {ref.ref_id}")

        if kind == "product":
            url = f"https://www.producthunt.com/products/{slug}"
        else:
            url = f"https://www.producthunt.com/posts/{slug}"

        self.rate_limiter.wait()
        context = self._get_context()
        page = context.new_page()
        try:
            page.set_default_navigation_timeout(self.config.navigation_timeout_ms)
            page.goto(url, wait_until="domcontentloaded")
            page.wait_for_timeout(750)
            if self._looks_like_cloudflare_block(
                title=page.title(), html=page.content()
            ):
                self._handle_cloudflare(page)

            title = page.title() or slug

            published_at = None
            meta_el = page.query_selector('meta[property="article:published_time"]')
            if meta_el:
                published_meta = meta_el.get_attribute("content")
                if published_meta:
                    published_at = _to_dt(published_meta)

            raw_text = (page.inner_text("body") or "").strip()
            if len(raw_text) > 200_000:
                raw_text = raw_text[:200_000] + "\n\n[truncated]"

            html = page.content()
            if len(html) > 500_000:
                html = html[:500_000] + "\n<!-- truncated -->"
        finally:
            try:
                page.close()
            except Exception:
                pass

        return RawDocument(
            doc_id=f"producthunt:{kind}:{slug}",
            source=self.name,
            source_entity="all",
            url=url,
            permalink=url,
            published_at=published_at,
            title=title,
            raw_text=raw_text,
            author=None,
            score=None,
            num_comments=None,
            metadata={"producthunt": {"kind": kind, "slug": slug, "html": html}},
        )
