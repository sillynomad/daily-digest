"""
Русский День — Daily Russian Reading Digest
For B2-level Russian learners.

Sections:
  1. Three Russian-language articles (world news, culture & arts, travel & lifestyle)
     — each with an English teaser + Russian excerpt
  2. Poem of the day (mix of classical, Soviet, and modern poets)
  3. Слово дня — one B2 word/phrase pulled from the day's articles

Stack: Python + Anthropic API (with web search) + Gmail SMTP
Delivery: GitHub Actions on a daily schedule
"""

import os
import json
import smtplib
import datetime
import anthropic
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ---------------------------------------------------------------------------
# Claude client
# ---------------------------------------------------------------------------
client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
MODEL = "claude-sonnet-4-20250514"
TODAY = datetime.date.today()
TODAY_READABLE = TODAY.strftime("%A, %d %B %Y")
TODAY_SHORT = TODAY.strftime("%d %B %Y")


# ---------------------------------------------------------------------------
# Content generation helpers
# ---------------------------------------------------------------------------

def _extract_json(content_blocks) -> dict:
    """Pull JSON out of a Claude response, stripping any markdown fences."""
    raw = ""
    for block in content_blocks:
        if hasattr(block, "text"):
            raw += block.text
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.rsplit("```", 1)[0].strip()
    return json.loads(raw)


def fetch_articles() -> list[dict]:
    """Use Claude + web search to find 3 real, recent Russian-language articles."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        system="""You are curating a daily Russian-language reading digest for a B2-level learner.
Find exactly 3 real, recently published articles written IN RUSSIAN — one per topic:
  1. World News / Current Affairs
  2. Culture & Arts
  3. Travel & Lifestyle

Preferred sources (use the Russian-language versions):
  News: meduza.io, rbc.ru, kommersant.ru, novayagazeta.ru
  Culture: arzamas.academy, kultура.рф, theoryandpractice.ru
  Travel/Lifestyle: vokrugsveta.ru, national-geographic.ru, afisha.ru

For each article return:
  - topic: exactly one of "World News", "Culture & Arts", "Travel & Lifestyle"
  - title: article headline in Russian
  - source: outlet name
  - url: direct article URL
  - english_teaser: 2–3 sentences in English summarising what the article is about
    (this helps the reader decide whether to open it)
  - russian_excerpt: 3–4 sentence excerpt or summary IN RUSSIAN, B2 accessible —
    avoid overly complex subordinate clauses; prefer active voice

Return ONLY valid JSON, no markdown fences, no preamble:
{
  "articles": [ { "topic": "...", "title": "...", "source": "...", "url": "...",
                  "english_teaser": "...", "russian_excerpt": "..." }, ... ]
}""",
        messages=[
            {
                "role": "user",
                "content": f"Today is {TODAY_SHORT}. Search and return 3 Russian articles as specified."
            }
        ],
    )
    data = _extract_json(response.content)
    return data["articles"]


def fetch_poem() -> dict:
    """Generate a poem of the day selection, mixing eras."""
    response = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system="""You are a literary curator selecting a Russian poem of the day for a B2-level learner.
Rotate across eras — classical (Pushkin, Lermontov, Tyutchev), Silver Age (Akhmatova, Tsvetaeva, Blok,
Pasternak), Soviet (Mayakovsky, Yesenin, Okudzhava), and modern/contemporary poets.
Choose poems that are evocative but not excessively long (ideally 8–24 lines).

