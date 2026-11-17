#!/usr/bin/env python3
"""MTG Arena Odds: follows Arena's Player.log and serves the odds panel at http://127.0.0.1:8765/.

Usage:
  python3 mtga/mtga_odds.py                      # finds Arena's log and opens the panel
  python3 mtga/mtga_odds.py --log PATH           # for a log somewhere else, like Steam on Linux
  python3 mtga/mtga_odds.py --replay PATH        # plays back a saved log, to try it without Arena
  python3 mtga/mtga_odds.py --record             # also saves your decisions for tools/train_mtga_policy.py
  python3 mtga/mtga_odds.py --model policy.json  # uses your trained model for suggestions

It only reads the log and only listens on this computer. Needs Python 3 and no other packages.
"""
import argparse, json, mimetypes, os, sys, threading, time, webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from decisions import Recorder
import policy

EXT = os.path.join(os.path.dirname(HERE), "extension")
DATA_DIR = os.path.join(os.path.expanduser("~"), ".mtga-odds")
HISTORY = os.path.join(DATA_DIR, "history.json")
HISTORY_MAX = 80
DECISIONS = os.path.join(DATA_DIR, "decisions.jsonl")
STARTER_MODEL = os.path.join(os.path.dirname(HERE), "models", "mtga-starter.json")
STATIC = {
    "/": (HERE, "panel.html"), "/panel.js": (HERE, "panel.js"), "/odds.js": (HERE, "odds.js"), "/panel-extra.css": (HERE, "panel-extra.css"),
    "/mtg-cards.js": (HERE, "mtg-cards.js"), "/mtg-decks.js": (HERE, "mtg-decks.js"),
    "/panel.css": (EXT, "panel.css"), "/fonts.css": (EXT, "fonts.css"),
}


def default_log():
    home = os.path.expanduser("~")
    places = [
        os.path.join(home, "Library", "Logs", "Wizards Of The Coast", "MTGA", "Player.log"),
        os.path.join(home, "AppData", "LocalLow", "Wizards Of The Coast", "MTGA", "Player.log"),
    ]
    for p in places:
        if os.path.exists(p): return p
    return places[1] if os.name == "nt" else places[0]


def load_history():
    try:
        with open(HISTORY, encoding="utf-8") as f: return json.load(f)
    except (OSError, ValueError):
        return []


def save_game(rec):
    rec["t"] = int(time.time() * 1000)
    h = load_history()
    h.append(rec)
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = HISTORY + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f: json.dump(h[-HISTORY_MAX:], f)
    os.replace(tmp, HISTORY)


def save_decision(rec):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(DECISIONS, "a", encoding="utf-8") as f: f.write(json.dumps(rec) + "\n")


class Follower(threading.Thread):
    """Reads whatever Arena adds to the log. Starting from the top means opening this mid-game loses nothing."""
    daemon = True

    def __init__(self, path, tracker, replay=False, speed=0.02, model=None):
        super().__init__()
        self.path, self.tracker, self.replay, self.speed = path, tracker, replay, speed
        self.found = False
        self.error = None
        self.done = False
        self.lock = threading.Lock()
        self.model = model
        self.make = lambda: Recorder(tracker.cards, tracker.on_game_end, tracker.on_decision, tracker.details)

    def read_view(self):
        with self.lock:
            v = self.tracker.view()
            v["suggest"] = self.suggestions(v)
        v.update(found=self.found, log_path=self.path, error=self.error, replay=self.replay, replay_done=self.done)
        return v

    def suggestions(self, v):
        """The model's ranking of the decision in front of you. It's never worked out in a game against a person."""
        if not self.model: return {"state": "nomodel"}
        if v["state"] != "duel" or not policy.suggestions_allowed(self.tracker.event, self.replay): return {"state": "locked" if v["state"] == "duel" else "idle"}
        g = self.tracker.game
        recs = [r for r in self.tracker.latest or [] if r["game"] == f"{g.match}#{g.number}"]
        out = []
        for r in recs:
            ranked = policy.rank(self.model, r)
            out.append({"kind": r["kind"], "attacker": (r.get("attacker") or {}).get("name"), "plays": [{"p": round(p, 3), "play": c["play"], "name": c.get("name"), "commander": bool(c.get("commander"))} for p, c in ranked[:6]]})
        return {"state": "ready", "decisions": out, "trained": self.model.get("decisions")}

    def run(self):
        pos, tail = 0, b""
        while True:
            try:
                size = os.path.getsize(self.path)
                self.found, self.error = True, None
                # Arena starts a new log each launch, and that's a smaller file than the one being followed.
                if size < pos:
                    pos, tail = 0, b""
                    with self.lock: self.tracker = self.make()
                if size > pos:
                    with open(self.path, "rb") as f:
                        f.seek(pos)
                        data = f.read(1 << 20)
                    pos += len(data)
                    lines = (tail + data).split(b"\n")
                    tail = lines.pop()
                    for raw in lines:
                        line = raw.decode("utf-8", "replace").rstrip("\r")
                        with self.lock:
                            try: self.tracker.feed(line)
                            except Exception as e:
                                self.error = f"{type(e).__name__}: {e}"
                        if self.replay and line.startswith("{") and "greToClientEvent" in line[:300]: time.sleep(self.speed)
                    continue
                if self.replay: self.done = True
            except FileNotFoundError:
                self.found = False
            except OSError as e:
                self.error = str(e)
            time.sleep(0.25)


