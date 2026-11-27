# Accio

A small website for friends, named after the summoning charm: type what you're shopping for ("walking shoes", "air fryer under $100") and Claude reads this week's Black Friday roundups, then lists the best deals with each store's price side by side.

- **Invite codes.** Each friend gets their own code. No passwords.
- **Spending caps.** Each friend has a daily dollar cap ($1 by default) and the whole site has one too ($5). The server records the real cost of every search from Claude's usage numbers and stops new searches once a cap is reached. A friend can go over by at most one search.
- **Shared results.** A search anyone ran in the last 6 hours opens instantly for everyone, for free. "Air fryers", "air fryer deals" and "best Black Friday air fryer" count as the same search. If two friends search the same thing at once, only one search runs.
- **Compare stores.** Deal cards list every store's price with the lowest marked. The "Compare stores" view shows a table with one column per store, and "check ↗" links that look a product up at stores the articles didn't mention.

Searches use Claude Sonnet 5.5 with web search. A new search costs roughly $0.20–0.35 (measured cost is shown after each search and in `python manage.py usage`).

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
   Limits live in `friends.toml` (`daily_cap_per_friend`, `daily_cap_site`, `cache_hours`). To turn a code off, add `active = false` under that friend. Restart the server after editing.

## Run

```bash
source .venv/bin/activate
uvicorn accio.app:app --port 8000
```

Open http://localhost:8000 and enter a code.

## Admin

```bash
python manage.py friends   # names, codes and caps
python manage.py usage     # what each friend spent, per day
```

## Files

| Path | What it does |
| --- | --- |
| `accio/app.py` | Web server: checks codes, enforces caps, serves the page |
| `accio/finder.py` | Asks Claude to search the web and report deals in a fixed shape; computes each search's cost |
| `accio/jobs.py` | Runs searches in the background and shares one search between friends |
| `accio/store.py` | SQLite: daily spending per friend, and saved results |
| `accio/access.py` | Invite-code lookup and a brake on code guessing |
| `accio/static/index.html` | The page. Animations use Motion and AutoAnimate (both MIT) plus the browser's View Transitions |
| `friends.toml`, `.env`, `data/` | Your private settings, key and database. Not for sharing |