Return ONLY valid JSON, no markdown fences:
{
  "poet_name":    "First Last (Имя Фамилия)",
  "era":          "e.g. Classical / Silver Age / Soviet / Contemporary",
  "title":        "Poem title in Russian, or 'Без названия' if untitled",
  "poem_text":    "Full poem in Russian, lines separated by \\n",
  "english_note": "2–3 sentences in English: who this poet is and why this poem is resonant or worth reading today"
}""",
        messages=[
            {
                "role": "user",
                "content": f"Today is {TODAY_SHORT}. Choose today's poem — vary the era from recent selections."
            }
        ],
    )
    return _extract_json(response.content)


def fetch_word_of_day(articles: list[dict]) -> dict:
    """Extract one interesting B2 word or phrase from the day's articles."""
    articles_text = "\n\n".join(
        f"[{a['topic']}] {a['title']}\n{a['russian_excerpt']}" for a in articles
    )
    response = client.messages.create(
        model=MODEL,
        max_tokens=500,
        system="""You are a Russian vocabulary coach for B2 learners.
From the provided article excerpts, pick ONE interesting word or phrase that is:
  - Genuinely useful at B2 level (not too simple, not obscure)
  - Idiomatic, culturally rich, or tricky to guess from roots alone

Return ONLY valid JSON, no markdown fences:
{
  "word":                "the word or phrase in Russian (Cyrillic)",
  "transliteration":     "romanised pronunciation (e.g. pozhaluysta)",
  "translation":         "concise English meaning",
  "usage_tip":           "one sentence in English on how/when this word is used",
  "example_ru":          "natural example sentence in Russian using this word",
  "example_en":          "English translation of the example sentence"
}""",
        messages=[
            {
                "role": "user",
                "content": f"Today's article excerpts:\n\n{articles_text}\n\nPick the best слово дня."
            }
        ],
    )
    return _extract_json(response.content)


# ---------------------------------------------------------------------------
# HTML email builder
# ---------------------------------------------------------------------------

TOPIC_META = {
    "World News":       {"icon": "🌍", "label": "Мировые новости"},
    "Culture & Arts":   {"icon": "🎭", "label": "Культура и искусство"},
    "Travel & Lifestyle": {"icon": "✈️", "label": "Путешествия"},
}


