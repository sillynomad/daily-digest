#!/usr/bin/env python3
"""
Daily Multilingual News Digest
Fetches RSS feeds, summarizes with Claude, sends via email.
"""

import os
import re
import json
import smtplib
import feedparser
import anthropic
import urllib.request
import urllib.parse
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── RSS Feed Sources ──────────────────────────────────────────────────────────

FEEDS = {
    "general": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://feeds.reuters.com/reuters/worldNews",
        "https://www.theguardian.com/world/rss",
        "https://feeds.npr.org/1004/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
    ],
    "tech_asia": [
        "https://www.techinasia.com/feed",
        "https://kr-asia.com/feed",
        "https://e27.co/feed/",
    ],
    "la_liga_opinion": [
        "https://e00-marca.uecdn.es/rss/opinion.xml",
        "https://www.sport.es/rss/opinion.xml",
        "https://www.mundodeportivo.com/rss/opinion.xml",
        "https://feeds.as.com/mrss-s/pages/as/site/as.com/opinion/",
    ],
    "singapore": [
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416",
        "https://www.straitstimes.com/news/singapore/rss.xml",
    ],
    "quirky": [
        "https://www.odditycentral.com/feed",
        "https://feeds.feedburner.com/universetoday/feer",
        "https://www.mentalfloss.com/feeds/all",
        "https://feeds.bbci.co.uk/news/magazine/rss.xml",
        "https://www.atlasobscura.com/feeds/latest",
        "https://feeds.feedburner.com/ColosseumFeed",  # Ripley's Believe It or Not
    ],
}

MAX_ARTICLES = 8  # per category, before Claude selects the best

# Your GitHub Pages URL — update with your actual GitHub username
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL", "https://sillynomad.github.io/daily-digest/")


def ruby_to_parens(html: str) -> str:
    """Convert <ruby>漢字<rt>かんじ</rt></ruby> to 漢字(かんじ) for email clients."""
    return re.sub(r'<ruby>(.*?)<rt>(.*?)</rt></ruby>', r'\1(\2)', html, flags=re.DOTALL)

def ruby_strip(html: str) -> str:
    """Remove ruby annotations entirely for email — keep only base characters, drop readings."""
    html = re.sub(r'<rt>.*?</rt>', '', html, flags=re.DOTALL)
    html = re.sub(r'</?ruby[^>]*>', '', html)
    return html


# ── Feed Fetching ─────────────────────────────────────────────────────────────

def fetch_articles(urls: list[str], limit: int = MAX_ARTICLES) -> list[dict]:
    articles = []
    for url in urls:
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:limit]:
                articles.append({
                    "title": entry.get("title", ""),
                    "summary": entry.get("summary", entry.get("description", ""))[:600],
                    "link": entry.get("link", ""),
                    "source": feed.feed.get("title", url),
                })
        except Exception as e:
            print(f"Warning: could not fetch {url}: {e}")
    return articles[:limit]


