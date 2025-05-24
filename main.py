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
            # print(">>>", type(c), str(c)[:200].replace('\n', ' '))
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


def clean_html_content(content: str, base_url: str) -> str:
    """Clean and fix HTML content for RSS feed."""
    soup = BeautifulSoup(content, "html.parser")

    # Convert relative URLs to absolute
    for tag in soup.find_all(["a", "img"]):
        if tag.get("href"):
            if not tag["href"].startswith(("http://", "https://")):
                tag["href"] = f"{base_url}{tag['href']}"
        if tag.get("src"):
            if not tag["src"].startswith(("http://", "https://")):
                tag["src"] = f"{base_url}{tag['src']}"

    # Remove problematic tags
    for tag in soup.find_all(["script", "xmp"]):
        tag.decompose()

    # Fix common HTML issues
    for tag in soup.find_all():
        # Fix hef attribute to href
        if tag.get("hef"):
            tag["href"] = tag["hef"]
            del tag["hef"]

        # Remove non-standard tags
        if tag.name in ["xa", "nota"]:
            tag.unwrap()

    # Clean up bad characters
    text = str(soup)
    text = text.replace("\x97", "—")  # Replace em dash
    text = text.replace("\x96", "–")  # Replace en dash

    return text


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

    # Clean the content before creating Article
    cleaned_content = clean_html_content(str(content), "https://paulgraham.com/")

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


def main():
    for dir in [DATA, STASH]:
        dir.mkdir(parents=True, exist_ok=True)
    feedgen = FeedGenerator()
    BASE_URL = "https://paulgraham.com/"
    feedgen.id(BASE_URL)
    feedgen.title("Paul Graham's Essays")
    feedgen.link(href=BASE_URL, rel="alternate")
    feedgen.language("en")
    feedgen.description("Paul Graham's Essays")
    for article in articles():
        entry = feedgen.add_entry()
        entry.title(article.title.strip())
        entry.id(f"{BASE_URL}/{article.href}")
        entry.guid(f"{BASE_URL}/{article.href}")
        entry.content(article.content)
        # Clean description as well
        clean_description = clean_html_content(article.content[:500], BASE_URL)
        entry.description(clean_description)
        entry.pubDate(article.date)
        entry.link(href=f"{BASE_URL}/{article.href}")
    feedgen.rss_file(DOCS / "rss.xml", pretty=True)
    print("done.")


if __name__ == "__main__":
    main()
