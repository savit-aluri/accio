#!/bin/bash
# Double-click to put Accio online from this Mac.
# It starts the site, opens a free Cloudflare link to it, prints a message to text each
# friend, and keeps the Mac awake. Close this window (or press Ctrl+C) to take it offline.

cd "$(dirname "$0")" || exit 1
PORT=8000

fail() { echo; echo "  $1"; echo; read -r -p "  Press Return to close." _; exit 1; }

[ -x .venv/bin/uvicorn ] || fail "The Python environment is missing. See Setup in README.md."
grep -qE '^ANTHROPIC_API_KEY=.+' .env 2>/dev/null || fail "Add your Anthropic API key to the .env file first (after ANTHROPIC_API_KEY=)."
[ -f friends.toml ] || fail "No friends.toml yet. Run: .venv/bin/python manage.py add-friend NAME"

CLOUDFLARED=./bin/cloudflared
[ -x "$CLOUDFLARED" ] || CLOUDFLARED=$(command -v cloudflared)
[ -n "$CLOUDFLARED" ] || fail "cloudflared is missing. See 'Share from your Mac' in README.md."

if nc -z 127.0.0.1 "$PORT" 2>/dev/null; then
  fail "Something is already using port $PORT (maybe Accio is already running in another window)."
fi

mkdir -p data
rm -f data/public_url.txt
cleanup() {
  kill "$SERVER" "$TUNNEL" 2>/dev/null
  rm -f data/public_url.txt
  echo; echo "  Accio is offline."
}
trap cleanup EXIT
trap 'exit 0' INT TERM

echo "  Starting Accio…"
.venv/bin/uvicorn accio.app:app --host 127.0.0.1 --port "$PORT" --log-level warning &
SERVER=$!

"$CLOUDFLARED" tunnel --no-autoupdate --url "http://127.0.0.1:$PORT" > data/tunnel.log 2>&1 &
TUNNEL=$!

URL=""
for _ in $(seq 1 60); do
  URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' data/tunnel.log | head -1)
  [ -n "$URL" ] && break
  kill -0 "$TUNNEL" 2>/dev/null || break
  sleep 1
done
[ -n "$URL" ] || fail "Couldn't get a public link from Cloudflare. Details are in data/tunnel.log."
echo "$URL" > data/public_url.txt

echo
echo "  Accio is online at:  $URL"
echo "  (The link is new each time you start Accio, so text friends the new one.)"
echo
.venv/bin/python manage.py invite | sed 's/^/  /'
echo "  Keep this window open. Your Mac won't go to sleep while it is."
echo "  Close the window or press Ctrl+C to take Accio offline."
echo

# Keep the Mac awake for as long as the site runs.
caffeinate -ims -w "$SERVER"
