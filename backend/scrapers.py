"""JIP - Scrapers for Jaipur news sources."""
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime

import feedparser
import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DEFAULT_MAX_ARTICLES_PER_SOURCE = int(os.environ.get("MAX_ARTICLES_PER_SOURCE", "8"))

JAIPUR_URL_SCOPE_TERMS = (
    "jaipur-news",
    "/jaipur-news/",
    "/city/jaipur",
    "/local/rajasthan/jaipur",
    "/rajasthan/jaipur",
    "/jaipur/",
    "jaipur.",
    "jaipur-",
)

NON_JAIPUR_URL_TERMS = (
    "/delhi/",
    "/new-delhi/",
    "/delhi-ncr/",
    "/national/",
    "/india-news/",
    "/world-news/",
)

JAIPUR_TITLE_SCOPE_TERMS = (
    "jaipur",
    "\u091c\u092f\u092a\u0941\u0930",
    "pink city",
    "walled city",
    "amer",
    "amber",
    "mansarovar",
    "vaishali nagar",
    "malviya nagar",
    "tonk road",
    "civil lines",
    "c scheme",
    "sindhi camp",
    "bani park",
    "raja park",
    "sanganer",
    "sitapura",
    "pratap nagar",
    "durgapura",
    "vidyadhar nagar",
    "vidhyadhar nagar",
    "jhotwara",
    "murlipura",
    "jagatpura",
    "adarsh nagar",
    "chaksu",
    "chomu",
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def has_jaipur_url_scope(url: str = "") -> bool:
    haystack = (url or "").casefold()
    return any(term.casefold() in haystack for term in JAIPUR_URL_SCOPE_TERMS)


def has_non_jaipur_url_scope(url: str = "") -> bool:
    haystack = (url or "").casefold()
    return any(term.casefold() in haystack for term in NON_JAIPUR_URL_TERMS)


def has_jaipur_title_scope(title: str = "") -> bool:
    haystack = (title or "").casefold()
    return any(term.casefold() in haystack for term in JAIPUR_TITLE_SCOPE_TERMS)


def has_jaipur_scope(title: str = "", body: str = "", url: str = "") -> bool:
    """Return whether an article candidate should enter the Jaipur pipeline."""
    if has_non_jaipur_url_scope(url) and not has_jaipur_url_scope(url):
        return False
    if has_jaipur_url_scope(url):
        return True
    return has_jaipur_title_scope(title)


class Article:
    def __init__(self, source, title, body, url, published_at):
        self.source = source
        self.title = title
        self.body = body or ""
        self.url = url
        self.published_at = published_at or datetime.utcnow().isoformat()


def is_jaipur_article(article: Article) -> bool:
    return has_jaipur_scope(title=article.title, url=article.url)


class BaseScraper(ABC):
    source_name: str
    rss_url: str = ""
    max_articles: int = DEFAULT_MAX_ARTICLES_PER_SOURCE

    def scrape(self) -> list[Article]:
        articles = []
        if self.rss_url:
            articles = self._from_rss()
        if not articles:
            logger.info("[%s] RSS yielded nothing, falling back to HTML", self.source_name)
            articles = self._from_html()
        return self._scope_articles(articles)

    def _scope_articles(self, articles: list[Article]) -> list[Article]:
        scoped = [article for article in articles if is_jaipur_article(article)]
        dropped = len(articles) - len(scoped)
        if dropped:
            logger.info("[%s] skipped %d non-Jaipur articles", self.source_name, dropped)
        if len(scoped) > self.max_articles:
            logger.info("[%s] limiting Jaipur articles to %d", self.source_name, self.max_articles)
        return scoped[: self.max_articles]

    def _from_rss(self) -> list[Article]:
        try:
            feed = feedparser.parse(self.rss_url)
            results = []
            for entry in feed.entries[:20]:
                title = entry.get("title", "")
                url = entry.get("link", "")
                summary = BeautifulSoup(entry.get("summary", ""), "html.parser").get_text(" ", strip=True)
                if not has_jaipur_scope(title=title, url=url):
                    continue

                body = self._fetch_body(url)
                results.append(Article(
                    source=self.source_name,
                    title=title,
                    body=body or summary,
                    url=url,
                    published_at=entry.get("published", datetime.utcnow().isoformat()),
                ))
                if len(results) >= self.max_articles:
                    break
            logger.info("[%s] RSS fetched %d articles", self.source_name, len(results))
            return results
        except Exception as exc:
            logger.error("[%s] RSS error: %s", self.source_name, exc)
            return []

    def _fetch_body(self, url: str) -> str:
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()
            paragraphs = soup.find_all("p")
            text = " ".join(p.get_text(" ", strip=True) for p in paragraphs)
            return text[:8000]
        except Exception:
            return ""

    @abstractmethod
    def _from_html(self) -> list[Article]:
        ...


class TimesOfIndiaScraper(BaseScraper):
    source_name = "Times of India"
    rss_url = "https://timesofindia.indiatimes.com/rssfeeds/-2128839596.cms"
    fallback_url = "https://timesofindia.indiatimes.com/city/jaipur"

    def _from_html(self) -> list[Article]:
        try:
            resp = httpx.get(self.fallback_url, headers=HEADERS, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            articles = []
            for a_tag in soup.select("a[href*='/jaipur/']")[:20]:
                url = a_tag.get("href", "")
                if not url.startswith("http"):
                    url = "https://timesofindia.indiatimes.com" + url
                title = a_tag.get_text(strip=True)
                if len(title) < 15:
                    continue
                if not has_jaipur_scope(title=title, url=url):
                    continue
                body = self._fetch_body(url)
                articles.append(Article(
                    source=self.source_name,
                    title=title,
                    body=body,
                    url=url,
                    published_at=datetime.utcnow().isoformat(),
                ))
            logger.info("[Times of India] HTML scraped %d articles", len(articles))
            return articles
        except Exception as exc:
            logger.error("[Times of India] HTML scrape failed: %s", exc)
            return []


class RajasthanPatrikaScraper(BaseScraper):
    source_name = "Rajasthan Patrika"
    rss_url = "https://www.patrika.com/rss/jaipur-news.xml"
    fallback_url = "https://www.patrika.com/jaipur-news/"
    sitemap_urls = (
        "https://www.patrika.com/google-news-sitemap-v1.xml",
        "https://www.patrika.com/google-news-sitemap-v2.xml",
        "https://www.patrika.com/newurlsitemapindex.xml",
    )

    def scrape(self) -> list[Article]:
        articles = super().scrape()
        if articles:
            return articles
        logger.info("[Rajasthan Patrika] RSS/HTML yielded nothing, trying sitemaps")
        return self._scope_articles(self._from_sitemaps())

    def _from_sitemaps(self) -> list[Article]:
        articles = []
        seen = set()
        for sitemap_url in self.sitemap_urls:
            try:
                resp = httpx.get(sitemap_url, headers=HEADERS, timeout=15, follow_redirects=True)
                resp.raise_for_status()
                soup = BeautifulSoup(resp.text, "xml")
                for item in soup.find_all(["url", "sitemap"]):
                    loc = item.find("loc")
                    if not loc:
                        continue
                    url = loc.get_text(strip=True)
                    if url in seen:
                        continue
                    seen.add(url)

                    title_node = item.find("news:title") or item.find("title")
                    title = title_node.get_text(" ", strip=True) if title_node else ""
                    if not title:
                        title = url.rstrip("/").split("/")[-1].replace("-", " ").title()
                    if not has_jaipur_scope(title=title, url=url):
                        continue

                    body = self._fetch_body(url)
                    articles.append(Article(
                        source=self.source_name,
                        title=title,
                        body=body,
                        url=url,
                        published_at=datetime.utcnow().isoformat(),
                    ))
                    if len(articles) >= self.max_articles:
                        logger.info("[Rajasthan Patrika] Sitemap scraped %d articles", len(articles))
                        return articles
            except Exception as exc:
                logger.warning("[Rajasthan Patrika] Sitemap failed (%s): %s", sitemap_url, exc)
        logger.info("[Rajasthan Patrika] Sitemap scraped %d articles", len(articles))
        return articles

    def _from_html(self) -> list[Article]:
        try:
            resp = httpx.get(self.fallback_url, headers=HEADERS, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            articles = []
            for card in soup.select("article, .news-card, .story-card, h2 a, h3 a")[:15]:
                a_tag = card if card.name == "a" else card.find("a")
                if not a_tag or not a_tag.get("href"):
                    continue
                url = a_tag["href"]
                if not url.startswith("http"):
                    url = "https://www.patrika.com" + url
                title = a_tag.get_text(strip=True) or card.get_text(strip=True)
                if len(title) < 10:
                    continue
                if not has_jaipur_scope(title=title, url=url):
                    continue
                body = self._fetch_body(url)
                articles.append(Article(
                    source=self.source_name,
                    title=title,
                    body=body,
                    url=url,
                    published_at=datetime.utcnow().isoformat(),
                ))
            logger.info("[Rajasthan Patrika] HTML scraped %d articles", len(articles))
            return articles
        except Exception as exc:
            logger.error("[Rajasthan Patrika] HTML scrape failed: %s", exc)
            return []


class DainikBhaskarScraper(BaseScraper):
    source_name = "Dainik Bhaskar"
    rss_url = "https://www.bhaskar.com/rss-feed/1060/"
    fallback_url = "https://www.bhaskar.com/local/rajasthan/jaipur/"

    def _from_html(self) -> list[Article]:
        try:
            resp = httpx.get(self.fallback_url, headers=HEADERS, timeout=15, follow_redirects=True)
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")
            articles = []
            for a_tag in soup.select("a.db-card, a[href*='/news/'], h3 a, h2 a")[:20]:
                url = a_tag.get("href", "")
                if not url.startswith("http"):
                    url = "https://www.bhaskar.com" + url
                title = a_tag.get_text(strip=True)
                if len(title) < 10 or not url:
                    continue
                if not has_jaipur_scope(title=title, url=url):
                    continue
                body = self._fetch_body(url)
                articles.append(Article(
                    source=self.source_name,
                    title=title,
                    body=body,
                    url=url,
                    published_at=datetime.utcnow().isoformat(),
                ))
            logger.info("[Dainik Bhaskar] HTML scraped %d articles", len(articles))
            return articles
        except Exception as exc:
            logger.error("[Dainik Bhaskar] HTML scrape failed: %s", exc)
            return []


ALL_SCRAPERS = [RajasthanPatrikaScraper, TimesOfIndiaScraper, DainikBhaskarScraper]