def articles_to_text(articles: list[dict]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(f"{i}. [{a['source']}] {a['title']}\n   {a['summary']}\n   URL: {a['link']}")
    return "\n\n".join(lines)


# ── Claude Calls ──────────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-sonnet-4-20250514"


def claude(prompt: str, system: str = "") -> str:
    kwargs = {"model": MODEL, "max_tokens": 1500, "messages": [{"role": "user", "content": prompt}]}
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    return msg.content[0].text.strip()


def build_skim(articles: list[dict]) -> tuple[str, str]:
    raw = articles_to_text(articles)
    result = claude(
        f"Here are today's top news articles:\n\n{raw}\n\n"
        "Write a 5-story global news summary in the style of The Daily Skimm — punchy, witty, conversational. "
        "For each story output the following HTML structure:\n"
        "<div class='skim-item'>\n"
        "  <strong>Bold headline phrase</strong>\n"
        "  <p class='skim-body'>2-3 sentences: first state what happened, then give 1-2 sentences of essential background "
        "context explaining WHY it's happening — e.g. what caused it, what led up to it, why now. "
        "Never leave the reader asking 'but why?'.</p>\n"
        "  <p class='skim-analysis'><em>What This Means:</em> 2-3 sentence analytical paragraph on broader significance or implications.</p>\n"
        "  <p class='skim-sources'>Read more: <a href='URL1'>Source Name 1</a> · <a href='URL2'>Source Name 2</a></p>\n"
        "</div>\n"
        "After all 5 stories, add a line starting with 'TITLES_USED:' followed by a pipe-separated list of the "
        "original article titles you selected (e.g. TITLES_USED: Title one|Title two|Title three|Title four|Title five). "
        "Use the article URLs provided as the source links. Return only the HTML and the TITLES_USED line.",
        system="You are a witty, analytically sharp news summarizer in the style of The Daily Skimm meets The Economist."
    )
    # Split out the titles line from the HTML
    if "TITLES_USED:" in result:
        html_part, titles_part = result.rsplit("TITLES_USED:", 1)
        used_titles = titles_part.strip()
    else:
        html_part = result
        used_titles = ""
    return html_part.strip(), used_titles


def build_tech_asia(articles: list[dict]) -> str:
    raw = articles_to_text(articles)
    return claude(
        f"Here are tech news articles from Asia:\n\n{raw}\n\n"
        "Pick the 3 most interesting and write a short digest. "
        "For each article output this exact HTML structure:\n"
        "<div class='article-card'>\n"
        "  <div class='article-source'>Source Name</div>\n"
        "  <h4><a href='URL'>Article title here</a></h4>\n"
        "  <p>2 sentences explaining why it matters.</p>\n"
        "</div>\n"
        "Use the source name from the article metadata. Return only the HTML.",
        system="You are a sharp tech journalist covering Asia's startup and tech ecosystem."
    )


def build_laliga_opinion(articles: list[dict]) -> str:
    raw = articles_to_text(articles)
    return claude(
        f"Aquí hay artículos de opinión sobre fútbol español de Marca, Sport, Mundo Deportivo y As:\n\n{raw}\n\n"
        "Selecciona las 3 piezas de opinión más interesantes y para cada una genera esta estructura HTML exacta:\n"
        "<div class='article-card'>\n"
        "  <div class='article-source'>Nombre del medio</div>\n"
        "  <h4><a href='URL'>Título del artículo</a></h4>\n"
        "  <p>2-3 frases que capturen el argumento principal del columnista.</p>\n"
        "</div>\n"
        "Devuelve solo el HTML.",
        system="Eres un periodista deportivo español especializado en análisis y opinión sobre La Liga."
    )


def build_singapore(articles: list[dict]) -> str:
    raw = articles_to_text(articles)
    return claude(
        f"Here are Singapore local news articles:\n\n{raw}\n\n"
        "Pick the 3 most relevant and write a short local news digest. "
        "For each article output this exact HTML structure:\n"
        "<div class='article-card'>\n"
        "  <div class='article-source'>Source Name</div>\n"
        "  <h4><a href='URL'>Article title here</a></h4>\n"
        "  <p>2 sentences of context.</p>\n"
        "</div>\n"
        "Return only the HTML.",
        system="You are a local Singapore news correspondent writing for an expat-friendly morning briefing."
    )


def build_language_corner(articles: list[dict], already_covered: list[dict] = None) -> tuple:
    raw = articles_to_text(articles)
    excluded = "\n".join(f"- {a['title']}" for a in (already_covered or []))
    exclusion_note = (
        f"\n\nIMPORTANT: The reader has already seen these stories in today's World News section — "
        f"do NOT pick any of these or anything similar:\n{excluded}"
        if excluded else ""
    )

    # Step 1: pick 3 fun/quirky stories not already covered
    chosen = claude(
        f"Here are fun and quirky world news articles:\n\n{raw}{exclusion_note}\n\n"
        "Pick exactly 3 of the most fun, playful, or quirky stories — nothing tragic or political, "
        "and nothing already covered in today's main news section. "
        "Return ONLY a JSON array with objects: [{\"title\": ..., \"summary\": ..., \"link\": ...}]. "
        "No markdown fences.",
        system="You curate fun, lighthearted news stories for language learners."
    )

    try:
        stories = json.loads(chosen)[:3]
    except Exception:
        # fallback: use first 3 articles
        stories = articles[:3]

    s1 = f"Title: {stories[0]['title']}\nSummary: {stories[0].get('summary','')}\nURL: {stories[0].get('link','')}"
    s2 = f"Title: {stories[1]['title']}\nSummary: {stories[1].get('summary','')}\nURL: {stories[1].get('link','')}"
    s3 = f"Title: {stories[2]['title']}\nSummary: {stories[2].get('summary','')}\nURL: {stories[2].get('link','')}"

    # French — fluent level
    fr = claude(
        f"Rewrite this fun news story in natural, fluent French (like a native journalist would write it). "
        f"Story:\n{s1}\n\n"
        "Format as HTML: <h4> title in French, then exactly 5 paragraphs — develop the story fully, "
        "add colour, context, and a touch of wit. No vocabulary glossary needed.",
        system="You write natural, fluent French for an advanced French language learner."
    )

    # Japanese — N2 (ruby tags for HTML; email gets auto-converted to parens)
    ja = claude(
        f"Rewrite this fun news story in Japanese at JLPT N2 level. "
        f"Story:\n{s2}\n\n"
        "Rules: N2-appropriate grammar, no N1 expressions. "
        "Wrap EVERY kanji or kanji compound in ruby tags with furigana, "
        "e.g. <ruby>食事<rt>しょくじ</rt></ruby>、<ruby>確認<rt>かくにん</rt></ruby>. "
        "After the article, add a <ul> vocab glossary of 5 key words: "
        "<li><ruby>単語<rt>reading</rt></ruby> — English meaning</li>. "
        "Format the whole thing as HTML with <p> tags for paragraphs.",
        system="You are a Japanese language teacher writing N2-level news for learners."
    )

    # Mandarin — A2 (ruby tags for HTML; email gets auto-converted to parens)
    zh = claude(
        f"Rewrite this fun news story in Mandarin Chinese at HSK 2-3 (A2) level. "
        f"Story:\n{s3}\n\n"
        "Rules: very simple short sentences (max 12 characters each). "
        "Wrap EVERY character or word in ruby tags with pinyin, "
        "e.g. <ruby>我<rt>wǒ</rt></ruby><ruby>是<rt>shì</rt></ruby><ruby>学生<rt>xuésheng</rt></ruby>。 "
        "After the article, add a <ul> glossary of 5 key words: "
        "<li><ruby>词<rt>pīnyīn</rt></ruby> — English meaning</li>. "
        "Format the whole thing as HTML with <p> tags for paragraphs.",
        system="You are a Mandarin teacher writing HSK A2-level news for beginners."
    )

    return fr, ja, zh


# ── Quote / Photo / Poem ──────────────────────────────────────────────────────

def build_quote() -> str:
    today = datetime.now().strftime("%B %d")
    result = claude(
        f"Today is {today}. Choose one memorable, thought-provoking quote — it can be from any era, "
        "any field (philosophy, science, literature, sport, etc.). "
        "Avoid overused clichés like 'Be the change' or 'Carpe diem'. Aim for something that surprises. "
        "Return ONLY a JSON object with keys: quote, author, author_search_url (a Google search URL for the author). "
        "No markdown fences.",
        system="You are a thoughtful curator of memorable quotations."
    )
    try:
        data = json.loads(result)
        q = data.get("quote", "")
        a = data.get("author", "")
        url = data.get("author_search_url", f"https://www.google.com/search?q={a.replace(' ', '+')}")
        return f"""<blockquote class="qotd">
  <p class="qotd-text">"{q}"</p>
  <cite>— <a href="{url}" target="_blank">{a}</a></cite>
</blockquote>"""
    except Exception:
        return ""


def build_photo_of_day() -> str:
    """Fetch Wikimedia Commons Picture of the Day — no API key required."""
    try:
        date_str = datetime.now().strftime("%Y-%m-%d")

        # Use the FeaturedFeed API which is more reliable than parsing templates
        feed_url = (
            "https://en.wikipedia.org/w/api.php"
            "?action=featuredfeed&feed=potd&feedformat=atom&format=json"
        )
        # Actually use the direct Commons API for today's POTD image
        api_url = (
            f"https://commons.wikimedia.org/w/api.php?action=query"
            f"&generator=images&titles=Template:Potd/{date_str}"
            f"&prop=imageinfo&iiprop=url|extmetadata&iiurlwidth=1200&format=json"
        )
        req = urllib.request.Request(api_url, headers={"User-Agent": "DailyDigestBot/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())

        pages = data.get("query", {}).get("pages", {})
        if not pages:
            raise ValueError("No images found in POTD template")

        # Get the first image page
        img_page = next(iter(pages.values()))
        info = img_page.get("imageinfo", [{}])[0]
        img_url  = info.get("thumburl") or info.get("url", "")
        page_url = info.get("descriptionurl", "https://commons.wikimedia.org/wiki/Commons:Picture_of_the_day")
        meta     = info.get("extmetadata", {})
        title    = re.sub(r'<[^>]+>', '', meta.get("ObjectName", {}).get("value", img_page.get("title", "Picture of the Day").replace("File:", "").rsplit(".", 1)[0]))
        desc_raw = meta.get("ImageDescription", {}).get("value", "")
        desc     = re.sub(r'<[^>]+>', '', desc_raw)[:280].strip()
        if desc:
            desc += "…"
        credit   = re.sub(r'<[^>]+>', '', meta.get("Artist", {}).get("value", "Wikimedia Commons")).strip()

        if not img_url:
            raise ValueError("No image URL found")

        return f"""<div class="potd">
  <a href="{page_url}" target="_blank">
    <img src="{img_url}" alt="{title}" style="width:100%;border-radius:6px;display:block;">
  </a>
  <p class="potd-title">{title}</p>
  {"" if not desc else f'<p class="potd-caption">{desc}</p>'}
  <p class="potd-credit">📷 {credit} · <a href="{page_url}" target="_blank">Wikimedia Commons</a></p>
</div>"""

    except Exception as e:
        print(f"Warning: could not fetch Wikimedia POTD: {e}")
        return ""


def build_poem_of_day() -> str:
    FALLBACK_POEMS = [
        {"title": "The Road Not Taken", "author": "Robert Frost",
         "lines": ["Two roads diverged in a yellow wood,", "And sorry I could not travel both",
                   "And be one traveler, long I stood", "And looked down one as far as I could",
                   "To where it bent in the undergrowth;", "", "Then took the other, as just as fair,",
                   "And having perhaps the better claim,", "Because it was grassy and wanted wear;",
                   "Though as for that the passing there", "Had worn them really about the same,"]},
        {"title": "i carry your heart with me", "author": "E.E. Cummings",
         "lines": ["i carry your heart with me(i carry it in", "my heart)i am never without it(anywhere",
                   "i go you go,my dear;and whatever is done", "by only me is your doing,my darling)",
                   "", "i fear no fate(for you are my fate,my sweet)i want", "no world(for beautiful you are my world,my true)",
                   "and it's you are whatever a moon has always meant", "and whatever a sun will always sing is you"]},
        {"title": "Still I Rise", "author": "Maya Angelou",
         "lines": ["You may write me down in history", "With your bitter, twisted lies,",
                   "You may trod me in the very dirt", "But still, like dust, I'll rise.", "",
                   "Does my sassiness upset you?", "Why are you beset with gloom?",
                   "'Cause I walk like I've got oil wells", "Pumping in my living room."]},
    ]
    try:
        url = "https://poetrydb.org/random/1"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
        # PoetryDB returns a list or sometimes a dict with an error key
        if isinstance(data, list) and len(data) > 0:
            poem = data[0]
        elif isinstance(data, dict) and "lines" in data:
            poem = data
        else:
            raise ValueError("Unexpected PoetryDB response")
        title  = poem.get("title", "Untitled")
        author = poem.get("author", "Unknown")
        lines  = poem.get("lines", [])
        if not lines:
            raise ValueError("Empty poem")
    except Exception as e:
        print(f"Warning: PoetryDB failed ({e}), using fallback poem")
        import random
        poem   = random.choice(FALLBACK_POEMS)
        title  = poem["title"]
        author = poem["author"]
        lines  = poem["lines"]

    display_lines = lines[:20]
    truncated = len(lines) > 20
    lines_html = "<br>\n".join(
        l if l.strip() else "<br>"
        for l in display_lines
    )
    more = '<p class="poem-more">… <a href="https://poetrydb.org" target="_blank">read full poem</a></p>' if truncated else ""
    search_url = f"https://www.google.com/search?q={urllib.parse.quote(author)}+poet"
    return f"""<div class="poem">
  <p class="poem-title">{title}</p>
  <p class="poem-author">by <a href="{search_url}" target="_blank">{author}</a></p>
  <div class="poem-body">{lines_html}</div>
  {more}
</div>"""


# ── Email Builder ─────────────────────────────────────────────────────────────

def build_html(skim, tech, laliga, sg, fr, ja, zh, quote="", photo="", poem="", web_url="") -> str:
    today = datetime.now().strftime("%A, %d %B %Y")
    browser_button = (
        f'<div class="view-browser"><a href="{web_url}" target="_blank">🌐 Read in Browser</a></div>'
        if web_url else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ font-family: Georgia, serif; background: #f9f6f1; margin: 0; padding: 0; color: #1a1a1a; }}
  .wrapper {{ max-width: 640px; margin: 0 auto; background: #ffffff; }}
  .header {{ background: #1a1a2e; color: white; padding: 28px 32px; }}
  .header h1 {{ margin: 0; font-size: 22px; letter-spacing: 1px; text-transform: uppercase; }}
  .header p {{ margin: 4px 0 0; font-size: 13px; color: #aaa; font-family: sans-serif; }}
  .view-browser {{ display:block; text-align:center; padding: 12px 32px; }}
  .view-browser a {{
    display: inline-block;
    background: #f5c842; color: #0f0f1a;
    font-family: sans-serif; font-size: 12px; font-weight: 700;
    letter-spacing: 1px; text-transform: uppercase; text-decoration: none;
    padding: 10px 24px; border-radius: 4px;
  }}
  .section {{ padding: 24px 32px; border-bottom: 1px solid #efefef; }}
  .section-label {{ font-family: sans-serif; font-size: 10px; font-weight: 700; letter-spacing: 2px;
                    text-transform: uppercase; color: #888; margin-bottom: 12px; }}
  .section h2 {{ font-family: Georgia, serif; margin: 0 0 16px; font-size: 20px; color: #1a1a1a; }}
  .section h4 {{ font-family: Georgia, serif; margin: 18px 0 5px; font-size: 15px; font-weight: 700; color: #1a1a1a; }}
  .section h4 a {{ color: #1a1a2e; text-decoration: none; border-bottom: 1px solid #ddd; }}
  .section h4 a:hover {{ border-bottom-color: #1a1a2e; }}
  .section p {{ font-family: Georgia, serif; font-size: 14px; line-height: 1.7; color: #333; margin: 0 0 10px; }}
  /* Article cards (Tech, La Liga, Singapore) */
  .article-card {{ padding: 16px 0; border-bottom: 1px solid #f0ede6; }}
  .article-card:last-child {{ border-bottom: none; }}
  .article-source {{ font-family: sans-serif; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
                     text-transform: uppercase; color: #aaa; margin-bottom: 4px; }}
  /* Skim items */
  .skim-item {{ padding: 16px 0; border-bottom: 1px solid #f0ede6; }}
  .skim-item:last-child {{ border-bottom: none; }}
  .skim-item strong {{ display: block; font-size: 15px; margin-bottom: 6px; }}
  .skim-body {{ margin: 0 0 8px; line-height: 1.65; font-size: 14px; }}
  .skim-analysis {{ background: #f8f5ef; border-left: 3px solid #f5c842; padding: 10px 14px;
                    margin: 8px 0; font-size: 13px; line-height: 1.6; color: #444; border-radius: 0 4px 4px 0; }}
  .skim-analysis em {{ font-family: sans-serif; font-size: 10px; font-weight: 700; letter-spacing: 1px;
                       text-transform: uppercase; font-style: normal; color: #aaa; display: block; margin-bottom: 4px; }}
  .skim-sources {{ font-family: sans-serif; font-size: 11px; color: #aaa; margin: 6px 0 0; }}
  .skim-sources a {{ color: #666; text-decoration: none; border-bottom: 1px solid #ddd; }}
  /* Quote */
  .qotd {{ margin: 0; padding: 20px 24px; background: #f0ece4; border-left: 4px solid #1a1a2e;
           border-radius: 0 6px 6px 0; }}
  .qotd-text {{ font-family: Georgia, serif; font-size: 17px; font-style: italic; line-height: 1.7;
                color: #1a1a2e; margin: 0 0 10px; }}
  .qotd cite {{ font-family: sans-serif; font-size: 12px; color: #888; font-style: normal; }}
  .qotd cite a {{ color: #555; }}
  /* Photo */
  .potd {{ margin: 0; }}
  .potd-title {{ font-family: Georgia, serif; font-size: 15px; font-weight: 700; margin: 10px 0 4px; }}
  .potd-caption {{ font-size: 13px; color: #555; line-height: 1.6; margin: 0 0 6px; }}
  .potd-credit {{ font-family: sans-serif; font-size: 11px; color: #aaa; margin: 0; }}
  .potd-credit a {{ color: #888; }}
  /* Poem */
  .poem {{ background: #faf8f4; border: 1px solid #e8e4dc; border-radius: 6px; padding: 20px 24px; }}
  .poem-title {{ font-family: Georgia, serif; font-size: 16px; font-weight: 700; margin: 0 0 4px; }}
  .poem-author {{ font-family: sans-serif; font-size: 12px; color: #888; margin: 0 0 16px; }}
  .poem-author a {{ color: #666; }}
  .poem-body {{ display: flex; flex-direction: column; }}
  .poem-line {{ font-size: 14px; line-height: 1.9; color: #333; }}
  .poem-more {{ font-family: sans-serif; font-size: 12px; color: #aaa; margin: 12px 0 0; }}
  /* Lang */
  .lang-block {{ background: #f4f0eb; border-left: 4px solid #c0392b; padding: 16px 20px;
                  margin: 12px 0; border-radius: 0 6px 6px 0; }}
  .lang-block.ja {{ border-left-color: #e74c3c; }}
  .lang-block.zh {{ border-left-color: #e67e22; }}
  .lang-label {{ font-family: sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 1px;
                  text-transform: uppercase; color: #888; margin-bottom: 8px; }}
  ruby rt {{ font-size: 0.6em; color: #555; }}
  ul {{ margin: 8px 0; padding-left: 20px; }}
  li {{ margin-bottom: 6px; line-height: 1.6; }}
  .footer {{ background: #1a1a2e; color: #888; padding: 20px 32px; font-family: sans-serif; font-size: 12px; }}
</style>
</head>
<body>
<div class="wrapper">

  <div class="header">
    <h1>☀️ Your Daily Digest</h1>
    <p>{today} · Personalised for you</p>
  </div>

  {browser_button}

  <!-- QUOTE OF THE DAY -->
  {"" if not quote else f'<div class="section"><div class="section-label">💬 Quote of the Day</div>{quote}</div>'}

  <!-- THE SKIM -->
  <div class="section">
    <div class="section-label">📰 World News</div>
    <h2>The Skim</h2>
    {skim}
  </div>

  <!-- TECH ASIA -->
  <div class="section">
    <div class="section-label">💻 Tech · Asia</div>
    <h2>Tech In Asia</h2>
    {tech}
  </div>

  <!-- LA LIGA OPINION -->
  <div class="section">
    <div class="section-label">⚽ Fútbol · Opinión</div>
    <h2>La Liga Opinión</h2>
    {laliga}
  </div>

  <!-- SINGAPORE -->
  <div class="section">
    <div class="section-label">🇸🇬 Local · Singapore</div>
    <h2>Singapore Kopi</h2>
    {sg}
  </div>

  <!-- LANGUAGE CORNER -->
  <div class="section">
    <div class="section-label">🌍 Language Corner</div>
    <h2>Daily Practice</h2>
    <p style="font-family:sans-serif;font-size:13px;color:#666;">One fun world news story per language — adapted to your level.</p>

    <div class="lang-block">
      <div class="lang-label">🇫🇷 French · Niveau avancé</div>
      {fr}
    </div>

    <div class="lang-block ja">
      <div class="lang-label">🇯🇵 日本語 · JLPT N2</div>
      {ja}
    </div>

    <div class="lang-block zh">
      <div class="lang-label">🇨🇳 中文 · HSK A2 (拼音)</div>
      {zh}
    </div>
  </div>

  <!-- PHOTO OF THE DAY -->
  {"" if not photo else f'<div class="section"><div class="section-label">🖼️ Photo of the Day · Wikimedia Commons</div>{photo}</div>'}

  <!-- POEM OF THE DAY -->
  {"" if not poem else f'<div class="section"><div class="section-label">📜 Poem of the Day</div>{poem}</div>'}

  <div class="footer">
    Built with Claude · Delivered daily · Singapore 🇸🇬
  </div>

</div>
</body>
</html>"""


# ── Email Sending ─────────────────────────────────────────────────────────────

def send_email(html: str):
    sender = os.environ["EMAIL_SENDER"]
    recipient = os.environ["EMAIL_RECIPIENT"]
    password = os.environ["EMAIL_APP_PASSWORD"]

    today = datetime.now().strftime("%d %b %Y")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"☀️ Your Daily Digest · {today}"
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())
    print(f"✅ Digest sent to {recipient}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("📡 Fetching feeds...")
    general_articles  = fetch_articles(FEEDS["general"])
    tech_articles     = fetch_articles(FEEDS["tech_asia"])
    laliga_articles   = fetch_articles(FEEDS["la_liga_opinion"])
    sg_articles       = fetch_articles(FEEDS["singapore"])
    quirky_articles   = fetch_articles(FEEDS["quirky"])

    print("🤖 Building sections with Claude...")
    skim, used_titles = build_skim(general_articles)
    tech   = build_tech_asia(tech_articles)
    laliga = build_laliga_opinion(laliga_articles)
    sg     = build_singapore(sg_articles)
    fr, ja, zh = build_language_corner(quirky_articles, already_covered=general_articles)
    quote  = build_quote()
    photo  = build_photo_of_day()
    poem   = build_poem_of_day()

    print("📧 Sending email...")
    # HTML file (GitHub Pages) — full ruby tags for furigana/pinyin rendered on top
    html_web = build_html(skim, tech, laliga, sg, fr, ja, zh,
                          quote=quote, photo=photo, poem=poem, web_url="")

    # Email — strip ruby annotations entirely (no inline readings in email)
    ja_email = ruby_strip(ja)
    zh_email = ruby_strip(zh)
    html_email = build_html(skim, tech, laliga, sg, fr, ja_email, zh_email,
                            quote=quote, photo=photo, poem=poem, web_url=GITHUB_PAGES_URL)

    # Save HTML for GitHub Pages (workflow will commit this file)
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_web)
    print("💾 Saved docs/index.html for GitHub Pages")

    send_email(html_email)


if __name__ == "__main__":
    main()
