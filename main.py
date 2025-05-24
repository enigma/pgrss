from pydantic import BaseModel
import requests
import pathlib
from bs4 import BeautifulSoup, Tag
import re
from datetime import datetime, timezone
from feedgen.feed import FeedGenerator


BASE = pathlib.Path(__file__).parent
DATA = BASE / "data"
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
    return Article(
        href=href,
        title=title,
        content=str(content),
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
    feedgen.link(href=BASE_URL, rel="self")
    feedgen.language("en")
    feedgen.description("Paul Graham's Essays")
    for article in articles():
        entry = feedgen.add_entry()
        entry.title(article.title.strip())
        entry.content(article.content)
        entry.description(article.content[:500])
        entry.pubDate(article.date)
        entry.link(href=f"{BASE_URL}/{article.href}")
    feedgen.rss_file(DATA / "rss.xml", pretty=True)
    print("done.")


if __name__ == "__main__":
    main()
