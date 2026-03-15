#!/usr/bin/env python3
"""
Daily Multilingual News Digest
Fetches RSS feeds, summarizes with Claude, sends via email.
"""

import os
import re
import json
import random
import smtplib
import feedparser
import anthropic
import urllib.request
import urllib.parse
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ── Constants ─────────────────────────────────────────────────────────────────

GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL", "https://sillynomad.github.io/daily-digest/")
USED_STORIES_FILE = "used_stories.json"
MAX_HISTORY = 20      # entries to keep per category in used_stories.json
MAX_PER_FEED = 6      # articles to pull per feed URL
MAX_ARTICLES = 15     # total articles passed to Claude per section

# ── RSS Feed Sources ──────────────────────────────────────────────────────────

FEEDS = {
    "general": [
        "https://feeds.bbci.co.uk/news/world/rss.xml",
        "https://rss.nytimes.com/services/xml/rss/nyt/World.xml",
        "https://www.theguardian.com/world/rss",
        "https://feeds.npr.org/1004/rss.xml",
        "https://www.aljazeera.com/xml/rss/all.xml",
        "https://feeds.feedburner.com/time/world",
        "https://rss.dw.com/rdf/rss-en-world",
    ],
    "tech_asia": [
        "https://e27.co/feed/",
        "https://kr-asia.com/feed",
        "https://restofworld.org/feed/latest",
        "https://technode.com/feed/",
        "https://www.techinasia.com/feed",
        "https://asia.nikkei.com/rss/feed/nar",
    ],
    "la_liga_opinion": [
        "https://e00-marca.uecdn.es/rss/opinion.xml",
        "https://as.com/feeds/rss/portada.rss",
        "https://www.mundodeportivo.com/rss/futbol.xml",
        "https://www.sport.es/rss/futbol.xml",
        "https://www.diarioas.es/rss/feeds/opinion.xml",
    ],
    "singapore": [
        "https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml&category=10416",
        "https://www.todayonline.com/feed",
        "https://mothership.sg/feed/",
        "https://www.businesstimes.com.sg/rss/all",
        "https://www.straitstimes.com/news/singapore/rss.xml",
    ],
    "french_culture": [
        "https://www.lemonde.fr/rss/une.xml",
        "https://www.lefigaro.fr/rss/figaro_actualites.xml",
        "https://www.france24.com/fr/rss",
        "https://www.rfi.fr/fr/rss",
        "https://www.lepoint.fr/rss.xml",
    ],
    "quirky": [
        "https://www.odditycentral.com/feed",
        "https://www.atlasobscura.com/feeds/latest",
        "https://www.mentalfloss.com/feeds/all",
        "https://feeds.bbci.co.uk/news/magazine/rss.xml",
        "https://www.iflscience.com/rss.xml",
        "https://laughingsquid.com/feed/",
        "https://www.amusingplanet.com/feeds/posts/default",
        "https://www.thisiscolossal.com/feed/",
        "https://www.boredpanda.com/feed/",
    ],
}


# ── Used Stories Tracking ─────────────────────────────────────────────────────

def load_used() -> dict:
    """Load the used-stories ledger from disk."""
    try:
        with open(USED_STORIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"story_titles": [], "quote_authors": [], "poem_titles": []}


