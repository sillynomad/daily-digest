# ☀️ Daily Multilingual News Digest

A personalised morning email digest with world news, tech Asia, La Liga opinion, Singapore local news, and daily language practice in French, Japanese (N2), and Mandarin (A2).

---

## What you get every morning

| Section | Content | Language |
|---|---|---|
| 🌍 The Skim | 5-bullet global news summary | English |
| 💻 Tech Asia | 3 top Asia tech stories | English |
| ⚽ La Liga Opinión | 3 opinion pieces from Marca, Sport, MD, As | Spanish |
| 🇸🇬 Singapore Kopi | 3 local SG headlines | English |
| 🇫🇷 Language Corner | Fun world story · advanced level | French |
| 🇯🇵 Language Corner | Fun world story · JLPT N2 + furigana + glossary | Japanese |
| 🇨🇳 Language Corner | Fun world story · HSK A2 + pinyin + glossary | Mandarin |

---

## Setup (one-time, ~20 minutes)

### Step 1 — Get an Anthropic API Key

1. Go to [console.anthropic.com](https://console.anthropic.com) and create a free account
2. Navigate to **API Keys** → **Create Key**
3. Copy and save the key (starts with `sk-ant-...`) — you won't see it again
4. Add a payment method (usage is pay-as-you-go; this digest costs roughly **$0.10–0.20/day**)

### Step 2 — Set up Gmail for sending

You need a Gmail **App Password** (not your regular Gmail password):

1. Go to your Google Account → **Security**
2. Enable **2-Step Verification** if not already on
3. Go to **Security** → **App Passwords**
4. Create an app password: App = "Mail", Device = "Other" → name it "Daily Digest"
5. Copy the 16-character password shown

> You can use any Gmail address as the sender — even the same one you're sending to.

### Step 3 — Create a GitHub repository

1. Go to [github.com](https://github.com) and sign up / log in (free)
2. Click **New Repository** → name it `daily-digest` → set to **Private** → Create
3. Upload all files from this folder into the repo (drag and drop works in the GitHub UI):
   - `digest.py`
   - `requirements.txt`
   - `.github/workflows/daily_digest.yml`

### Step 4 — Add your secrets to GitHub

In your GitHub repo, go to **Settings** → **Secrets and variables** → **Actions** → **New repository secret**

Add these four secrets:

| Secret name | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your `sk-ant-...` key from Step 1 |
| `EMAIL_SENDER` | Your Gmail address (e.g. `you@gmail.com`) |
| `EMAIL_RECIPIENT` | Where to deliver the digest (can be same address) |
| `EMAIL_APP_PASSWORD` | The 16-char app password from Step 2 |

### Step 5 — Test it manually

1. In your repo, go to **Actions** tab
2. Click **Daily News Digest** → **Run workflow** → **Run workflow**
3. Watch the logs — if it goes green, check your inbox! 🎉

After that, it runs automatically every morning at **7:00 AM Singapore time**.

---

## Customisation

### Change delivery time
Edit the cron line in `.github/workflows/daily_digest.yml`:
```yaml
- cron: '0 23 * * *'   # 23:00 UTC = 07:00 SGT
```
Use [crontab.guru](https://crontab.guru) to find the UTC equivalent of your preferred time.

### Add or swap RSS feeds
Edit the `FEEDS` dictionary at the top of `digest.py`. Any RSS/Atom URL works.

### Add more language sections
Copy one of the language blocks in `build_language_corner()` and adjust the prompt for your target language and level.

---

## Cost estimate

Each daily run makes roughly 6–7 Claude API calls.
At `claude-sonnet` pricing, expect **~$0.10–0.25 per day** depending on article lengths.
That's roughly **$3–7/month** — cheaper than a single coffee.
