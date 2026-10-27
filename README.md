# YGO Duel Odds

Two single-page calculators for retro-format Yu-Gi-Oh! duels on DuelingBook. You log what your opponent does, and the page estimates what their face-down cards, hand and next draw are likely to be. It only uses public information.

- `goat-odds.html`: Goat format, with a sample Goat Control list.
- `edison-odds.html`: Edison format, with a sample Blackwing list and hand-trap tracking for Gorz, Tragoedia and Battle Fader.

Open either file in a browser. No build step or server is needed. Keep `cards.js` in the same folder.

## Browser extension

`extension/` is a browser extension that does the logging for you. It runs in a panel next to DuelingBook and updates the odds as the duel happens. You don't press anything to log draws, sets, activations, searches or turns.

### Installing

Download this repository (Code > Download ZIP) and unzip it, or clone it. Then:

| Browser | Steps | Where the panel opens |
|---|---|---|
| Chrome, Brave, Edge, Opera, Vivaldi | Open the extensions page (`chrome://extensions`, `brave://extensions`, `edge://extensions`, `opera://extensions` or `vivaldi://extensions`). Turn on Developer mode, click "Load unpacked" and choose the `extension` folder. | Side panel. On browsers without one, a small window. |
| Firefox 128 or newer | Open `about:debugging#/runtime/this-firefox`, click "Load Temporary Add-on" and choose `extension/manifest.json`. Firefox removes temporary add-ons when it restarts, so repeat this each time. If the panel says it can't see DuelingBook, press "Allow access to DuelingBook". | Sidebar |
| Safari | Not tested. Safari needs the extension converted with Xcode's `xcrun safari-web-extension-converter extension`. | — |

Then open DuelingBook, or reload it if it was already open, and click the extension's toolbar button to open the panel. Pick Goat or Edison at the top. You don't need your opponent's decklist: the panel guesses it as the duel goes. If you have their list, paste it under "Their deck" > "Opponent decklist" and the panel uses it instead.

The panel has four tabs. **Odds** has the at-a-glance threats, every face-down card, their hand and their next draw. **Their deck** has the deck guess and the decklist. **Log** shows the duel as the extension saw it. **Settings** has the "no response" options, tracking options and the problem report.

### Reporting a problem

Click "Report a problem" at the bottom of the panel. The report page attaches what the extension saw: versions, whether duel events are coming through, recent errors and the last few plays. Player names are replaced with "Me" and "Opponent" unless you untick that option. Nothing is sent until you choose to. "Open a GitHub issue" opens a prefilled issue on this repository for you to review and submit, and "Copy report" and "Download report" work without a GitHub account.

What it reads, all public information:

- Their hand size, deck size, every face-down card, and every card that is face-up, in the graveyard or banished.
- Cards they reveal, or add to their hand in a way both players can see, such as a search. These count as known cards in their hand.
- A face-down card that goes back to their hand unseen keeps its "was set" weighting.

It never reads the names of cards in their hand or face-down cards that DuelingBook hasn't shown to both players.

How the deck guess works:

- It starts from a mix of deck archetypes, plus decks from your past duels. An earlier game against the same opponent counts most. The archetypes are learned from Goat and Edison decklists and stored in `extension/learned.js`. Topping decks from Format Library count most, and decks published on YGOPRODeck fill in the rest. Without that file, it falls back to rough sketches written from memory in `extension/formats.js`.
- Each deck gives every card a chance of running 0, 1, 2 or 3 copies.
- Every card they show shifts the mix toward decks that run it. Every card that hasn't appeared yet, as more of their deck gets seen, makes it less likely they run many copies.
- Each simulated deal draws a full 40-card list from the guess before dealing out their hidden cards. That way, uncertainty about the list feeds into every number.
- "Their deck" shows which deck they're most likely on and the best-guess list. You can copy the guess into the decklist box to edit it.

"No response" evidence is logged automatically. When you attack, summon, or activate a spell or trap, and they make no play before your next action, their face-down cards get evidence against cards that would have responded. An attack also adds evidence against hand traps. Any play they make in between, including a chat message, cancels it. You can turn this off, set how strong the evidence is, and remove any single piece of evidence in the panel.

The extension hooks into DuelingBook's own page code. If DuelingBook changes that code, the panel says that duel events aren't coming through. Board reading may still work in that case, but "no response" won't be logged automatically.

## Any decklist

Paste a list of card names like `3 Book of Moon`, or paste or open a `.ydk` file. Every printed card is recognized through `cards.js`, a database built from the YGOPRODeck card API. Extra Deck and Side Deck cards are skipped. If the opponent reveals a card that isn't in their list, it's added automatically.

Common staples use hand-tuned values in each page. For every other card, the chance it gets set and the tags (stops attacks, answers summons, removal, negation, hand trap) are guessed from its text. You can adjust them in the page.

To refresh the card database after new sets come out:

```
curl -o cardinfo.json https://db.ygoprodeck.com/api/v7/cardinfo.php
python3 tools/build_cards.py cardinfo.json cards.js
cp cards.js extension/cards.js
```

## Retraining the deck archetypes

```
python3 tools/train_decks.py            # uses cached decklists if there are any
python3 tools/train_decks.py --refresh  # downloads the published decklists again
```

The script needs no extra packages. It fetches about one request a second. The first run downloads every topping decklist, roughly 3,500 of them, which takes about an hour. You can stop it at any time and rerun it, and it picks up where it left off. Everything is cached in `tools/.cache`.

It uses two sources:

- **Topping decks from Format Library.** These are tournament results labeled with their deck type. Each one counts as 4 published decks, with more for higher placements. Older events count for less, losing half their weight every 2 years. Each deck type with at least 8 topping decks becomes its own archetype.
- **Decks published on YGOPRODeck.** These are dropped if they have unknown cards, aren't 40 to 60 cards, include a card released after the format's cutoff, break the Goat banlist, or duplicate another deck.

A semi-supervised latent class model then fits a 0 to 3 copy distribution for every card in each archetype. Labeled topping decks train only their own archetype. Published decks are shared out among those archetypes and a few extra ones for decks that don't match a known type. The number of extra archetypes is picked by how well the model predicts held-out decks. Each archetype's starting weight in the panel is 80% its share of topping lists and 20% its share of published decks. The script writes `extension/learned.js`.

## How it works

Every card in the opponent's list that you haven't seen is treated as equally likely to be in their hand, face-down on the field, or in their deck. Face-down cards add rules: set monsters must be monsters, and traps are far more likely to be set than cards like Pot of Greed. Logging what they didn't do, such as ignoring an attack, lowers the odds of cards that would have responded. The page simulates 30,000 deals that fit everything logged and reports the results.

The sample decklists were written from memory. Paste your opponent's real list under "Opponent decklist".

Keyboard shortcuts: D draw, S set spell/trap, M set monster, E end turn, Z undo.