def save_used(used: dict):
    """Persist the used-stories ledger, trimming to MAX_HISTORY entries."""
    for key in ["story_titles", "quote_authors", "poem_titles"]:
        used[key] = used.get(key, [])[-MAX_HISTORY:]
    with open(USED_STORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(used, f, ensure_ascii=False, indent=2)


# ── Ruby / Furigana helpers ───────────────────────────────────────────────────

def ruby_strip(html: str) -> str:
    """Remove ruby annotations entirely — keep only base characters."""
    html = re.sub(r'<rt>.*?</rt>', '', html, flags=re.DOTALL)
    html = re.sub(r'</?ruby[^>]*>', '', html)
    return html


# ── Feed Fetching ─────────────────────────────────────────────────────────────

def fetch_articles(urls: list[str], limit: int = MAX_ARTICLES) -> list[dict]:
    """Fetch articles from a list of RSS URLs, deduplicated by title."""
    articles = []
    seen_titles = set()
    for url in urls:
        try:
            feed = feedparser.parse(url)
            source_name = feed.feed.get("title", url.split("/")[2])
            count = 0
            for entry in feed.entries:
                if count >= MAX_PER_FEED:
                    break
                title = entry.get("title", "").strip()
                if not title or title.lower() in seen_titles:
                    continue
                seen_titles.add(title.lower())
                articles.append({
                    "title": title,
                    "summary": entry.get("summary", entry.get("description", ""))[:600],
                    "link": entry.get("link", ""),
                    "source": source_name,
                })
                count += 1
            print(f"  ✓ {source_name}: {count} articles")
        except Exception as e:
            print(f"  ✗ {url}: {e}")
    return articles[:limit]


def articles_to_text(articles: list[dict]) -> str:
    lines = []
    for i, a in enumerate(articles, 1):
        lines.append(
            f"{i}. [{a['source']}] {a['title']}\n"
            f"   {a['summary']}\n"
            f"   URL: {a['link']}"
        )
    return "\n\n".join(lines)


# ── Claude Client ─────────────────────────────────────────────────────────────

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-sonnet-4-20250514"


def claude(prompt: str, system: str = "", max_tokens: int = 1500) -> str:
    kwargs = {
        "model": MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    msg = client.messages.create(**kwargs)
    return msg.content[0].text.strip()


# ── Section Builders ──────────────────────────────────────────────────────────

def build_skim(articles: list[dict]) -> tuple[str, list[str]]:
    raw = articles_to_text(articles)
    result = claude(
        f"Here are today's top news articles from multiple sources:\n\n{raw}\n\n"
        "Select 5 stories from DIFFERENT sources — do not pick more than 2 from the same outlet. "
        "Write a global news summary in the style of The Daily Skimm — punchy, witty, conversational. "
        "For each story output this HTML:\n"
        "<div class='skim-item'>\n"
        "  <strong>Bold headline phrase</strong>\n"
        "  <p class='skim-body'>2-3 sentences: what happened, then WHY — cause, background, why now.</p>\n"
        "  <p class='skim-analysis'><em>What This Means:</em> 2-3 sentences of analytical significance.</p>\n"
        "  <p class='skim-sources'>Read more: <a href='URL'>Source Name</a></p>\n"
        "</div>\n"
        "Use the actual article URL and source name for each story. "
        "After all 5 stories add: TITLES_USED: title1|title2|title3|title4|title5\n"
        "Return only the HTML blocks and the TITLES_USED line.",
        system="You are a witty, analytically sharp news summarizer in the style of The Daily Skimm meets The Economist.",
        max_tokens=2000,
    )
    if "TITLES_USED:" in result:
        html_part, titles_part = result.rsplit("TITLES_USED:", 1)
        used_titles = [t.strip() for t in titles_part.strip().split("|")]
    else:
        html_part = result
        used_titles = []
    return html_part.strip(), used_titles


def build_tech_asia(articles: list[dict], used_titles: list[str]) -> str:
    raw = articles_to_text(articles)
    exclusion = "\n".join(f"- {t}" for t in used_titles) if used_titles else ""
    excl_note = f"\n\nDo NOT repeat these stories already used today:\n{exclusion}" if exclusion else ""
    return claude(
        f"Here are tech news articles from Asia:\n\n{raw}{excl_note}\n\n"
        "Pick 3 stories from DIFFERENT sources. "
        "For each output:\n"
        "<div class='article-card'>\n"
        "  <div class='article-source'>Source Name</div>\n"
        "  <h4><a href='URL'>Title</a></h4>\n"
        "  <p>2 sentences on why it matters.</p>\n"
        "</div>\n"
        "Return only the HTML.",
        system="You are a sharp tech journalist covering Asia's startup and tech ecosystem.",
    )


def build_laliga_opinion(articles: list[dict]) -> str:
    raw = articles_to_text(articles)
    return claude(
        f"Artículos de opinión sobre fútbol español:\n\n{raw}\n\n"
        "Elige 3 piezas de opinión de DIFERENTES medios (Marca, AS, Sport, Mundo Deportivo). "
        "Para cada una:\n"
        "<div class='article-card'>\n"
        "  <div class='article-source'>Nombre del medio</div>\n"
        "  <h4><a href='URL'>Título</a></h4>\n"
        "  <p>2-3 frases con el argumento principal del columnista.</p>\n"
        "</div>\n"
        "Devuelve solo el HTML.",
        system="Eres un periodista deportivo español especializado en análisis sobre La Liga.",
    )


def build_singapore(articles: list[dict]) -> str:
    raw = articles_to_text(articles)
    return claude(
        f"Singapore local news articles:\n\n{raw}\n\n"
        "Pick 3 stories from DIFFERENT sources (CNA, Today, Mothership, Business Times, Straits Times). "
        "For each:\n"
        "<div class='article-card'>\n"
        "  <div class='article-source'>Source Name</div>\n"
        "  <h4><a href='URL'>Title</a></h4>\n"
        "  <p>2 sentences of context.</p>\n"
        "</div>\n"
        "Return only the HTML.",
        system="You are a local Singapore news correspondent writing for an expat-friendly morning briefing.",
    )


def build_french(articles: list[dict], used_story_titles: list[str]) -> str:
    """French section: genuine journalism from French-language sources."""
    raw = articles_to_text(articles)
    exclusion = "\n".join(f"- {t}" for t in used_story_titles) if used_story_titles else ""
    excl_note = f"\n\nDo NOT use any of these stories:\n{exclusion}" if exclusion else ""
    return claude(
        f"Here are articles from French-language news sources:\n\n{raw}{excl_note}\n\n"
        "Pick the single most interesting story. Write a 4-paragraph journalistic piece in natural, "
        "fluent French — the register of Le Monde or Le Point. "
        "Rules: each paragraph MUST add new information; zero repetition; no padding. "
        "Paragraph 1: the news hook. Paragraph 2: background and context. "
        "Paragraph 3: stakes and implications. Paragraph 4: wider perspective or irony. "
        "Format as HTML: <h4> title, then 4 <p> tags. No vocabulary glossary.",
        system="Tu es un journaliste francophone expérimenté qui écrit pour un lecteur avancé.",
        max_tokens=1200,
    )


def build_language_corner_ja_zh(
    articles: list[dict],
    already_covered: list[str],
    used_story_titles: list[str],
) -> tuple[str, str]:
    """Pick 2 distinct quirky stories for Japanese and Mandarin, avoiding repeats."""
    raw = articles_to_text(articles)
    all_excluded = list(set(already_covered + used_story_titles))
    excl_text = "\n".join(f"- {t}" for t in all_excluded)
    excl_note = f"\n\nDo NOT pick any of these — they have been used recently:\n{excl_text}" if excl_text else ""

    chosen = claude(
        f"Here are fun and quirky world news articles:\n\n{raw}{excl_note}\n\n"
        "Pick exactly 2 of the most fun, playful, or quirky stories — nothing tragic or political, "
        "nothing from the excluded list above, and the 2 must be on DIFFERENT topics. "
        "Return ONLY a JSON array: "
        '[{"title": ..., "summary": ..., "link": ...}, {"title": ..., "summary": ..., "link": ...}]. '
        "No markdown fences.",
        system="You curate fun, lighthearted news stories for language learners.",
    )
    try:
        stories = json.loads(chosen)[:2]
        if len(stories) < 2:
            raise ValueError("Not enough stories")
    except Exception:
        stories = articles[:2]

    s_ja = f"Title: {stories[0]['title']}\nSummary: {stories[0].get('summary','')}\nURL: {stories[0].get('link','')}"
    s_zh = f"Title: {stories[1]['title']}\nSummary: {stories[1].get('summary','')}\nURL: {stories[1].get('link','')}"

    # Japanese — N2 with ruby tags
    ja = claude(
        f"Rewrite this fun news story in Japanese at JLPT N2 level.\nStory:\n{s_ja}\n\n"
        "Rules: N2-appropriate grammar, no N1 expressions. "
        "Wrap EVERY kanji/compound in ruby tags: <ruby>食事<rt>しょくじ</rt></ruby>. "
        "After the article, add a <ul> vocab glossary of 5 key words: "
        "<li><ruby>単語<rt>よみ</rt></ruby> — English meaning</li>. "
        "Format with <p> tags for paragraphs.",
        system="You are a Japanese language teacher writing N2-level news for learners.",
    )

    # Mandarin — A2 with ruby tags
    zh = claude(
        f"Rewrite this fun news story in Mandarin Chinese at HSK 2-3 (A2) level.\nStory:\n{s_zh}\n\n"
        "Rules: very simple sentences (max 12 characters each). "
        "Wrap EVERY character/word in ruby tags with pinyin: <ruby>我<rt>wǒ</rt></ruby>. "
        "After the article, add a <ul> glossary of 5 key words: "
        "<li><ruby>词<rt>pīnyīn</rt></ruby> — English meaning</li>. "
        "Format with <p> tags for paragraphs.",
        system="You are a Mandarin teacher writing HSK A2-level news for beginners.",
    )

    # Return both the HTML and the titles used
    return ja, zh, [stories[0]["title"], stories[1]["title"]]


# ── Quote / Photo / Poem ──────────────────────────────────────────────────────

def build_quote(used_authors: list[str]) -> tuple[str, str]:
    """Generate a quote, avoiding recently used authors."""
    excl = ", ".join(used_authors[-10:]) if used_authors else "none"
    result = claude(
        f"Choose one memorable, surprising, thought-provoking quote. "
        f"Do NOT use quotes by any of these recently featured authors: {excl}. "
        "Draw from philosophy, science, literature, sport, history, music — be eclectic. "
        "Avoid overused clichés. Aim to surprise. "
        "Return ONLY a JSON object: "
        '{"quote": "...", "author": "...", "author_search_url": "https://www.google.com/search?q=..."}. '
        "No markdown fences.",
        system="You are a thoughtful curator of memorable, lesser-known quotations.",
    )
    try:
        data = json.loads(result)
        q = data.get("quote", "")
        a = data.get("author", "")
        url = data.get("author_search_url", f"https://www.google.com/search?q={urllib.parse.quote(a)}")
        html = f"""<blockquote class="qotd">
  <p class="qotd-text">"{q}"</p>
  <cite>— <a href="{url}" target="_blank">{a}</a></cite>
</blockquote>"""
        return html, a
    except Exception:
        return "", ""


def build_photo_of_day() -> str:
    """Fetch Wikimedia Commons Picture of the Day."""
    try:
        date_str = datetime.now().strftime("%Y-%m-%d")
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
            raise ValueError("No images found")

        img_page = next(iter(pages.values()))
        info = img_page.get("imageinfo", [{}])[0]
        img_url = info.get("thumburl") or info.get("url", "")
        if not img_url:
            raise ValueError("No image URL")

        page_url = info.get("descriptionurl", "https://commons.wikimedia.org/wiki/Commons:Picture_of_the_day")
        meta = info.get("extmetadata", {})
        raw_title = meta.get("ObjectName", {}).get("value",
                    img_page.get("title", "Picture of the Day").replace("File:", "").rsplit(".", 1)[0])
        title = re.sub(r'<[^>]+>', '', raw_title)
        desc = re.sub(r'<[^>]+>', '', meta.get("ImageDescription", {}).get("value", ""))[:280].strip()
        if desc:
            desc += "…"
        credit = re.sub(r'<[^>]+>', '', meta.get("Artist", {}).get("value", "Wikimedia Commons")).strip()

        return f"""<div class="potd">
  <a href="{page_url}" target="_blank">
    <img src="{img_url}" alt="{title}" style="width:100%;border-radius:6px;display:block;">
  </a>
  <p class="potd-title">{title}</p>
  {"" if not desc else f'<p class="potd-caption">{desc}</p>'}
  <p class="potd-credit">📷 {credit} · <a href="{page_url}" target="_blank">Wikimedia Commons</a></p>
</div>"""
    except Exception as e:
        print(f"Warning: Wikimedia POTD failed: {e}")
        return ""


def build_poem_of_day(used_poem_titles: list[str]) -> tuple[str, str]:
    """Fetch a short lyric poem (≤24 lines), avoiding recently used titles."""
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
                   "", "i fear no fate(for you are my fate,my sweet)i want",
                   "no world(for beautiful you are my world,my true)",
                   "and it's you are whatever a moon has always meant",
                   "and whatever a sun will always sing is you"]},
        {"title": "Still I Rise", "author": "Maya Angelou",
         "lines": ["You may write me down in history", "With your bitter, twisted lies,",
                   "You may trod me in the very dirt", "But still, like dust, I'll rise.", "",
                   "Does my sassiness upset you?", "Why are you beset with gloom?",
                   "'Cause I walk like I've got oil wells", "Pumping in my living room."]},
        {"title": "Hope is the Thing with Feathers", "author": "Emily Dickinson",
         "lines": ["Hope is the thing with feathers", "That perches in the soul,",
                   "And sings the tune without the words,", "And never stops at all,", "",
                   "And sweetest in the gale is heard;", "And sore must be the storm",
                   "That could abash the little bird", "That kept so many warm.", "",
                   "I've heard it in the chillest land,", "And on the strangest sea;",
                   "Yet, never, in extremity,", "It asked a crumb of me."]},
    ]

    title, author, lines = "", "", []

    # Try up to 4 times to get a short, non-repeated poem
    for attempt in range(4):
        try:
            url = "https://poetrydb.org/random/1"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read())
            if isinstance(data, list) and data:
                poem = data[0]
            elif isinstance(data, dict) and "lines" in data:
                poem = data
            else:
                raise ValueError("Bad response")
            t = poem.get("title", "")
            l = poem.get("lines", [])
            if not l or len(l) > 24 or t in used_poem_titles:
                continue   # too long or already used — try again
            title = t
            author = poem.get("author", "Unknown")
            lines = l
            break
        except Exception:
            break

    if not lines:
        # Use a fallback poem not in recently used
        available = [p for p in FALLBACK_POEMS if p["title"] not in used_poem_titles]
        poem = random.choice(available if available else FALLBACK_POEMS)
        title = poem["title"]
        author = poem["author"]
        lines = poem["lines"]

    lines_html = "<br>\n".join(l if l.strip() else "<br>" for l in lines)
    search_url = f"https://www.google.com/search?q={urllib.parse.quote(author)}+poet"
    html = f"""<div class="poem">
  <p class="poem-title">{title}</p>
  <p class="poem-author">by <a href="{search_url}" target="_blank">{author}</a></p>
  <div class="poem-body">{lines_html}</div>
</div>"""
    return html, title


