from pydantic import BaseModel
import requests
import pathlib
from bs4 import BeautifulSoup, Tag
import re
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator


BASE = pathlib.Path(__file__).parent
DATA = BASE / "data"
DOCS = BASE / "docs"
STASH = BASE / "stash"

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def fetch_article_links():
    url = "https://paulgraham.com/articles.html"
    response = requests.get(url)
    soup = BeautifulSoup(response.text, "html.parser")
    table = soup.select("table")[-2]
    return [
        (a.text.strip(), a["href"])
        for a in table.find_all("a", href=True)
        if a.text.strip() and a["href"].endswith(".html")
    ]


def has_date(font):
    for c in font.contents[:10]:
        if isinstance(c, Tag):
            if res := has_date(c):
                return res
        if not isinstance(c, str):
            continue
        match = re.match(r"\s*(\w+)\s(\d{4}).*$", c.strip())
        if c and bool(match):
            month = match.group(1)
            year = match.group(2)
            return (month, int(year))
    return None


def get_article_content(soup):
    for font in soup.select("table tr td font"):
        if date := has_date(font):
            return font, date
    return None, None


class Article(BaseModel):
    href: str
    title: str
    content: str
    date: datetime


def clean_html_content(content: str, base_url: str, article_href: str = None) -> str:
    """Clean and fix HTML content for RSS feed."""
    soup = BeautifulSoup(content, "html.parser")

    # Convert relative URLs to absolute
    for tag in soup.find_all(["a", "img"]):
        if tag.get("href"):
            if tag["href"].startswith("#"):
                # Convert anchor links to absolute URLs
                if article_href:
                    tag["href"] = f"{base_url}{article_href}{tag['href']}"
            elif not tag["href"].startswith(("http://", "https://")):
                tag["href"] = f"{base_url}{tag['href']}"
        if tag.get("src"):
            if not tag["src"].startswith(("http://", "https://")):
                tag["src"] = f"{base_url}{tag['src']}"

    # Remove problematic tags
    for tag in soup.find_all(["script", "xmp", "nobr"]):
        tag.decompose()

    # Remove non-standard tags
    for tag in soup.find_all(["xa", "nota", "nobr"]):
        tag.unwrap()

    return str(soup)


def fetch_article(href) -> Article:
    if (path := (STASH / href)).exists():
        with open(path, "r") as f:
            src = f.read()
    else:
        url = f"https://paulgraham.com/{href}"
        print(f"Fetching {url}")
        response = requests.get(url)
        src = response.text
        with open(path, "w") as f:
            f.write(src)
    soup = BeautifulSoup(src, "html.parser")
    title = soup.select_one("title").text.strip()
    content, (month, year) = get_article_content(soup)

    # Clean the content before creating Article, passing the article href
    cleaned_content = clean_html_content(str(content), "https://paulgraham.com/", href)

    return Article(
        href=href,
        title=title,
        content=cleaned_content,
        date=datetime(year, MONTHS.index(month) + 1, 1, tzinfo=timezone.utc),
    )


def get_article(href) -> Article:
    if (path := (DATA / f"{href}.json")).exists():
        with open(path, "r") as f:
            return Article.model_validate_json(f.read())
    else:
        article = fetch_article(href)
        with open(path, "w") as f:
            f.write(article.model_dump_json())
        return article


# Need to fix extraction for these
TODO_HREF = {"fix.html", "noop.html", "lwba.html", "progbot.html"}


def articles():
    links = fetch_article_links()
    for _, href in links:
        if href in TODO_HREF:
            continue
        yield get_article(href)


