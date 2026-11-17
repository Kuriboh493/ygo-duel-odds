"""Download the Goat format replays Format Library has published, with their plays, from DuelingBook.

Usage:
  python3 tools/fetch_replays.py                 # every published Goat replay not downloaded yet
  python3 tools/fetch_replays.py --limit 50      # just the 50 most recent

Format Library's replay list (formatlibrary.com/api/replays) names each replay's winner, loser, deck types
and event, and links to the replay on DuelingBook. DuelingBook gave this project an app key that lets it
download Goat format replays without the browser check; put it in tools/.cache/duelingbook_app (one line)
or the DUELINGBOOK_APP environment variable. It's not in the repository, which is public.

Each replay is saved as tools/.cache/replays/<duelingbook id>.json: DuelingBook's replay with Format
Library's entry under "fl". Ones already there are skipped, so the script can be stopped and run again.
tools/replay_records.py turns them into training decisions.
"""
import argparse, json, os, re, sys, time, urllib.error, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")
OUT = os.path.join(CACHE, "replays")
UA = {"User-Agent": "Mozilla/5.0 (ygo-duel-odds replay trainer)"}

def get_json(url, tries=4):
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                return json.load(r)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            if i == tries - 1: raise
            print(f"  retrying after {e}", flush=True)
            time.sleep(5 * (i + 1))

def app_key():
    k = os.environ.get("DUELINGBOOK_APP")
    path = os.path.join(CACHE, "duelingbook_app")
    if not k and os.path.exists(path): k = open(path, encoding="utf-8").read().strip()
    if not k: sys.exit("No DuelingBook app key: put it in tools/.cache/duelingbook_app or DUELINGBOOK_APP.")
    return k

def fl_list(fmt, limit):
    out, page = [], 1
    while True:
        q = urllib.parse.urlencode({"page": page, "limit": 100, "filter": f"formatName:eq:{fmt}"})
        rows = get_json(f"https://formatlibrary.com/api/replays/?{q}")
        if not isinstance(rows, list) or not rows: break
        out += rows
        if limit and len(out) >= limit: return out[:limit]
        page += 1
    return out

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--format", default="Goat", help="Format Library format name (the app key only covers Goat)")
    ap.add_argument("--limit", type=int, default=0, help="only the N most recent replays")
    ap.add_argument("--delay", type=float, default=1.5, help="seconds between DuelingBook requests, to go easy on the site")
    a = ap.parse_args()
    key = app_key()
    os.makedirs(OUT, exist_ok=True)
    rows = fl_list(a.format, a.limit)
    print(f"Format Library lists {len(rows)} {a.format} replays.", flush=True)
    got = skipped = failed = 0
    # A few entries hold more than one link in "url", so every replay id in it is taken.
    todo = [(rid, row) for row in rows for rid in re.findall(r"replay\?id=([\w-]+)", row.get("url") or "")]
    for i, (rid, row) in enumerate(todo, 1):
        path = os.path.join(OUT, f"{rid}.json")
        if os.path.exists(path): skipped += 1; continue
        try:
            d = get_json(f"https://www.duelingbook.com/view-replay?id={urllib.parse.quote(rid)}&app={urllib.parse.quote(key)}")
        except Exception as e:
            print(f"  {rid}: {e}", flush=True); failed += 1; time.sleep(a.delay); continue
        if not isinstance(d, dict) or not d.get("plays"):
            print(f"  {rid}: {str(d)[:120]}", flush=True); failed += 1
        else:
            d["fl"] = row
            tmp = path + ".part"
            with open(tmp, "w", encoding="utf-8") as f: json.dump(d, f, separators=(",", ":"))
            os.replace(tmp, path); got += 1
        if i % 25 == 0: print(f"  {i}/{len(todo)}: {got} downloaded, {skipped} already had, {failed} failed", flush=True)
        time.sleep(a.delay)
    print(f"Done: {got} downloaded, {skipped} already had, {failed} failed. Saved in {OUT}")

if __name__ == "__main__":
    main()