def make_handler(follower):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def send_body(self, code, body, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            # A web page can't reach this by pointing its own domain at this computer.
            host = (self.headers.get("Host") or "").split(":")[0]
            if host not in ("127.0.0.1", "localhost"): return self.send_body(403, b"Forbidden", "text/plain")
            path = urlparse(self.path).path
            if path == "/api/view": return self.send_body(200, json.dumps(follower.read_view()).encode(), "application/json")
            if path == "/api/history": return self.send_body(200, json.dumps([] if follower.replay else load_history()).encode(), "application/json")
            if path in STATIC: base, name = STATIC[path]
            elif path.startswith("/fonts/") or path.startswith("/icons/"):
                base, name = EXT, os.path.join(*path.lstrip("/").split("/"))
                if ".." in name: return self.send_body(404, b"Not found", "text/plain")
            else: return self.send_body(404, b"Not found", "text/plain")
            try:
                with open(os.path.join(base, name), "rb") as f: body = f.read()
            except OSError:
                return self.send_body(404, b"Not found", "text/plain")
            ctype = mimetypes.guess_type(name)[0] or ("text/html" if name.endswith(".html") else "application/octet-stream")
            self.send_body(200, body, ctype + ("; charset=utf-8" if ctype.startswith(("text/", "application/javascript")) else ""))
    return Handler


def main():
    ap = argparse.ArgumentParser(description="Live odds for your opponent's hand and deck in MTG Arena.")
    ap.add_argument("--log", help="path to Player.log, if it isn't in the usual place")
    ap.add_argument("--replay", help="play back a saved log instead of following Arena")
    ap.add_argument("--speed", type=float, default=0.02, help="seconds between game messages when replaying")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--record", action="store_true", help="save your decisions to ~/.mtga-odds/decisions.jsonl")
    ap.add_argument("--model", help="a model from tools/train_mtga_policy.py, instead of the starter")
    ap.add_argument("--no-open", action="store_true", help="don't open the panel in a browser")
    args = ap.parse_args()
    path = args.replay or args.log or default_log()
    # A replay isn't a game you played, so it stays out of the decks the panel learns from.
    tracker = Recorder(on_game_end=None if args.replay else save_game, on_decision=save_decision if args.record and not args.replay else None)
    model_path = args.model or STARTER_MODEL
    model = policy.load(model_path) if os.path.exists(model_path) else None
    follower = Follower(path, tracker, replay=bool(args.replay), speed=args.speed, model=model)
    follower.start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(follower))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"MTG Arena Odds is at {url}\nReading {path}\nPress Ctrl+C to stop.", flush=True)
    if not args.no_open: webbrowser.open(url)
    try: server.serve_forever()
    except KeyboardInterrupt: pass


if __name__ == "__main__":
    main()