def generate_paged_feeds(page_size=30):
    """Generate paginated RSS feeds with stable date-based names following RFC 5005"""
    # Get all articles sorted from oldest to newest
    all_articles = sorted(list(articles()), key=lambda a: a.date)

    BASE_URL = "https://paulgraham.com/"
    FEED_BASE_URL = "https://enigma.github.io/pgrss/"

    # Group articles into pages of page_size
    pages = []
    for i in range(0, len(all_articles), page_size):
        page_articles = all_articles[i : i + page_size]
        pages.append(page_articles)

    # Generate feeds from oldest to newest
    for page_idx, page_articles in enumerate(pages):
        feedgen = FeedGenerator()

        # Determine feed filename based on the last (most recent) article in this page
        last_article_date = page_articles[-1].date
        is_most_recent_page = page_idx == len(pages) - 1

        if is_most_recent_page:
            # Most recent page uses rss.xml
            feed_filename = "rss.xml"
            feed_url = f"{FEED_BASE_URL}rss.xml"
        else:
            # Archive pages use date-based naming (YYYY-MM format)
            feed_filename = (
                f"rss-{last_article_date.year:04d}-{last_article_date.month:02d}.xml"
            )
            feed_url = f"{FEED_BASE_URL}{feed_filename}"

        feedgen.id(feed_url)
        feedgen.title("Paul Graham's Essays")
        feedgen.link(href=BASE_URL, rel="alternate")
        feedgen.language("en")
        feedgen.description("Paul Graham's Essays")

        # Self link
        feedgen.link(
            href=feed_url,
            rel="self",
            type="application/rss+xml",
        )

        # RFC 5005 pagination links
        # Link to first page (oldest)
        if page_idx > 0:
            first_page_date = pages[0][-1].date
            first_filename = (
                f"rss-{first_page_date.year:04d}-{first_page_date.month:02d}.xml"
            )
            feedgen.link(
                href=f"{FEED_BASE_URL}{first_filename}",
                rel="first",
                type="application/rss+xml",
            )

        # Link to previous page (older)
        if page_idx > 0:
            prev_page_date = pages[page_idx - 1][-1].date
            prev_filename = (
                f"rss-{prev_page_date.year:04d}-{prev_page_date.month:02d}.xml"
            )
            feedgen.link(
                href=f"{FEED_BASE_URL}{prev_filename}",
                rel="previous",
                type="application/rss+xml",
            )

        # Link to next page (newer)
        if page_idx < len(pages) - 1:
            if page_idx == len(pages) - 2:
                # Next page is the most recent
                next_filename = "rss.xml"
            else:
                next_page_date = pages[page_idx + 1][-1].date
                next_filename = (
                    f"rss-{next_page_date.year:04d}-{next_page_date.month:02d}.xml"
                )

            feedgen.link(
                href=f"{FEED_BASE_URL}{next_filename}",
                rel="next",
                type="application/rss+xml",
            )

        # Link to last page (most recent - always rss.xml)
        if not is_most_recent_page:
            feedgen.link(
                href=f"{FEED_BASE_URL}rss.xml",
                rel="last",
                type="application/rss+xml",
            )

        # Add articles for this page (already in chronological order)
        build_date = None
        for article in page_articles:
            build_date = max(build_date or article.date, article.date)
            entry = feedgen.add_entry()
            entry.title(article.title.strip())
            entry.id(f"{BASE_URL}/{article.href}")
            entry.guid(f"{BASE_URL}/{article.href}")

            # Clean content and ensure all URLs are absolute
            cleaned_content = clean_html_content(
                article.content, BASE_URL, article.href
            )
            entry.content(cleaned_content)

            # Clean description as well
            clean_description = clean_html_content(
                article.content[:500], BASE_URL, article.href
            )
            entry.description(clean_description)
            entry.pubDate(article.date)
            entry.link(href=f"{BASE_URL}/{article.href}")

        feedgen.lastBuildDate(build_date)

        # Generate both RSS and Atom formats
        feedgen.rss_file(DOCS / feed_filename, pretty=True)

        # Also generate Atom format which better supports RFC 5005
        atom_filename = feed_filename.replace(".xml", ".atom")
        feedgen.atom_file(DOCS / atom_filename, pretty=True)

        print(
            f"Generated {feed_filename} and {atom_filename} ({len(page_articles)} articles, ending {last_article_date.strftime('%Y-%m')})"
        )


def main():
    for dir in [DATA, STASH, DOCS]:
        dir.mkdir(parents=True, exist_ok=True)

    generate_paged_feeds()
    print("done.")


if __name__ == "__main__":
    main()
