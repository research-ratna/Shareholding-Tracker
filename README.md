# Shareholding tracker

Tracks whether the investors (and their specific holding entities) on your
watchlist are new to, adding to, or exiting a stock — based on each listed
company's quarterly ≥1% shareholding pattern disclosure (SEBI LODR
Regulation 31). Not bulk/block deals, not real-time, no alerts — a
browsable, filterable record you check when you want to.

```
scraper/     Python: fetches filings from NSE, parses named holders,
             matches them to your watchlist, works out new/added/sold/
             existing, writes to Supabase. Runs on a schedule via GitHub
             Actions - entirely free at this scale.
supabase/    schema.sql - the database tables.
web/         Next.js dashboard - Input tab (watchlist) and Data
             repository tab (the filterable, groupable output).
```

Total cost to run this: **$0/month**, on Supabase's and Vercel's free
tiers and GitHub Actions' free allowance for public repos.

---

## 1. Set up Supabase (free)

1. Create a project at [supabase.com](https://supabase.com) — no credit card needed.
2. Open the SQL Editor and run everything in `supabase/schema.sql`.
3. Go to Project Settings → API. You'll need three values from here:
   - **Project URL** → used as `SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_URL`
   - **anon / public key** → used as `NEXT_PUBLIC_SUPABASE_ANON_KEY` (safe to expose in the browser)
   - **service_role key** → used as `SUPABASE_SERVICE_KEY` (secret — only the scraper uses this, never the browser)

## 2. Set up the scraper (GitHub Actions)

1. Push this whole folder to a new GitHub repo. Public repos get unlimited
   free Actions minutes; this scraper only touches public regulatory
   filings, so there's no real downside to public. If you'd rather keep it
   private, the free 2,000 min/month allowance comfortably covers a daily
   run (this takes roughly 15-20 minutes per run).
2. In the repo: Settings → Secrets and variables → Actions → New repository secret. Add:
   - `SUPABASE_URL`
   - `SUPABASE_SERVICE_KEY`
3. That's it — `.github/workflows/scrape.yml` is already set up to run daily
   and can also be triggered manually from the Actions tab
   ("Run workflow").

## 3. Set up the dashboard (Vercel, free)

1. Import the repo into [vercel.com](https://vercel.com), set the project's
   **root directory to `web`**.
2. Add environment variables in the Vercel project settings:
   - `NEXT_PUBLIC_SUPABASE_URL`
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY`
3. Deploy. You'll get a free `*.vercel.app` URL.

(To run it locally instead: `cd web && cp .env.local.example .env.local`,
fill in the two values, then `npm install && npm run dev`.)

## 4. Add your watchlist

Open the deployed dashboard's **Input** tab and either upload an Excel file
with `investor` and `entity` columns (one row per entity — same investor
name repeated across rows if they use several entities), or add rows one
at a time. Nothing gets scraped for an entity until it's on this list.

## 5. Run it

Go to the repo's **Actions** tab → "Scrape shareholding filings" → **Run
workflow**, to do a first run without waiting for the schedule. Then check
the **Data repository** tab on the dashboard.

---

## Before you trust this at scale: validate the parser

I built `scraper/xbrl_parser.py` without live network access to
nseindia.com, so while the *logic* is tested (see `test_xbrl_parser.py`,
which passes against a real filing's structure I fetched separately), the
exact XBRL tag names it guesses at (`_classify_tag()` in that file) are
not independently confirmed. Raw XBRL is what NSE actually serves for
most filings, so this matters.

**Do this once, before your first real run:**

```bash
cd scraper
pip install -r requirements.txt
python3 -c "
from nse import NSE
with NSE(download_folder='.', server=False) as nse:
    records = nse.shareholding('RELIANCE')  # or any symbol you like
    path = nse.download_document(records[0]['xbrl'])
    print('Downloaded:', path)
"
python3 -c "
from xbrl_parser import parse_filing
from pathlib import Path
rows = parse_filing(Path('SHP_....xml'))  # use the filename printed above
for r in rows:
    print(r)
"
```

Compare the printed rows against what that company actually filed (visible
on the NSE website, under the same shareholding-pattern page). If rows
come back empty or the numbers look wrong, the fix is almost always
widening the keyword lists in `_classify_tag()` — the grouping logic
itself shouldn't need to change. Happy to help debug this directly against
a real downloaded file if you hit this.

## What this doesn't cover yet

- **BSE-only companies** (not cross-listed on NSE): the schema and
  matching/diff logic are exchange-agnostic, but `nse_client.py` only
  talks to NSE. Adding BSE means writing an equivalent to
  `nse_client.py` against the `BseIndiaApi` package and feeding its
  output through the same `xbrl_parser.py` / `matcher.py` / `diff.py`.
- **Below-1% stakes**: invisible in this data source by regulatory
  design, not a gap in this code — true for any tool built on this
  disclosure.
- **Exact transaction dates**: the date shown is the quarter-end the
  filing covers, not the day a trade happened. That's what your separate
  bulk/block tracker is for.
