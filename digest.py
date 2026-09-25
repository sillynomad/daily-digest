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

SCRIPT_VERSION = "2026-09-24 · jobs-v4"   # bump when digest.py changes; printed in the Action log
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


# ── Jobs of the Day ───────────────────────────────────────────────────────────
# Everything in this block is meant to be edited by hand as the search evolves.

JOBS_PER_DAY = 3
JOB_BOARDS_FILE = "job_boards.json"   # cache of resolved ATS board slugs
MAX_JOB_HISTORY = 90                  # job URLs remembered, to avoid repeats
BOARD_RESOLVE_PER_RUN = 8             # unknown companies probed per run
JOB_MAX_AGE_DAYS = 21                 # ignore postings older than this
JOB_CANDIDATES_TO_CLAUDE = 30         # shortlist size sent for final ranking
MAX_PER_COMPANY_SHORTLIST = 4         # stops one big board crowding out the shortlist
ONE_ROLE_PER_COMPANY = True           # never send three roles from the same employer

# Who you are, in the terms a recruiter would use. This is the brief Claude
# ranks against — rewrite it as the search moves.
CANDIDATE_PROFILE = """
Country Manager / GM with full P&L ownership across Singapore and Australia at
TTRacing (consumer hardware, 500 Global-backed). Former CEO of FoodRazor (B2B
SaaS, Cocoon Capital-backed): led the turnaround, scaled to 10 markets, company
acquired 2023. Earlier: Rakuten, and six years at EF Education First across Hong
Kong and Tokyo. Yale BA, INSEAD MBA. EU passport, based in Singapore.
Distributor and market-entry work across Australia, Japan and Costa Rica.
Languages: English, Spanish, French fluent; Japanese working; Mandarin A2.

TARGETING: GM, Country Manager, Managing Director, Regional Director or Head of
<function> roles with commercial ownership at Western companies, based in
Singapore or covering APAC/SEA. Consumer brands, B2B SaaS, sports/endurance and
partnerships/channel roles all fit.

HARD FILTERS: Singapore-based or genuinely APAC-regional (remote-APAC counts).
Seniority at least Director/Head level. Compensation must clear SGD 15,000/month
— treat anything that looks below that as a non-starter.
AVOID: individual-contributor sales quotas, junior or mid-level roles,
engineering roles, and roles requiring relocation outside Singapore.
"""

# Tier list — the resolver finds each company's ATS board automatically and
# caches the answer in job_boards.json. Add or remove names freely.
TARGET_COMPANIES = [
    "Stripe", "Canva", "Miro", "Spotify", "HubSpot", "Asana", "Adobe",
    "Strava", "Zwift", "Whoop", "Oura", "Sportradar", "Emeritus",
    "Figma", "Notion", "Airtable", "Atlassian", "Datadog", "Twilio",
    "Cloudflare", "Deel", "Rippling", "Remote", "Gitlab", "Elastic",
    "Peloton", "Garmin", "Wahoo Fitness", "Lululemon", "On Running",
]

# Companies whose board we already know — skips probing.
BOARD_OVERRIDES = {
    "Stripe": ["greenhouse", "stripe"],
    "Asana": ["greenhouse", "asana"],
}

JOB_TITLE_KEYWORDS = [
    "country manager", "general manager", "managing director", "country lead",
    "country director", "regional director", "regional manager", "head of",
    "vp ", "vice president", "director, ", "director of", "commercial director",
    "chief commercial", "chief operating", "chief executive", "gm,", "gm ",
    "market lead", "market director", "partnerships", "channel", "go-to-market",
    "business development director", "sales director", "revenue",
]

JOB_TITLE_EXCLUDE = [
    "intern", "internship", "graduate", "junior", "associate ", "assistant",
    "engineer", "developer", "designer", "scientist", "analyst", "recruiter",
    "coordinator", "specialist", "representative", "sdr", "bdr", "executive assistant",
    "manager, engineering", "software", "technician", "accountant", "controller",
    # individual-contributor sales — "Channel Account Executive" is not a Head of role
    "account executive", "account manager", "account director", "sales manager",
    "customer success manager", "solutions consultant", "partner manager",
]

