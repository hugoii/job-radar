# job-radar

Watches curated new-grad job lists and emails you the moment fresh matches appear. Runs on GitHub Actions every 15 minutes — your PC does not need to be on.

## Sources

- [SimplifyJobs/New-Grad-Positions](https://github.com/SimplifyJobs/New-Grad-Positions) — community-maintained NG board with direct apply links

(Adding Greenhouse / Lever / Ashby company boards is easy — append another `fetch_*` function to `sources.py` and add it to `SOURCES`.)

## Why not scrape LinkedIn directly

LinkedIn has aggressive anti-bot detection (CAPTCHA, IP bans, account suspensions). A 24/7 scraper will get your LinkedIn account suspended within days. SimplifyJobs already aggregates from LinkedIn + many other sources with *direct apply links*, which are more useful than the LinkedIn redirect anyway.

## Setup

### 1. Generate a Gmail App Password

Regular Gmail passwords no longer work for SMTP — you need an App Password (16 chars).

1. Enable 2-Step Verification at https://myaccount.google.com/security
2. Generate an App Password at https://myaccount.google.com/apppasswords (pick "Mail" / "Other")
3. Copy the 16-char string (e.g. `abcd efgh ijkl mnop`).

### 2. Push this folder to GitHub

```powershell
cd C:\Users\zjh14\job-radar
git init
git add .
git commit -m "init job-radar"
gh repo create job-radar --public --source=. --push
```

Public repo is recommended → unlimited GitHub Actions minutes. If you really want private, change the cron in `.github/workflows/check-jobs.yml` from `*/15` to `*/20` to stay inside the 2000 min/month free quota.

### 3. Add the three secrets

In your repo: **Settings → Secrets and variables → Actions → New repository secret**

| Name | Value |
|---|---|
| `GMAIL_FROM` | Your Gmail address (the one you generated the app password for) |
| `GMAIL_TO` | Where alerts go (can be the same address) |
| `GMAIL_APP_PASSWORD` | The 16-char app password from step 1 (spaces OK) |

### 4. Enable Actions and test once manually

1. **Actions** tab → if prompted, click "I understand my workflows, go ahead and enable them"
2. Click the "Check new jobs" workflow on the left → **Run workflow** (manual trigger)
3. Wait ~30s. First run will email you ALL recent matches (≤7 days old) since `seen_jobs.json` starts empty — could be 30-100+ jobs. That is normal.
4. After the first run, the cron fires every 15 min and only NEW jobs trigger emails.

## Customizing

Edit `config.yml`:

| Key | Meaning |
|---|---|
| `max_days_old` | Drop postings older than N days |
| `keywords` | Role title must match at least one (word-boundary, case-insensitive) |
| `exclude_keywords` | Reject if role contains any (substring match) |
| `location_exclude` | Reject if location contains any (substring match) |

Commit the change → next cron run picks it up. No redeploy needed.

## Local testing

```powershell
cd C:\Users\zjh14\job-radar
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

$env:GMAIL_FROM = "you@gmail.com"
$env:GMAIL_TO = "you@gmail.com"
$env:GMAIL_APP_PASSWORD = "abcd efgh ijkl mnop"

$env:DRY_RUN = "1"   # set to skip the email send and just print what would be sent
python main.py
```

`DRY_RUN=1` makes the script print the jobs it *would* email and skip the SMTP send entirely. Drop the `DRY_RUN` line to actually send (you'll still need the three GMAIL env vars set).

## Cost

Free. Public repo = unlimited Actions minutes. Private repo on free tier = 2000 min/month (a 15-min cron at ~30s/run uses ~1450 min/month, fits).
