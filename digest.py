#!/usr/bin/env python3
"""
Daily Multilingual News Digest
Fetches RSS feeds, summarizes with Claude, sends via email.
"""

import os
import re
import smtplib
import feedparser
import anthropic
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
GITHUB_PAGES_URL = os.environ.get("GITHUB_PAGES_URL", "")


def ruby_to_parens(html: str) -> str:
    """Convert <ruby>漢字<rt>かんじ</rt></ruby> to 漢字(かんじ) for email clients."""
    return re.sub(r'<ruby>(.*?)<rt>(.*?)</rt></ruby>', r'\1(\2)', html, flags=re.DOTALL)


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
        "Pick the 3 most interesting and write a short digest. For each: "
        "<h4> title (hyperlinked to URL), then 2 sentences explaining why it matters. "
        "Return valid HTML.",
        system="You are a sharp tech journalist covering Asia's startup and tech ecosystem."
    )


def build_laliga_opinion(articles: list[dict]) -> str:
    raw = articles_to_text(articles)
    return claude(
        f"Aquí hay artículos de opinión sobre fútbol español de Marca, Sport, Mundo Deportivo y As:\n\n{raw}\n\n"
        "Selecciona las 3 piezas de opinión más interesantes y escribe un resumen en español de cada una: "
        "título en <h4> con enlace, luego 2-3 frases que capturen el argumento principal del columnista. "
        "Devuelve HTML válido.",
        system="Eres un periodista deportivo español especializado en análisis y opinión sobre La Liga."
    )


def build_singapore(articles: list[dict]) -> str:
    raw = articles_to_text(articles)
    return claude(
        f"Here are Singapore local news articles:\n\n{raw}\n\n"
        "Pick the 3 most relevant and write a short local news digest. For each: "
        "<h4> title (hyperlinked), then 2 sentences of context. Return valid HTML.",
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

    import json
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


# ── Email Builder ─────────────────────────────────────────────────────────────

def build_html(skim, tech, laliga, sg, fr, ja, zh, web_url="") -> str:
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
  .section h2 {{ margin: 0 0 16px; font-size: 18px; }}
  .section h4 {{ margin: 16px 0 4px; font-size: 15px; }}
  .section h4 a {{ color: #1a1a2e; }}
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
    skim   = build_skim(general_articles)
    tech   = build_tech_asia(tech_articles)
    laliga = build_laliga_opinion(laliga_articles)
    sg     = build_singapore(sg_articles)
    fr, ja, zh = build_language_corner(quirky_articles, already_covered=general_articles)

    print("📧 Sending email...")
    # HTML file (GitHub Pages) — full ruby tags for furigana/pinyin rendered on top
    html_web = build_html(skim, tech, laliga, sg, fr, ja, zh, web_url="")

    # Email — convert ruby tags to parentheses (Gmail strips ruby)
    ja_email = ruby_to_parens(ja)
    zh_email = ruby_to_parens(zh)
    html_email = build_html(skim, tech, laliga, sg, fr, ja_email, zh_email, web_url=GITHUB_PAGES_URL)

    # Save HTML for GitHub Pages (workflow will commit this file)
    os.makedirs("docs", exist_ok=True)
    with open("docs/index.html", "w", encoding="utf-8") as f:
        f.write(html_web)
    print("💾 Saved docs/index.html for GitHub Pages")

    send_email(html_email)


if __name__ == "__main__":
    main()