# A posting must carry one of these to count as reachable from Singapore.
# Word-boundary matched, so "Seattle" no longer reads as "sea".
JOB_LOCATION_REQUIRED = [
    "singapore", "sg", "apac", "aspac", "apj", "asia pacific", "asia-pacific",
    "southeast asia", "south east asia", "south-east asia", "sea", "asia",
    "global", "worldwide", "anywhere",
    # APAC hubs — a regional role often lists the hub rather than the region.
    # Relocation out of Singapore is handled by the ranking prompt, not here.
    "australia", "sydney", "melbourne", "new zealand", "auckland",
    "japan", "tokyo", "hong kong", "korea", "seoul", "taiwan", "taipei",
    "malaysia", "kuala lumpur", "indonesia", "jakarta", "thailand", "bangkok",
    "vietnam", "hanoi", "ho chi minh", "philippines", "manila", "india",
    "bangalore", "bengaluru", "mumbai", "china", "shanghai", "beijing", "shenzhen",
]

# Bare "remote" is no longer enough on its own — "US FL Miami - Remote" is not
# a Singapore job. Remote only counts alongside one of the tokens above.
JOB_LOCATION_EXCLUDE = [
    "remote - us", "remote, us", "remote (us", "united states", "usa", "u.s.",
    "latam", "latin america", "americas", "emea", "europe", "north america",
    "canada", "brazil", "mexico", "argentina", "colombia", "chile",
    "united kingdom", "germany", "france", "spain", "netherlands", "ireland",
    "poland", "portugal", "israel", "dubai", "uae",
]

# Broad Singapore sweep via Adzuna. Free key from developer.adzuna.com.
ADZUNA_APP_ID = os.environ.get("ADZUNA_APP_ID", "")
ADZUNA_APP_KEY = os.environ.get("ADZUNA_APP_KEY", "")
ADZUNA_QUERIES = [
    "country manager", "general manager", "managing director",
    "regional director", "head of partnerships", "commercial director",
]

# The Muse — free, no key.
MUSE_LOCATIONS = ["Singapore, Singapore"]
MUSE_LEVELS = ["Senior Level", "Management"]


# ── Used Stories Tracking ─────────────────────────────────────────────────────

def load_used() -> dict:
    """Load the used-stories ledger from disk."""
    try:
        with open(USED_STORIES_FILE, "r", encoding="utf-8") as f:
            used = json.load(f)
        # Self-heal: a URL recorded more than once came from a board handing the
        # same careers-page link to several roles. Leaving it in would exclude
        # that employer's entire board from here on.
        jobs = used.get("job_urls", [])
        counts = {}
        for u in jobs:
            counts[u] = counts.get(u, 0) + 1
        poisoned = {u for u, n in counts.items() if n > 1}
        if poisoned:
            used["job_urls"] = [u for u in jobs if u not in poisoned]
            print(f"  · dropped {len(poisoned)} generic URL(s) from the job ledger: "
                  + ", ".join(sorted(poisoned)))
        return used
    except Exception:
        return {"story_titles": [], "quote_authors": [], "poem_titles": [], "job_urls": []}


def save_used(used: dict):
    """Persist the used-stories ledger, trimming to MAX_HISTORY entries."""
    for key in ["story_titles", "quote_authors", "poem_titles"]:
        used[key] = used.get(key, [])[-MAX_HISTORY:]
    used["job_urls"] = used.get("job_urls", [])[-MAX_JOB_HISTORY:]
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
MODEL = "claude-sonnet-4-6"


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


# ── Jobs: fetching ────────────────────────────────────────────────────────────

def http_json(url: str, timeout: int = 15):
    """GET a URL and parse JSON. Returns None on any failure."""
    try:
        req = urllib.request.Request(url, headers={
            "User-Agent": "DailyDigestBot/1.0 (personal job digest)",
            "Accept": "application/json",
        })
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception:
        return None