# ── Email / HTML Builder ──────────────────────────────────────────────────────

def build_html(skim, tech, laliga, sg, fr, ja, zh,
               quote="", photo="", poem="", web_url="") -> str:
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
  *, *::before, *::after {{ box-sizing: border-box; }}
  body {{ font-family: Georgia, serif; background: #f9f6f1; margin: 0; padding: 0; color: #1a1a1a; }}
  .wrapper {{ max-width: 640px; margin: 0 auto; background: #ffffff; }}
  .header {{ background: #1a1a2e; color: white; padding: 28px 32px; }}
  .header h1 {{ margin: 0; font-size: 22px; letter-spacing: 1px; text-transform: uppercase; font-family: Georgia, serif; }}
  .header p {{ margin: 4px 0 0; font-size: 13px; color: #aaa; font-family: sans-serif; }}
  .view-browser {{ display:block; text-align:center; padding: 14px 32px; background: #f8f5ef; border-bottom: 1px solid #efefef; }}
  .view-browser a {{
    display: inline-block; background: #f5c842; color: #0f0f1a;
    font-family: sans-serif; font-size: 12px; font-weight: 700;
    letter-spacing: 1px; text-transform: uppercase; text-decoration: none;
    padding: 10px 28px; border-radius: 4px;
  }}
  .section {{ padding: 24px 32px; border-bottom: 1px solid #efefef; }}
  .section-label {{ font-family: sans-serif; font-size: 10px; font-weight: 700; letter-spacing: 2px;
                    text-transform: uppercase; color: #888; margin-bottom: 12px; }}
  .section h2 {{ font-family: Georgia, serif; margin: 0 0 16px; font-size: 20px; color: #1a1a1a; }}
  .section h4 {{ font-family: Georgia, serif; margin: 18px 0 5px; font-size: 15px; font-weight: 700; color: #1a1a1a; }}
  .section h4 a {{ color: #1a1a2e; text-decoration: none; border-bottom: 1px solid #ddd; }}
  .section h4 a:hover {{ border-bottom-color: #1a1a2e; }}
  .section p {{ font-family: Georgia, serif; font-size: 14px; line-height: 1.7; color: #333; margin: 0 0 10px; }}
  /* Article cards */
  .article-card {{ padding: 16px 0; border-bottom: 1px solid #f0ede6; }}
  .article-card:last-child {{ border-bottom: none; }}
  .article-source {{ font-family: sans-serif; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
                     text-transform: uppercase; color: #aaa; margin-bottom: 4px; }}
  /* Skim */
  .skim-item {{ padding: 16px 0; border-bottom: 1px solid #f0ede6; }}
  .skim-item:last-child {{ border-bottom: none; }}
  .skim-item strong {{ display: block; font-family: Georgia, serif; font-size: 15px; font-weight: 700; margin-bottom: 6px; color: #1a1a1a; }}
  .skim-body {{ font-family: Georgia, serif; font-size: 14px; line-height: 1.65; margin: 0 0 8px; color: #333; }}
  .skim-analysis {{ background: #f8f5ef; border-left: 3px solid #f5c842; padding: 10px 14px;
                    margin: 8px 0; font-size: 13px; line-height: 1.6; color: #444; border-radius: 0 4px 4px 0; }}
  .skim-analysis em {{ font-family: sans-serif; font-size: 10px; font-weight: 700; letter-spacing: 1px;
                       text-transform: uppercase; font-style: normal; color: #aaa; display: block; margin-bottom: 4px; }}
  .skim-sources {{ font-family: sans-serif; font-size: 11px; color: #aaa; margin: 6px 0 0; }}
  .skim-sources a {{ color: #666; text-decoration: none; border-bottom: 1px solid #ddd; }}
  /* Quote */
  .qotd {{ margin: 0; padding: 20px 24px; background: #f0ece4; border-left: 4px solid #1a1a2e; border-radius: 0 6px 6px 0; }}
  .qotd-text {{ font-family: Georgia, serif; font-size: 17px; font-style: italic; line-height: 1.7; color: #1a1a2e; margin: 0 0 10px; }}
  .qotd cite {{ font-family: sans-serif; font-size: 12px; color: #888; font-style: normal; }}
  .qotd cite a {{ color: #555; }}
  /* Photo */
  .potd {{ margin: 0; }}
  .potd-title {{ font-family: Georgia, serif; font-size: 15px; font-weight: 700; margin: 10px 0 4px; }}
  .potd-caption {{ font-family: Georgia, serif; font-size: 13px; color: #555; line-height: 1.6; margin: 0 0 6px; }}
  .potd-credit {{ font-family: sans-serif; font-size: 11px; color: #aaa; margin: 0; }}
  .potd-credit a {{ color: #888; }}
  /* Poem */
  .poem {{ background: #faf8f4; border: 1px solid #e8e4dc; border-radius: 6px; padding: 20px 24px; }}
  .poem-title {{ font-family: Georgia, serif; font-size: 16px; font-weight: 700; margin: 0 0 4px; }}
  .poem-author {{ font-family: sans-serif; font-size: 12px; color: #888; margin: 0 0 16px; }}
  .poem-author a {{ color: #666; }}
  .poem-body {{ font-family: Georgia, serif; font-size: 14px; line-height: 1.9; color: #333; }}
  /* Lang */
  .lang-block {{ background: #f4f0eb; border-left: 4px solid #c0392b; padding: 16px 20px; margin: 12px 0; border-radius: 0 6px 6px 0; }}
  .lang-block.ja {{ border-left-color: #e74c3c; }}
  .lang-block.zh {{ border-left-color: #e67e22; }}
  .lang-label {{ font-family: sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 1px;
                  text-transform: uppercase; color: #888; margin-bottom: 8px; }}
  ruby rt {{ font-size: 0.6em; color: #555; }}
  ul {{ margin: 8px 0; padding-left: 20px; }}
  li {{ font-family: Georgia, serif; font-size: 14px; margin-bottom: 6px; line-height: 1.6; }}
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

    <div class="lang-block">
      <div class="lang-label">🇫🇷 Français · Le point du jour</div>
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
    # Load history to avoid repeats
    used = load_used()
    print(f"📚 Loaded used history: "
          f"{len(used['story_titles'])} stories, "
          f"{len(used['quote_authors'])} authors, "
          f"{len(used['poem_titles'])} poems")

    print("📡 Fetching feeds...")
    general_articles = fetch_articles(FEEDS["general"])
    tech_articles    = fetch_articles(FEEDS["tech_asia"])
    laliga_articles  = fetch_articles(FEEDS["la_liga_opinion"])
    sg_articles      = fetch_articles(FEEDS["singapore"])
    french_articles  = fetch_articles(FEEDS["french_culture"])
    quirky_articles  = fetch_articles(FEEDS["quirky"])

    print("🤖 Building sections with Claude...")
    skim, skim_titles         = build_skim(general_articles)
    tech                      = build_tech_asia(tech_articles, skim_titles)
    laliga                    = build_laliga_opinion(laliga_articles)
    sg                        = build_singapore(sg_articles)
    fr                        = build_french(french_articles, used["story_titles"])
    ja, zh, lang_titles       = build_language_corner_ja_zh(
                                    quirky_articles,
                                    already_covered=skim_titles,
                                    used_story_titles=used["story_titles"],
                                )
    quote_html, quote_author  = build_quote(used["quote_authors"])
    photo                     = build_photo_of_day()
    poem_html, poem_title     = build_poem_of_day(used["poem_titles"])

    # Update used history
    used["story_titles"]  = used["story_titles"] + skim_titles + lang_titles
    used["quote_authors"] = used["quote_authors"] + ([quote_author] if quote_author else [])
    used["poem_titles"]   = used["poem_titles"]   + ([poem_title]   if poem_title   else [])
    save_used(used)
    print("💾 Saved used_stories.json")

    print("📧 Building HTML...")
    # HTML version (GitHub Pages) — ruby on top
    html_web = build_html(skim, tech, laliga, sg, fr, ja, zh,
                          quote=quote_html, photo=photo, poem=poem_html, web_url="")

    # Email version — strip ruby entirely, add browser button
    ja_email = ruby_strip(ja)
    zh_email = ruby_strip(zh)
    html_email = build_html(skim, tech, laliga, sg, fr, ja_email, zh_email,
                            quote=quote_html, photo=photo, poem=poem_html,
                            web_url=GITHUB_PAGES_URL)

    # Save for GitHub Pages
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_web)
    print("💾 Saved docs/index.html")

    send_email(html_email)


if __name__ == "__main__":
    main()