def build_html(articles: list[dict], poem: dict, word: dict) -> str:
    # --- Articles HTML ---
    articles_html = ""
    for a in articles:
        meta = TOPIC_META.get(a["topic"], {"icon": "📰", "label": a["topic"]})
        articles_html += f"""
      <div class="card article-card">
        <div class="tag">{meta['icon']}&nbsp;&nbsp;{meta['label']}</div>
        <h2 class="article-title">
          <a href="{a['url']}" class="article-link">{a['title']}</a>
        </h2>
        <p class="source-label">📎 {a['source']}</p>
        <div class="teaser-box">
          <span class="teaser-label">In a nutshell</span><br>
          {a['english_teaser']}
        </div>
        <p class="ru-text">{a['russian_excerpt']}</p>
        <a href="{a['url']}" class="read-link">Читать полностью →</a>
      </div>"""

    # --- Poem HTML ---
    poem_lines_html = poem["poem_text"].replace("\n", "<br>\n          ")

    return f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Русский День — {TODAY_SHORT}</title>
  <style>
    /* ── Reset & base ── */
    body, table, td, p, a {{ margin:0; padding:0; border:0; }}
    body {{
      font-family: 'Georgia', 'Times New Roman', serif;
      background: #1c1524;
      color: #e8e0f0;
    }}

    /* ── Outer wrapper ── */
    .wrapper {{
      max-width: 620px;
      margin: 0 auto;
      background: #1c1524;
    }}

    /* ── Header ── */
    .header {{
      background: #0f0b18;
      padding: 40px 44px 32px;
      border-bottom: 1px solid #2e2040;
      text-align: center;
    }}
    .header-eyebrow {{
      font-family: 'Courier New', Courier, monospace;
      font-size: 10px;
      letter-spacing: 4px;
      color: #9370db;
      text-transform: uppercase;
      margin-bottom: 12px;
    }}
    .header-title {{
      font-size: 34px;
      font-weight: normal;
      color: #f0eaff;
      letter-spacing: 5px;
      text-transform: uppercase;
      margin-bottom: 6px;
    }}
    .header-sub {{
      font-size: 12px;
      color: #7a6a90;
      font-style: italic;
      letter-spacing: 1px;
    }}
    .header-date {{
      display: inline-block;
      margin-top: 16px;
      font-family: 'Courier New', Courier, monospace;
      font-size: 10px;
      letter-spacing: 3px;
      color: #5a4a70;
      text-transform: uppercase;
    }}

    /* ── Section dividers ── */
    .section-label {{
      padding: 14px 44px;
      font-family: 'Courier New', Courier, monospace;
      font-size: 10px;
      letter-spacing: 4px;
      text-transform: uppercase;
      color: #9370db;
      background: #150f20;
      border-top: 1px solid #2e2040;
      border-bottom: 1px solid #2e2040;
    }}

    /* ── Cards ── */
    .card {{
      padding: 28px 44px;
      border-bottom: 1px solid #2a1f38;
    }}
    .article-card {{ background: #1c1524; }}
    .poem-card {{ background: #150f20; }}
    .word-card {{
      background: #0f0b18;
      border-bottom: none;
    }}

    /* ── Article elements ── */
    .tag {{
      font-family: 'Courier New', Courier, monospace;
      font-size: 10px;
      letter-spacing: 2px;
      color: #7b5ea7;
      text-transform: uppercase;
      margin-bottom: 10px;
    }}
    .article-title {{
      font-size: 19px;
      line-height: 1.45;
      margin-bottom: 6px;
      font-weight: normal;
    }}
    .article-link {{
      color: #d4bfff;
      text-decoration: none;
    }}
    .article-link:hover {{ text-decoration: underline; }}
    .source-label {{
      font-size: 11px;
      color: #5a4a70;
      font-family: 'Courier New', Courier, monospace;
      margin-bottom: 14px;
    }}
    .teaser-box {{
      background: #261840;
      border-left: 3px solid #9370db;
      padding: 11px 15px;
      font-size: 13px;
      color: #c0aee0;
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.65;
      border-radius: 0 6px 6px 0;
      margin-bottom: 16px;
    }}
    .teaser-label {{
      font-size: 10px;
      letter-spacing: 2px;
      text-transform: uppercase;
      color: #7b5ea7;
      font-family: 'Courier New', Courier, monospace;
      display: block;
      margin-bottom: 5px;
    }}
    .ru-text {{
      font-size: 15px;
      line-height: 1.85;
      color: #e8e0f0;
      margin-bottom: 14px;
    }}
    .read-link {{
      font-size: 12px;
      color: #9370db;
      text-decoration: none;
      font-family: Arial, Helvetica, sans-serif;
      letter-spacing: 0.5px;
    }}

    /* ── Poem elements ── */
    .poet-name {{
      font-size: 17px;
      color: #d4bfff;
      margin-bottom: 3px;
    }}
    .poem-era {{
      font-size: 10px;
      color: #5a4a70;
      font-family: 'Courier New', Courier, monospace;
      letter-spacing: 2px;
      text-transform: uppercase;
      margin-bottom: 5px;
    }}
    .poem-title {{
      font-size: 13px;
      color: #9370db;
      font-style: italic;
      margin-bottom: 16px;
    }}
    .poem-note {{
      background: #261840;
      border-left: 3px solid #9370db;
      padding: 11px 15px;
      font-size: 13px;
      color: #c0aee0;
      font-family: Arial, Helvetica, sans-serif;
      line-height: 1.65;
      border-radius: 0 6px 6px 0;
      margin-bottom: 20px;
    }}
    .poem-text {{
      font-size: 16px;
      line-height: 2.1;
      color: #f0eaff;
      font-style: italic;
    }}

    /* ── Word of the day ── */
    .word-header {{
      font-family: 'Courier New', Courier, monospace;
      font-size: 10px;
      letter-spacing: 4px;
      color: #9370db;
      text-transform: uppercase;
      margin-bottom: 14px;
    }}
    .word-main {{
      font-size: 32px;
      color: #d4bfff;
      margin-bottom: 4px;
    }}
    .word-translit {{
      font-size: 12px;
      color: #7a6a90;
      font-family: 'Courier New', Courier, monospace;
      margin-bottom: 8px;
      letter-spacing: 1px;
    }}
    .word-translation {{
      font-size: 14px;
      color: #c0aee0;
      font-family: Arial, Helvetica, sans-serif;
      margin-bottom: 10px;
    }}
    .word-tip {{
      font-size: 12px;
      color: #7a6a90;
      font-family: Arial, Helvetica, sans-serif;
      font-style: italic;
      margin-bottom: 14px;
      line-height: 1.6;
    }}
    .word-example-ru {{
      font-size: 15px;
      color: #e8e0f0;
      line-height: 1.7;
      margin-bottom: 5px;
    }}
    .word-example-en {{
      font-size: 12px;
      color: #5a4a70;
      font-family: Arial, Helvetica, sans-serif;
    }}

    /* ── Footer ── */
    .footer {{
      background: #0a0810;
      padding: 20px 44px;
      text-align: center;
      font-family: 'Courier New', Courier, monospace;
      font-size: 10px;
      color: #3a2e50;
      letter-spacing: 2px;
      text-transform: uppercase;
    }}
  </style>
</head>
<body>
<div class="wrapper">

  <!-- HEADER -->
  <div class="header">
    <div class="header-eyebrow">Daily Russian Digest</div>
    <div class="header-title">Русский День</div>
    <div class="header-sub">Read. Learn. Grow.</div>
    <div class="header-date">{TODAY_READABLE.upper()}</div>
  </div>

  <!-- ARTICLES -->
  <div class="section-label">📰&nbsp;&nbsp;Статьи дня — Today's Articles</div>
  {articles_html}

  <!-- POEM -->
  <div class="section-label">📖&nbsp;&nbsp;Стихотворение дня — Poem of the Day</div>
  <div class="card poem-card">
    <div class="poet-name">{poem['poet_name']}</div>
    <div class="poem-era">{poem['era']}</div>
    <div class="poem-title">«{poem['title']}»</div>
    <div class="poem-note">{poem['english_note']}</div>
    <div class="poem-text">
          {poem_lines_html}
    </div>
  </div>

  <!-- WORD OF THE DAY -->
  <div class="section-label">💡&nbsp;&nbsp;Слово дня — Word of the Day</div>
  <div class="card word-card">
    <div class="word-main">{word['word']}</div>
    <div class="word-translit">/{word['transliteration']}/</div>
    <div class="word-translation">{word['translation']}</div>
    <div class="word-tip">{word['usage_tip']}</div>
    <div class="word-example-ru">«{word['example_ru']}»</div>
    <div class="word-example-en">{word['example_en']}</div>
  </div>

  <!-- FOOTER -->
  <div class="footer">
    Русский День &nbsp;•&nbsp; {TODAY_SHORT} &nbsp;•&nbsp; Удачи в учёбе! 🇷🇺
  </div>

</div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Email sender
# ---------------------------------------------------------------------------

def send_email(html: str) -> None:
    sender   = os.environ["GMAIL_USER"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Русский День 🇷🇺 — {TODAY_SHORT}"
    msg["From"]    = f"Русский День <{sender}>"
    msg["To"]      = recipient

    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(sender, password)
        server.sendmail(sender, recipient, msg.as_string())

    print(f"✅  Digest sent to {recipient}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print(f"🔄  Building Русский День digest for {TODAY_SHORT}…")

    print("  • Fetching articles (web search)…")
    articles = fetch_articles()

    print("  • Selecting poem of the day…")
    poem = fetch_poem()

    print("  • Picking слово дня…")
    word = fetch_word_of_day(articles)

    print("  • Rendering HTML…")
    html = build_html(articles, poem, word)

    print("  • Sending email…")
    send_email(html)
    print("🎉  Done!")