def load_boards() -> dict:
    try:
        with open(JOB_BOARDS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_boards(boards: dict):
    with open(JOB_BOARDS_FILE, "w", encoding="utf-8") as f:
        json.dump(boards, f, ensure_ascii=False, indent=2, sort_keys=True)


def slug_variants(company: str) -> list[str]:
    """Plausible ATS slugs for a company name."""
    base = company.lower().strip()
    compact = re.sub(r"[^a-z0-9]", "", base)
    dashed = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    first = compact.split()[0] if compact else compact
    out = [compact, dashed, first, compact + "inc", compact + "careers",
           compact + "jobs", base.split()[0]]
    seen, uniq = set(), []
    for s in out:
        if s and s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq[:4]


def greenhouse_jobs(slug: str) -> list[dict]:
    data = http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=false")
    if not isinstance(data, dict):
        return []
    out = []
    for j in data.get("jobs", []):
        # Some boards (Stripe) return a generic careers-search page as absolute_url
        # for every posting. Fall back to the canonical per-job Greenhouse URL so
        # each role keeps a distinct link.
        jid = j.get("id")
        url = (j.get("absolute_url") or "").strip()
        if jid and str(jid) not in url:
            url = f"https://boards.greenhouse.io/{slug}/jobs/{jid}"
        out.append({
            "title": (j.get("title") or "").strip(),
            "location": ((j.get("location") or {}).get("name") or "").strip(),
            "url": url,
            "posted": (j.get("updated_at") or j.get("first_published") or "")[:10],
            "salary": "",
        })
    return out


def lever_jobs(slug: str) -> list[dict]:
    data = http_json(f"https://api.lever.co/v0/postings/{slug}?mode=json")
    if not isinstance(data, list):
        return []
    out = []
    for j in data:
        cat = j.get("categories") or {}
        ts = j.get("createdAt")
        posted = ""
        if isinstance(ts, (int, float)):
            posted = datetime.utcfromtimestamp(ts / 1000).strftime("%Y-%m-%d")
        out.append({
            "title": (j.get("text") or "").strip(),
            "location": (cat.get("location") or "").strip(),
            "url": j.get("hostedUrl", ""),
            "posted": posted,
            "salary": "",
        })
    return out


def ashby_jobs(slug: str) -> list[dict]:
    data = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}")
    if not isinstance(data, dict):
        return []
    out = []
    for j in data.get("jobs", []):
        out.append({
            "title": (j.get("title") or "").strip(),
            "location": (j.get("location") or "").strip(),
            "url": j.get("jobUrl") or j.get("applyUrl") or "",
            "posted": (j.get("publishedAt") or "")[:10],
            "salary": "",
        })
    return out


ATS_FETCHERS = {
    "greenhouse": greenhouse_jobs,
    "lever": lever_jobs,
    "ashby": ashby_jobs,
}


def resolve_board(company: str) -> list | None:
    """Probe the three ATS APIs for a company's public board. Returns [ats, slug] or None."""
    for slug in slug_variants(company):
        for ats, fetcher in ATS_FETCHERS.items():
            jobs = fetcher(slug)
            if jobs:
                print(f"  🔎 resolved {company} → {ats}/{slug} ({len(jobs)} jobs)")
                return [ats, slug]
    print(f"  · no public board found for {company}")
    return None


def fetch_target_company_jobs() -> list[dict]:
    """Pull jobs from target companies' ATS boards, resolving unknown boards gradually."""
    boards = load_boards()
    for company, board in BOARD_OVERRIDES.items():
        boards.setdefault(company, {"board": board, "checked": ""})

    today = datetime.now().strftime("%Y-%m-%d")
    probed = 0
    for company in TARGET_COMPANIES:
        entry = boards.get(company)
        stale = False
        if entry and entry.get("board") is None:
            # retry dead ends roughly monthly
            stale = (entry.get("checked", "") < (datetime.now().strftime("%Y-%m-%d")[:7] + "-01"))
        if entry and not stale:
            continue
        if probed >= BOARD_RESOLVE_PER_RUN:
            continue
        probed += 1
        boards[company] = {"board": resolve_board(company), "checked": today}

    jobs = []
    for company, entry in boards.items():
        board = (entry or {}).get("board")
        if not board:
            continue
        ats, slug = board[0], board[1]
        fetcher = ATS_FETCHERS.get(ats)
        if not fetcher:
            continue
        for j in fetcher(slug):
            j["company"] = company
            j["source"] = f"{company} careers"
            jobs.append(j)

    save_boards(boards)
    print(f"  ✓ target company boards: {len(jobs)} raw postings")
    return jobs


