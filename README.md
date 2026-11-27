# Accio

A small website for friends, named after the summoning charm: type what you're shopping for ("walking shoes", "air fryer under $100") and Claude reads this week's Black Friday roundups, then lists the best deals with each store's price side by side.

- **Invite codes.** Each friend gets their own code. No passwords.
- **Spending caps.** Each friend has a daily dollar cap ($1 by default) and the whole site has one too ($5). The server records the real cost of every search from Claude's usage numbers and stops new searches once a cap is reached. A friend can go over by at most one search.
- **Shared results.** A search anyone ran in the last 6 hours opens instantly for everyone, for free. "Air fryers", "air fryer deals" and "best Black Friday air fryer" count as the same search. If two friends search the same thing at once, only one search runs.
- **Compare stores.** Deal cards list every store's price with the lowest marked. The "Compare stores" view shows a table with one column per store, and "check ↗" links that look a product up at stores the articles didn't mention.

Searches use Claude Haiku 5.5, Anthropic's cheapest model, with web search. A new search measured about $0.12 (vs $0.39 on Sonnet 5.5), so a friend's $1 a day covers about 8 new searches. The cost of each search is shown after it runs and in `python manage.py usage`. To use Sonnet 5.5 instead, for more careful results, add `ACCIO_MODEL=claude-sonnet-5-5` to `.env`.

## Setup (once)

1. **Python 3.11 or newer.** macOS ships 3.9, which is too old.
2. **Install the dependencies:**
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **API key.** Create a key at https://platform.claude.com (Settings → API keys). Copy `.env.example` to `.env` and paste the key after `ANTHROPIC_API_KEY=`. In the Console, also set a monthly spend limit as a backstop.
4. **Friends.**
   ```bash
   python manage.py add-friend "Maya"            # prints Maya's code
   python manage.py add-friend "You" --cap 3.00  # a bigger cap for yourself
   ```
   Limits live in `friends.toml` (`daily_cap_per_friend`, `daily_cap_site`, `cache_hours`). To turn a code off, add `active = false` under that friend. A running site picks up friend changes within seconds; changes to `[limits]` need a restart.

## Run

```bash
source .venv/bin/activate
uvicorn accio.app:app --port 8000
```

Open http://localhost:8000 and enter a code.

## Share from your Mac (simplest)

Your Mac runs the site and Cloudflare's free quick tunnel gives it a public https link. No accounts needed.

1. Put `cloudflared` in a `bin/` folder here: download `cloudflared-darwin-arm64.tgz` (Apple silicon) or `cloudflared-darwin-amd64.tgz` (Intel) from https://github.com/cloudflare/cloudflared/releases and unpack it into `bin/`.
2. Double-click **Start Accio (Mac).command**. It prints the public link and a ready-to-text message for each friend with their own code. The first time, macOS may ask whether Terminal can access the Desktop folder: allow it.
3. Keep that window open. Your Mac stays awake while it's open; closing it takes Accio offline.

The link is different every time you start Accio, so text friends the new one (`python manage.py invite` prints the messages again).

## Admin

```bash
python manage.py friends        # names, codes and caps
python manage.py usage          # what each friend spent, per day
python manage.py invite [NAME]  # messages to text, with the current link and each code
```

## Put it online for free (Render + Neon)

Render runs the site from this GitHub repo on its free plan. Render's free servers sleep after 15 minutes without visitors and lose their files when they do, so spending and saved searches go in a free Neon Postgres database instead. Neither needs a credit card.

1. **Database (Neon).** Sign up at https://neon.com, create a project in a US region, and copy its connection string (it starts with `postgresql://`). It contains a password, so treat it like your API key.
2. **Website (Render).** Sign up at https://render.com with your GitHub account. Choose **New → Blueprint**, pick this repo, and Render reads `render.yaml`. When it asks, paste your Anthropic key into `ANTHROPIC_API_KEY` and the Neon string into `DATABASE_URL`.
3. **Invite codes.** In the new service, open **Environment → Secret Files**, add a file named `friends.toml`, paste in the contents of your local `friends.toml`, and save. Render redeploys.
4. **Share** the `https://….onrender.com` link and each friend's code.

Good to know:
- The first visit after the site has been asleep takes about a minute while Render wakes it.
- To add a friend later: run `python manage.py add-friend NAME` locally, paste the updated `friends.toml` into the Secret File again, and save.
- Free Render services are suspended for the rest of the month if they go over the workspace's free bandwidth. A friends-only site is far below that, but the Anthropic Console spend limit is still your real safety net.

## Files

| Path | What it does |
| --- | --- |
| `accio/app.py` | Web server: checks codes, enforces caps, serves the page |
| `accio/finder.py` | Asks Claude to search the web and report deals in a fixed shape; computes each search's cost |
| `accio/jobs.py` | Runs searches in the background and shares one search between friends |
| `accio/store.py` | Daily spending per friend and saved results: SQLite locally, Postgres (Neon) when `DATABASE_URL` is set |
| `accio/access.py` | Invite-code lookup and a brake on code guessing |
| `accio/static/index.html` | The page. Animations use Motion and AutoAnimate (both MIT) plus the browser's View Transitions |
| `render.yaml`, `.python-version` | Settings Render uses to run the site (no secrets) |
| `friends.toml`, `.env`, `data/` | Your private settings, key and database. Never committed |
