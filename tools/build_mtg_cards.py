"""Build mtga/mtg-cards.js, the MTG Arena card database, from Scryfall's bulk data.

Usage:
  python3 tools/build_mtg_cards.py

Downloads Scryfall's default-cards file (about 80 MB) into tools/.cache, keeps every card on Arena,
and tags each one from its text: counterspell, instant-speed removal, combat trick, flash, board wipe.
The tags are guesses from the wording, so a few cards will be off.
"""
import gzip, json, os, re, sys, urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, "tools", ".cache", "mtg")
UA = {"User-Agent": "mtga-odds-builder/0.1", "Accept": "application/json"}

COUNTER = re.compile(r"counter target ([a-z, -]*?)(?:spell|or ability|ability)")
REMOVAL = re.compile(
    r"(destroy|exile) (up to (one|two) )?(another )?target ((?!card)[a-z ,-]{0,40})?(creature|permanent|planeswalker)(?! card)"
    r"|deals? (\d+|x|that much) damage to (any target|target creature|target (attacking|blocking) creature)"
    r"|target creature( an opponent controls)? gets [-−](\d+|x)/[-−](\d+|x)"
    r"|return (up to one )?target ((?!card)[a-z -]{0,30})?(creature|permanent|nonland permanent) to its owner's hand")
TRICK = re.compile(r"target creature( you control)? (gets \+|gains? [a-z, ]*(indestructible|hexproof|first strike|double strike|protection))")
WIPE = re.compile(
    r"(destroy|exile) (all|each) (other )?(creatures?|nonland permanents?|artifacts and creatures|creatures and)"
    r"|(all|each) creatures? gets? [-−]"
    r"|deals? (\d+|x) damage to each (creature|other creature)"
    r"|return all (creatures|nonland permanents)")


def code(type_line):
    t = type_line.split(" // ")[0]
    for word, c in (("Land", "L"), ("Creature", "C"), ("Instant", "I"), ("Sorcery", "S"), ("Planeswalker", "P"), ("Battle", "B"), ("Artifact", "A"), ("Enchantment", "E")):
        if word in t: return c
    return "?"


def tags_for(c):
    text = " ".join(filter(None, [c.get("oracle_text")] + [f.get("oracle_text") for f in c.get("card_faces", [])])).lower()
    # Reminder text describes other cards' rules, so it doesn't count.
    text = re.sub(r"\([^)]*\)", "", text)
    front = c["type_line"].split(" // ")[0]
    flash = "Flash" in (c.get("keywords") or [])
    instant = "Instant" in c["type_line"] or flash
    tags = ""
    if instant:
        m = COUNTER.search(text)
        if m:
            what = m.group(1)
            if "noncreature" in what or "instant" in what or "sorcery" in what or "ability" in what: tags += "n"
            elif "creature" in what: tags += "c"
            else: tags += "cn"
        if REMOVAL.search(text): tags += "r"
        if TRICK.search(text): tags += "t"
    if flash and "Instant" not in front and "Land" not in front: tags += "f"
    if WIPE.search(text): tags += "w"
    return tags


def cost_of(c):
    if c.get("mana_cost"): return c["mana_cost"]
    faces = c.get("card_faces") or [{}]
    return faces[0].get("mana_cost", "")


def cmc_of(c):
    # A double-faced card's cmc is its front's. Adventure and split costs use the whole card, so read the front's symbols.
    total = 0
    for sym in re.findall(r"\{([^}]+)\}", cost_of(c).split(" // ")[0]):
        if sym.isdigit(): total += int(sym)
        elif sym != "X": total += 1
    return total


def download():
    os.makedirs(CACHE, exist_ok=True)
    req = urllib.request.Request("https://api.scryfall.com/bulk-data", headers=UA)
    bulk = {b["type"]: b for b in json.load(urllib.request.urlopen(req))["data"]}["default_cards"]
    url = bulk.get("jsonl_download_uri") or bulk["download_uri"]
    path = os.path.join(CACHE, os.path.basename(url))
    if not os.path.exists(path):
        print("Downloading", url)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA)) as r, open(path + ".part", "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk: break
                f.write(chunk)
        os.replace(path + ".part", path)
    return path


def base_name(name):
    # Arena's rebalanced Alchemy printings are named "A-Card". They count as the same card in a deck.
    return re.sub(r"^A-", "", name)


def main(dst):
    src = download()
    cards = {}
    with gzip.open(src, "rt", encoding="utf-8") as f:
        for line in f:
            c = json.loads(line)
            if not (c.get("arena_id") or "arena" in c.get("games", [])): continue
            if c.get("layout") in ("token", "double_faced_token", "emblem", "art_series"): continue
            name = base_name(c["name"])
            e = cards.get(name)
            if not e:
                e = cards[name] = {"ids": set(), "c": c}
            # The original printing's rules win over a rebalanced one.
            if e["c"]["name"].startswith("A-") and not c["name"].startswith("A-"): e["c"] = c
            if c.get("arena_id"): e["ids"].add(c["arena_id"])
    lines = []
    for name in sorted(cards):
        e = cards[name]
        # Scryfall can be late with a new set's Arena ids. Those cards still belong in decklists.
        if "\t" in name: continue
        c = e["c"]
        produced = "".join(x for x in "WUBRGC" if x in (c.get("produced_mana") or []))
        lines.append("\t".join([name, code(c["type_line"]), str(cmc_of(c)), cost_of(c).split(" // ")[0], produced, tags_for(c), ",".join(map(str, sorted(e["ids"])))]))
    with open(dst, "w", encoding="utf-8") as f:
        f.write("// Generated by tools/build_mtg_cards.py from Scryfall's bulk data. Do not edit by hand.\n")
        f.write("// Fields: name, type (L land, C creature, I instant, S sorcery, P planeswalker, B battle, A artifact, E enchantment), mana value, mana cost, mana produced, tags (c counters creature spells, n counters other spells, r instant removal, t combat trick, f flash, w board wipe), Arena ids\n")
        f.write("window.MTG_CARD_DATA = " + json.dumps("\n".join(lines), ensure_ascii=False) + ";\n")
    print(f"{len(lines)} cards written to {dst}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "mtga", "mtg-cards.js"))