def fetch_adzuna_jobs() -> list[dict]:
    """Broad Singapore sweep. Needs free ADZUNA_APP_ID / ADZUNA_APP_KEY."""
    if not (ADZUNA_APP_ID and ADZUNA_APP_KEY):
        print("  · Adzuna skipped (no API key set)")
        return []
    jobs = []
    for q in ADZUNA_QUERIES:
        url = (
            "https://api.adzuna.com/v1/api/jobs/sg/search/1"
            f"?app_id={ADZUNA_APP_ID}&app_key={ADZUNA_APP_KEY}"
            f"&results_per_page=25&what_phrase={urllib.parse.quote(q)}"
            f"&max_days_old={JOB_MAX_AGE_DAYS}&sort_by=date&content-type=application/json"
        )
        data = http_json(url)
        if not isinstance(data, dict):
            continue
        for j in data.get("results", []):
            smin, smax = j.get("salary_min"), j.get("salary_max")
            salary = ""
            if smin:
                salary = f"SGD {int(smin):,}" + (f"–{int(smax):,}" if smax and smax != smin else "") + " / yr"
            jobs.append({
                "title": (j.get("title") or "").strip(),
                "company": ((j.get("company") or {}).get("display_name") or "").strip(),
                "location": ((j.get("location") or {}).get("display_name") or "").strip(),
                "url": j.get("redirect_url", ""),
                "posted": (j.get("created") or "")[:10],
                "salary": salary,
                "source": "Adzuna SG",
            })
    print(f"  ✓ Adzuna: {len(jobs)} raw postings")
    return jobs


def fetch_muse_jobs() -> list[dict]:
    jobs = []
    for loc in MUSE_LOCATIONS:
        params = [f"location={urllib.parse.quote(loc)}", "page=1"]
        for lvl in MUSE_LEVELS:
            params.append(f"level={urllib.parse.quote(lvl)}")
        data = http_json("https://www.themuse.com/api/public/jobs?" + "&".join(params))
        if not isinstance(data, dict):
            continue
        for j in data.get("results", []):
            locs = ", ".join(l.get("name", "") for l in j.get("locations", []) if l.get("name"))
            jobs.append({
                "title": (j.get("name") or "").strip(),
                "company": ((j.get("company") or {}).get("name") or "").strip(),
                "location": locs,
                "url": ((j.get("refs") or {}).get("landing_page") or ""),
                "posted": (j.get("publication_date") or "")[:10],
                "salary": "",
                "source": "The Muse",
            })
    print(f"  ✓ The Muse: {len(jobs)} raw postings")
    return jobs


# ── Jobs: filtering and ranking ───────────────────────────────────────────────

def loc_has(loc: str, tokens: list[str]) -> bool:
    """Word-boundary match, so 'Seattle' doesn't read as 'sea' and 'Lagos' isn't 'sg'."""
    return any(re.search(r"\b" + re.escape(t) + r"\b", loc) for t in tokens)


def job_key(job: dict) -> str:
    """Stable identity for a posting: employer + title, not the URL.

    Boards that hand back the same careers-page URL for every role would
    otherwise poison the ledger and exclude that employer permanently.
    """
    company = re.sub(r"[^a-z0-9]", "", (job.get("company") or "").lower())
    title = re.sub(r"[^a-z0-9]+", " ", (job.get("title") or "").lower()).strip()
    return f"{company}|{title}"


