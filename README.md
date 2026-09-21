# ☀️ Daily Multilingual News Digest

A personalised morning email digest with world news, tech Asia, La Liga opinion, Singapore local news, and daily language practice in French, Japanese (N2), and Mandarin (A2).

---

## What you get every morning

| Section | Content | Language |
|---|---|---|
| 💼 Jobs of the Day | 3 roles worth applying to, ranked against your profile | English |
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

### Jobs of the Day

Three sources, merged and de-duplicated:

1. **Target companies' ATS boards** — Greenhouse, Lever and Ashby. `TARGET_COMPANIES` in
   `digest.py` is just a list of names; the script probes each company's board on first run
   and caches whatever it finds in `job_boards.json`. Companies with no public board are
   retried once a month. Add or remove names freely — no slugs to look up.
2. **Adzuna Singapore** — broad sweep, catches companies not on the list.
   Free key from [developer.adzuna.com](https://developer.adzuna.com), added as the
   `ADZUNA_APP_ID` and `ADZUNA_APP_KEY` repo secrets. Without them this source is skipped.
3. **The Muse** — free, no key.

Postings are filtered by title, seniority, location and age, pre-scored, then the top ~30 go
to Claude, which picks three and writes one line on why each fits and what to lead with.
Chosen roles are remembered in `used_stories.json` so they don't come back.

Tune the search by editing these in `digest.py`:

| What | Constant |
|---|---|
| Who you are / what you want | `CANDIDATE_PROFILE` |
| Company tier list | `TARGET_COMPANIES` |
| Titles to catch / ignore | `JOB_TITLE_KEYWORDS`, `JOB_TITLE_EXCLUDE` |
| Geography | `JOB_LOCATION_KEYWORDS`, `JOB_LOCATION_EXCLUDE` |
| How many, how fresh | `JOBS_PER_DAY`, `JOB_MAX_AGE_DAYS` |

Test it without sending an email: **Actions → Daily News Digest → Run workflow → tick
"jobs_only"**. The log shows what each source returned and which three were picked.
Locally: `python digest.py --jobs-test` (writes `jobs_preview.html`).

### Add or swap RSS feeds
Edit the `FEEDS` dictionary at the top of `digest.py`. Any RSS/Atom URL works.

### Add more language sections
Copy one of the language blocks in `build_language_corner()` and adjust the prompt for your target language and level.

---

## Cost estimate

Each daily run makes roughly 6–7 Claude API calls.
At `claude-sonnet` pricing, expect **~$0.10–0.25 per day** depending on article lengths.
That's roughly **$3–7/month** — cheaper than a single coffee.
