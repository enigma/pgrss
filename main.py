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


def clean_html_content(
    content: str | Tag, base_url: str, article_href: str = None
) -> str:
    """Clean and fix HTML content for RSS feed."""
    # If content is already a BeautifulSoup Tag, use it directly
    if isinstance(content, Tag):
        soup = BeautifulSoup(str(content), "html.parser")
    else:
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
    for tag in soup.find_all(["script", "xmp", "ximg", "ax"]):
        tag.decompose()

    # Fix common HTML issues
    for tag in soup.find_all():
        # Fix hef attribute to href
        if tag.get("hef"):
            tag["href"] = tag["hef"]
            del tag["hef"]

        # Remove non-standard tags
        if tag.name in ["xa", "nota", "ximg", "ax"]:
            tag.unwrap()

    # Convert special characters to HTML entities
    for tag in soup.find_all(text=True):
        if isinstance(tag, str):
            # Replace special characters with HTML entities
            new_text = tag.replace("–", "&ndash;")
            new_text = new_text.replace("—", "&mdash;")
            new_text = new_text.replace("'", "&apos;")
            new_text = new_text.replace('"', "&quot;")
            new_text = new_text.replace("…", "&hellip;")
            new_text = new_text.replace("?", "&mdash;")  # Replace em dash placeholder
            tag.replace_with(new_text)

    # Use BeautifulSoup's encode/decode to handle HTML entities properly
    return soup.encode("ascii", "xmlcharrefreplace").decode("ascii")


def fetch_article(href) -> Article:
    if (path := (STASH / href)).exists():
        with open(path, "r", encoding="utf-8") as f:
            src = f.read()
    else:
        url = f"https://paulgraham.com/{href}"
        print(f"Fetching {url}")
        response = requests.get(url)
        response.encoding = "utf-8"
        src = response.text
        with open(path, "w", encoding="utf-8") as f:
            f.write(src)

    soup = BeautifulSoup(src, "html.parser")
    title = soup.select_one("title").text.strip()
    content, (month, year) = get_article_content(soup)

    # Clean the content before creating Article
    cleaned_content = clean_html_content(content, "https://paulgraham.com/", href)

    return Article(
        href=href,
        title=title,
        content=cleaned_content,
        date=datetime(year, MONTHS.index(month) + 1, 1, tzinfo=timezone.utc),
    )


def get_article(href) -> Article:
    if (path := (DATA / f"{href}.json")).exists():
        with open(path, "r", encoding="utf-8") as f:  # Explicitly use UTF-8
            return Article.model_validate_json(f.read())
    else:
        article = fetch_article(href)
        with open(path, "w", encoding="utf-8") as f:  # Explicitly use UTF-8
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


def main():
    for dir in [DATA, STASH]:
        dir.mkdir(parents=True, exist_ok=True)
    feedgen = FeedGenerator()
    BASE_URL = "https://paulgraham.com/"
    FEED_URL = "https://enigma.github.io/pgrss/rss.xml"

    feedgen.id(FEED_URL)  # Use FEED_URL as the feed ID
    feedgen.title("Paul Graham's Essays")
    feedgen.link(href=BASE_URL, rel="alternate")
    feedgen.language("en")
    feedgen.description("Paul Graham's Essays")

    feedgen.link(
        href=FEED_URL,
        rel="self",
        type="application/rss+xml",
    )

    for n, article in enumerate(articles()):
        entry = feedgen.add_entry()
        entry.title(article.title.strip())
        entry.id(f"{BASE_URL}/{article.href}")
        entry.guid(f"{BASE_URL}/{article.href}")

        # Clean content and ensure all URLs are absolute
        cleaned_content = clean_html_content(article.content, BASE_URL, article.href)
        entry.content(cleaned_content)

        # Clean description as well, passing the article href
        clean_description = clean_html_content(
            article.content[:500], BASE_URL, article.href
        )
        entry.description(clean_description)
        entry.pubDate(article.date)
        entry.link(href=f"{BASE_URL}/{article.href}")

    feedgen.rss_file(DOCS / "rss.xml", pretty=True)
    print("done.")


if __name__ == "__main__":
    main()