def job_reject_reason(job: dict) -> str:
    """Why a posting was dropped — "" means it survives. Drives the funnel log."""
    title = (job.get("title") or "").lower()
    loc = (job.get("location") or "").lower()
    if not title or not job.get("url"):
        return "no title or url"
    if any(x in title for x in JOB_TITLE_EXCLUDE):
        return "title excluded"
    if not any(k in title for k in JOB_TITLE_KEYWORDS):
        return "title not senior enough"
    if loc:
        if loc_has(loc, JOB_LOCATION_EXCLUDE):
            return "location outside APAC"
        # "Remote" alone is not a location — it must be remote from somewhere he is.
        if not loc_has(loc, JOB_LOCATION_REQUIRED):
            return "location not APAC"
    posted = job.get("posted") or ""
    if len(posted) == 10:
        try:
            age = (datetime.now() - datetime.strptime(posted, "%Y-%m-%d")).days
            if age > JOB_MAX_AGE_DAYS:
                return f"older than {JOB_MAX_AGE_DAYS} days"
        except Exception:
            pass
    return ""


def job_is_relevant(job: dict) -> bool:
    return job_reject_reason(job) == ""


def job_score(job: dict) -> int:
    """Cheap pre-ranking so the shortlist sent to Claude is the strongest slice."""
    title = (job.get("title") or "").lower()
    loc = (job.get("location") or "").lower()
    score = 0
    for kw, pts in [("country manager", 30), ("general manager", 28), ("managing director", 28),
                    ("country director", 26), ("regional director", 22), ("country lead", 22),
                    ("head of", 16), ("vice president", 16), ("vp ", 16), ("director", 12),
                    ("partnerships", 8), ("channel", 6), ("commercial", 6)]:
        if kw in title:
            score += pts
            break
    if "singapore" in loc:
        score += 20
    elif any(k in loc for k in ("apac", "asia pacific", "asia-pacific", "southeast asia")):
        score += 14
    elif "asia" in loc:
        score += 8
    if job.get("source", "").endswith("careers"):
        score += 12          # target-company boards outrank aggregators
    if job.get("salary"):
        score += 3
    posted = job.get("posted") or ""
    if len(posted) == 10:
        try:
            age = (datetime.now() - datetime.strptime(posted, "%Y-%m-%d")).days
            score += max(0, 10 - age // 2)
        except Exception:
            pass
    return score


def collect_jobs(used_job_urls: list[str]) -> list[dict]:
    raw = fetch_target_company_jobs() + fetch_adzuna_jobs() + fetch_muse_jobs()
    # A URL that several postings share is a generic careers page, not a job
    # identity — matching on it would blacklist an employer's whole board.
    url_counts = {}
    for j in raw:
        u = (j.get("url") or "").split("?")[0]
        url_counts[u] = url_counts.get(u, 0) + 1
    generic_urls = {u for u, n in url_counts.items() if n > 1}
    if generic_urls:
        print(f"  · {len(generic_urls)} shared/generic URL(s) ignored for dedupe")

    seen = set(used_job_urls)
    out, dupes = [], set()
    funnel, near_misses = {}, []
    for j in raw:
        url = (j.get("url") or "").split("?")[0]
        key = job_key(j)
        already = key in seen or (url in seen and url not in generic_urls)
        if not url or already or key in dupes:
            funnel["already seen or duplicate"] = funnel.get("already seen or duplicate", 0) + 1
            continue
        reason = job_reject_reason(j)
        if reason:
            funnel[reason] = funnel.get(reason, 0) + 1
            # Roles in the right place but the wrong title are how we learn the
            # keyword list is too narrow — surface a few of them.
            if reason == "title not senior enough" and loc_has((j.get("location") or "").lower(),
                                                               ["singapore", "apac", "asia pacific"]):
                near_misses.append(f"{j.get('title')} — {j.get('company')} — {j.get('location')}")
            continue
        dupes.add(key)
        j["url"] = url
        out.append(j)
    out.sort(key=job_score, reverse=True)

    if funnel:
        print("  funnel: " + ", ".join(f"{v} {k}" for k, v in
                                       sorted(funnel.items(), key=lambda x: -x[1])))
    if near_misses:
        print(f"  near misses (right location, title didn't match — {len(near_misses)}):")
        for n in near_misses[:10]:
            print(f"    · {n}")
    print(f"  ✓ {len(out)} relevant, unseen postings after filtering")

    # Keep only the strongest few per employer — a 500-role board like Stripe's
    # would otherwise fill the entire shortlist on its own.
    per_company, capped = {}, []
    for j in out:
        c = (j.get("company") or "unknown").lower()
        if per_company.get(c, 0) >= MAX_PER_COMPANY_SHORTLIST:
            continue
        per_company[c] = per_company.get(c, 0) + 1
        capped.append(j)
    if len(capped) < len(out):
        print(f"  ✓ {len(capped)} after capping at {MAX_PER_COMPANY_SHORTLIST} per company "
              f"({len(per_company)} employers represented)")
    return capped[:JOB_CANDIDATES_TO_CLAUDE]


def parse_picks(txt: str):
    """Parse the ranking response. Returns a list (possibly empty), or None if unparseable."""
    if txt.startswith("```"):
        txt = re.sub(r"^```[a-z]*\n?|```$", "", txt, flags=re.MULTILINE).strip()
    try:
        data = json.loads(txt)
    except Exception:
        m = re.search(r"\[.*\]", txt, re.DOTALL)
        if not m:
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None
    return data if isinstance(data, list) else None


def no_jobs_note(scanned: int) -> str:
    return (f'<p class="job-none">Nothing worth applying to today — {scanned} '
            f'matching role{"s" if scanned != 1 else ""} scanned and none cleared the bar.</p>')


def build_jobs_of_day(candidates: list[dict]) -> tuple[str, list[str]]:
    """Ask Claude to pick the best JOBS_PER_DAY roles and say why. Returns (html, urls_used)."""
    if not candidates:
        print("  · no candidates reached the ranking step")
        return no_jobs_note(0), []

    listing = "\n\n".join(
        f"{i}. {c['title']}\n"
        f"   Company: {c.get('company') or 'unknown'}\n"
        f"   Location: {c.get('location') or 'not stated'}\n"
        f"   Posted: {c.get('posted') or 'unknown'}"
        + (f"\n   Salary: {c['salary']}" if c.get("salary") else "")
        + f"\n   Source: {c.get('source', '')}"
        for i, c in enumerate(candidates)
    )

    result = claude(
        f"CANDIDATE PROFILE:\n{CANDIDATE_PROFILE}\n\n"
        f"TODAY'S OPEN ROLES:\n{listing}\n\n"
        f"Pick the {JOBS_PER_DAY} roles most worth applying to today. Rank them best first. "
        "Favour genuine seniority and P&L or regional ownership over brand name. "
        "Pick from DIFFERENT employers — no two of your three from the same company. "
        "Drop anything that looks below the compensation floor or below Director level. "
        "If fewer than three are worth his time, return fewer — never pad the list.\n\n"
        "Return ONLY a JSON array, no prose, no code fences:\n"
        '[{"index": 0, "fit": "Strong fit", "why": "One sentence, max 25 words, '
        'naming the specific thing in his background that makes this land.", '
        '"angle": "One short sentence on the angle the application should lead with."}]\n'
        'Valid "fit" values: "Strong fit", "Good fit", "Worth a shot".',
        system="You are a blunt executive search partner who knows this candidate well. "
               "You do not flatter and you do not recommend roles that waste his time.",
        max_tokens=900,
    )

    picks = parse_picks(result.strip())
    if picks is None:
        # One retry with a stricter instruction before giving up. Never pad the
        # list with unvetted roles — a bad recommendation costs more than a gap.
        print("Warning: job ranking JSON failed — retrying once")
        retry = claude(
            f"CANDIDATE PROFILE:\n{CANDIDATE_PROFILE}\n\nROLES:\n{listing}\n\n"
            f"Return ONLY a JSON array of up to {JOBS_PER_DAY} objects with keys "
            '"index" (int), "fit", "why", "angle". No prose. No code fences. '
            "Different employer for each. Return [] if none are worth his time.",
            max_tokens=900,
        )
        picks = parse_picks(retry.strip())
    if picks is None:
        print("Warning: ranking failed twice — no jobs section today")
        return "", []
    if not picks:
        print("  · nothing in today's pool cleared the bar")
        return no_jobs_note(len(candidates)), []

    # Enforce employer diversity even if the model ignored the instruction.
    chosen, seen_companies, used_idx = [], set(), set()
    for p in picks:
        try:
            idx = int(p.get("index", -1))
            job = candidates[idx]
        except Exception:
            continue
        company = (job.get("company") or "").lower()
        if ONE_ROLE_PER_COMPANY and company and company in seen_companies:
            print(f"  · skipping second {job.get('company')} role ({job.get('title')})")
            continue
        chosen.append((job, p))
        seen_companies.add(company)
        used_idx.add(idx)
        if len(chosen) >= JOBS_PER_DAY:
            break

    # Deliberately no backfill. If only one role clears the bar, one card ships.
    if len(chosen) < JOBS_PER_DAY:
        print(f"  · only {len(chosen)} role(s) cleared the bar today — not padding")

    cards, urls = [], []
    for job, p in chosen:
        fit = (p.get("fit") or "").strip()
        why = (p.get("why") or "").strip()
        angle = (p.get("angle") or "").strip()
        meta = " · ".join(x for x in [job.get("company"), job.get("location"), job.get("salary")] if x)
        posted = f'<span class="job-posted">posted {job["posted"]}</span>' if job.get("posted") else ""
        cards.append(f"""<div class="job-card">
  <div class="job-meta">{meta}{" · " if meta and posted else ""}{posted}</div>
  <h4><a href="{job['url']}" target="_blank">{job['title']}</a></h4>
  {f'<span class="job-fit">{fit}</span>' if fit else ""}
  {f'<p class="job-why">{why}</p>' if why else ""}
  {f'<p class="job-angle"><em>Lead with:</em> {angle}</p>' if angle else ""}
  <p class="job-apply"><a href="{job['url']}" target="_blank">View &amp; apply →</a></p>
</div>""")
        # Record employer+title, not the URL — boards that reuse one careers-page
        # link for every role would otherwise blacklist themselves. Legacy URL
        # entries already in the ledger still match on the URL side.
        urls.append(job_key(job))

    return "\n".join(cards), urls


# ── Email / HTML Builder ──────────────────────────────────────────────────────

def build_html(skim, tech, laliga, sg, fr, ja, zh,
               quote="", photo="", poem="", jobs="", web_url="") -> str:
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
  /* Jobs of the day */
  .job-card {{ padding: 16px 0; border-bottom: 1px solid #f0ede6; }}
  .job-card:last-child {{ border-bottom: none; }}
  .job-meta {{ font-family: sans-serif; font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
               text-transform: uppercase; color: #aaa; margin-bottom: 4px; }}
  .job-posted {{ color: #bbb; letter-spacing: 1px; }}
  .job-card h4 {{ margin: 2px 0 6px; font-size: 16px; }}
  .job-fit {{ display: inline-block; font-family: sans-serif; font-size: 10px; font-weight: 700;
              letter-spacing: 1px; text-transform: uppercase; color: #6b5b00;
              background: #f5c842; padding: 3px 8px; border-radius: 3px; margin-bottom: 8px; }}
  .job-why {{ font-family: Georgia, serif; font-size: 14px; line-height: 1.65; color: #333; margin: 8px 0 4px; }}
  .job-angle {{ font-family: Georgia, serif; font-size: 13px; line-height: 1.6; color: #666; margin: 0 0 8px; }}
  .job-none {{ font-family: Georgia, serif; font-size: 14px; line-height: 1.7; color: #777;
               font-style: italic; margin: 0; }}
  .job-apply a {{ font-family: sans-serif; font-size: 11px; font-weight: 700; letter-spacing: 1px;
                  text-transform: uppercase; color: #1a1a2e; text-decoration: none;
                  border-bottom: 2px solid #f5c842; }}
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

  <!-- JOBS OF THE DAY -->
  {"" if not jobs else f'<div class="section"><div class="section-label">💼 Jobs of the Day</div><h2>Worth Applying To</h2>{jobs}</div>'}

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

def jobs_test(save: bool = True):
    """Dry run for the jobs section: fetch, filter, rank, print. No email, no other sections.

    Picked roles ARE written to used_stories.json by default, so a test run and the next
    morning's run don't hand you the same three jobs. Pass --no-save to leave the ledger alone.
    """
    print(f"🏷️  digest.py version: {SCRIPT_VERSION}")
    used = load_used()
    print("💼 Collecting jobs...")
    candidates = collect_jobs(used.get("job_urls", []))
    for c in candidates[:15]:
        print(f"  [{job_score(c):3}] {c['title']} — {c.get('company')} — "
              f"{c.get('location')} — {c.get('source')}")
    if not candidates:
        print("No candidates. Check source output above.")
        return
    html, urls = build_jobs_of_day(candidates)
    print("\n--- SECTION HTML ---\n")
    print(html)
    with open("jobs_preview.html", "w", encoding="utf-8") as f:
        f.write(build_html("", "", "", "", "", "", "", jobs=html))
    print("\n💾 Wrote jobs_preview.html — open it in a browser to see the styling.")
    if save:
        used["job_urls"] = used.get("job_urls", []) + urls
        save_used(used)
        print(f"💾 Recorded {len(urls)} job URLs in used_stories.json — they won't come back.")
    else:
        print("↩︎  --no-save: ledger untouched, these roles can appear again.")


def main():
    print(f"🏷️  digest.py version: {SCRIPT_VERSION}")
    # Load history to avoid repeats
    used = load_used()
    print(f"📚 Loaded used history: "
          f"{len(used.get('story_titles', []))} stories, "
          f"{len(used.get('quote_authors', []))} authors, "
          f"{len(used.get('poem_titles', []))} poems, "
          f"{len(used.get('job_urls', []))} jobs")

    print("💼 Collecting jobs...")
    try:
        job_candidates = collect_jobs(used.get("job_urls", []))
    except Exception as e:
        print(f"Warning: job collection failed: {e}")
        job_candidates = []

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

    try:
        jobs_html, job_urls = build_jobs_of_day(job_candidates)
    except Exception as e:
        print(f"Warning: job ranking failed: {e}")
        jobs_html, job_urls = "", []

    # Update used history
    used["story_titles"]  = used["story_titles"] + skim_titles + lang_titles
    used["quote_authors"] = used["quote_authors"] + ([quote_author] if quote_author else [])
    used["poem_titles"]   = used["poem_titles"]   + ([poem_title]   if poem_title   else [])
    used["job_urls"]      = used.get("job_urls", []) + job_urls
    save_used(used)
    print("💾 Saved used_stories.json")

    print("📧 Building HTML...")
    # HTML version (GitHub Pages) — ruby on top
    html_web = build_html(skim, tech, laliga, sg, fr, ja, zh,
                          quote=quote_html, photo=photo, poem=poem_html,
                          jobs=jobs_html, web_url="")

    # Email version — strip ruby entirely, add browser button
    ja_email = ruby_strip(ja)
    zh_email = ruby_strip(zh)
    html_email = build_html(skim, tech, laliga, sg, fr, ja_email, zh_email,
                            quote=quote_html, photo=photo, poem=poem_html,
                            jobs=jobs_html, web_url=GITHUB_PAGES_URL)

    # Save for GitHub Pages
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_web)
    print("💾 Saved docs/index.html")

    send_email(html_email)


if __name__ == "__main__":
    import sys
    if "--jobs-test" in sys.argv:
        jobs_test(save="--no-save" not in sys.argv)
    else:
        main()
