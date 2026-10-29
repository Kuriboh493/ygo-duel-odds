# YGO Duel Odds

A helper for playing Yu-Gi-Oh! **Goat** and **Edison** format on [DuelingBook](https://www.duelingbook.com/). It sits next to your duel and shows the odds for what your opponent might have: each face-down card, their hand, their next draw, and which deck they're playing. It updates on its own as you play. You don't have to type anything in.

![The panel during a duel](docs/panel-duel.png)

### [⬇ Download YGO Duel Odds](https://github.com/Kuriboh493/ygo-duel-odds/releases/latest/download/ygo-duel-odds.zip)

For Chrome, Edge, Brave, Opera, Vivaldi and Firefox. Using Safari on a Mac? [Download the Safari version](https://github.com/Kuriboh493/ygo-duel-odds/releases/latest/download/ygo-duel-odds-safari.zip) instead.

Then follow the [install steps](#install-it-about-5-minutes) below. It takes about 5 minutes.

It only uses what both players can see on screen. It never peeks at your opponent's hidden cards. Some tournaments don't allow helper tools, so check the rules before using it in an event.

- [Install it (about 5 minutes)](#install-it-about-5-minutes)
- [Use it](#use-it)
- [Turning it on partway through a duel](#turning-it-on-partway-through-a-duel)
- [Auto-play (Solo Mode)](#auto-play-solo-mode)
- [Something not working?](#something-not-working)
- [What it can and can't see](#what-it-can-and-cant-see)
- [For developers](#for-developers)

## Install it (about 5 minutes)

It works in **Chrome, Edge, Brave, Opera, Vivaldi**, **Firefox** and **Safari** on a Mac. Safari has [its own steps](#safari-on-a-mac). It isn't in any browser's add-on store yet, so there's no one-click install. You download a folder and point your browser at it, and the steps below walk through that.

### Step 1: Download it

1. Click this link: **[Download YGO Duel Odds](https://github.com/Kuriboh493/ygo-duel-odds/releases/latest/download/ygo-duel-odds.zip)**. A file called `ygo-duel-odds.zip` downloads, usually into your Downloads folder.
2. Unzip it:
   - **Windows:** right-click the file, choose **Extract All**, then **Extract**.
   - **Mac:** double-click the file.
3. You now have a folder called `ygo-duel-odds`. Leave it somewhere you won't delete it, like your Documents folder: the browser runs the extension from this folder.

### Step 2: Add it to your browser

**Chrome, Edge, Brave, Opera or Vivaldi**

1. Open a new tab and type the address for your browser into the address bar, then press Enter:
   - Chrome: `chrome://extensions`
   - Edge: `edge://extensions`
   - Brave: `brave://extensions`
   - Opera: `opera://extensions`
   - Vivaldi: `vivaldi://extensions`
2. Turn on **Developer mode**. It's a switch in the top-right corner of the page. In Edge it's on the left.
3. Click **Load unpacked**.
4. Find the **`ygo-duel-odds`** folder, click it once, and click **Select** (or **Open**).
5. "YGO Duel Odds" now appears in the list. It may show a yellow "warnings" note. That's expected and safe to ignore.
6. Pin it so it's easy to find. Click the puzzle-piece icon next to the address bar, then the pin next to "YGO Duel Odds". Its icon is a card with an eye on it.

**Firefox** (version 128 or newer)

1. Type `about:debugging#/runtime/this-firefox` into the address bar and press Enter.
2. Click **Load Temporary Add-on…**.
3. Open the `ygo-duel-odds` folder and pick the file called **`manifest.json`**.
4. Firefox only keeps add-ons installed this way until you close Firefox. Each time you reopen it, repeat these three steps.

**Safari:** see [Safari on a Mac](#safari-on-a-mac) below. It has its own download.

### Step 3: Open the panel

1. Go to [duelingbook.com](https://www.duelingbook.com/). If it was already open, reload the page so the extension can start.
2. Click the extension's icon, the card with an eye. A panel opens on the side of the window. In Firefox it's the sidebar. In browsers without a side panel, it opens as a small window.
3. **Firefox only:** if the panel says it can't see DuelingBook, click **Allow access to DuelingBook**, then reload the DuelingBook page.
4. Pick **Goat** or **Edison** from the menu in the top-right of the panel.

That's it. Start or watch a duel and the panel fills in by itself.

### Safari on a Mac

Safari installs extensions as a small Mac app. This one isn't signed with a paid Apple developer account, so macOS and Safari each ask you to confirm it once. You also have to tick one Safari setting each time you open Safari.

1. **Download:** [Download the Safari version](https://github.com/Kuriboh493/ygo-duel-odds/releases/latest/download/ygo-duel-odds-safari.zip). A file called `ygo-duel-odds-safari.zip` downloads. Double-click it to unzip it.
2. **Move it:** drag **YGO Duel Odds** (the app) into your **Applications** folder.
3. **Open the app once.** macOS will say it can't check the app for malicious software, because it isn't signed. To open it anyway:
   - **macOS 14 (Sonoma) or older:** hold **Control**, click the app, choose **Open**, then click **Open** again.
   - **macOS 15 (Sequoia) or newer:** double-click the app and close the warning. Open **System Settings** > **Privacy & Security**, scroll down, and click **Open Anyway** next to "YGO Duel Odds". Enter your password if asked.

   A small window opens. It's only the installer, so you can close it.
4. **Turn on unsigned extensions in Safari.**
   - Open **Safari** > **Settings** > **Advanced** and tick **Show features for web developers**.
   - A **Developer** tab appears in Settings. Open it and tick **Allow unsigned extensions**, then enter your password. On Safari 16 or older, this is in the **Develop** menu instead.
5. **Turn the extension on:** in Safari's **Settings** > **Extensions**, tick **YGO Duel Odds**.
6. **Allow it on DuelingBook:** go to [duelingbook.com](https://www.duelingbook.com/), click the extension's icon in the toolbar, and choose **Always Allow on This Website**.
7. **Open the panel:** click the icon again. In Safari, the panel opens in its own small window. Put it next to your DuelingBook window.

**Each time you reopen Safari**, it switches off "Allow unsigned extensions" again, so repeat step 4. The extension stays installed, and turns back on when you tick that box. Only an extension signed through Apple's paid developer program avoids this step.

## Use it

### The on/off switch

The switch at the top of the panel turns tracking on and off.

- **On** (green): it follows the duel and keeps the odds up to date.
- **Off** (grey): it reads nothing and saves nothing. The toolbar icon shows **OFF**, so you can tell at a glance.

![The panel with tracking off](docs/panel-off.png)

You can switch it on whenever you like, including in the middle of a duel. See [Turning it on partway through a duel](#turning-it-on-partway-through-a-duel).

### The four tabs

- **Odds**: what you need mid-duel.
  - **At a glance** has the big risks: whether their face-down spells or traps can stop an attack or answer a summon, and whether their hand holds removal.
  - **Face-down cards** lists each card they've set, with the cards it's most likely to be.
  - **Their hand** lists what they're likely holding. Cards you saw them add to their hand are marked "known".
  - **Their next draw** lists the cards they're most likely to draw next.
- **Their deck**: the deck they're most likely playing, the cards it usually runs, and a place to paste their decklist if you have it.
- **Log**: everything the extension has noticed, in order, newest first. The number on the tab counts new entries.
- **Auto**: [auto-play](#auto-play-solo-mode), which can make plays for you in Solo Mode.
- **Settings**: the "no response" options, tracking options, and **Report a problem**.

### Reading the numbers

- **"Royal Decree 14%"** under a face-down card means: out of every 100 situations that match everything seen so far, that card is Royal Decree in about 14.
- **"Holds one+ 25%"** in their hand means a 1-in-4 chance they're holding at least one copy.
- **Red** means likely, **orange** means maybe, and **green** means unlikely.

The numbers sharpen as the duel goes on and they show more of their deck.

### "What they didn't do"

When you attack, summon, or activate a spell or trap and your opponent doesn't respond, that's a clue. They probably don't have a card that would have stopped it. The extension notices this by itself and lowers the odds of those cards. The adjustment appears as a small tag under the face-down card, such as "Auto: Ignored an attack 70%".

- To undo one, click its tag.
- To rule out a card for one face-down card, click the **✕** next to that card.
- The buttons under **What they didn't do** on the Odds tab are for things the extension can't see, like "Left my backrow alone".
- You can turn the automatic version off, or make it stronger or weaker, in **Settings**.

### If you know their decklist

You don't need it, because the extension guesses their deck as they play. If you do have it:

1. Open the **Their deck** tab and click **Opponent decklist**.
2. Paste the list, one card per line (like `3 Book of Moon`), or click **Open a .ydk or text file**.
3. Click **Load list**.

To go back to guessing, choose **Guess it from what they play** in the same place.

## Turning it on partway through a duel

Switch it on at any point, or open the panel mid-duel, and it catches up by itself:

1. It reads the board as it is right now: their hand and deck size, every face-down card, and everything in the graveyard and banished.
2. It reads DuelingBook's own **Duel Log** for this game. Any card your opponent showed earlier counts as part of their deck. A card they added to their hand, and haven't used since, is marked as probably still in their hand.
3. The earlier plays show up in the **Log** tab, marked "Earlier".

There are two things it can't recover from before you switched it on:

- **"No response" moments.** It doesn't know which of your attacks they let through earlier. You can add these by hand with the buttons under **What they didn't do**.
- **Earlier face-down cards.** It doesn't know whether a card in their hand was once set face-down.

A note at the top of the Odds tab tells you when this happens.

## Auto-play (Solo Mode)

The **Auto** tab can make plays on DuelingBook for you: draw, summon, set, activate, attack, change phases and end the turn. It makes them through DuelingBook's own menus, exactly as if you'd clicked them.

![The Auto tab in a Solo Mode duel](docs/panel-autoplay.png)

**It only works in DuelingBook's Solo Mode**, where you play both sides yourself. In any duel against another person, it's locked and refuses every play. Having a program play for you against someone who thinks they're playing you would be unfair to them, and DuelingBook treats outside help as cheating.

It doesn't decide what to play yet. That part is left for later, so for now it comes with two simple settings:

- **Nothing (just watch)**: runs but never plays. Use it to check that auto-play can see the duel.
- **Test: draw, then end the turn**: on player 1's turns it draws a card and ends the turn, to check that plays go through.

To try it:

1. On DuelingBook, start a **Solo Mode** duel.
2. Open the **Auto** tab. The box at the top should say **Ready: Solo Mode duel**.
3. Under **Plays available now**, click any play. Auto-play makes it on DuelingBook, so you can see it working.
4. Or pick a setting under **What it should do**, choose how long to wait between plays, and press **Start**. Press **Stop** at any time.

Everything it does is listed under **What it did**.

## Something not working?

| What you see | What to do |
|---|---|
| "Looking for a DuelingBook tab…" | Open [duelingbook.com](https://www.duelingbook.com/) in the same browser window. If it's already open, reload it. |
| "Connected… Waiting for a duel to start" | This is normal until a duel begins. Start or watch a duel. |
| "Tracking is off" | Flip the switch at the top of the panel to **On**. |
| "The extension can't see DuelingBook yet" (Firefox) | Click **Allow access to DuelingBook**, then reload the DuelingBook page. |
| "Duel events aren't coming through" | DuelingBook may have updated. The board is still read, but "no response" isn't logged automatically. Please [report it](#reporting-a-problem). |
| The extension disappeared (Safari) | Safari turns off unsigned extensions whenever it quits. In Safari's **Settings** > **Developer**, tick **Allow unsigned extensions** again ([step 4](#safari-on-a-mac)). |
| The extension disappeared (Firefox) | Firefox removes add-ons installed this way when it closes. Repeat [Step 2](#step-2-add-it-to-your-browser). |
| I want the newest version | Download it again from the [download link](https://github.com/Kuriboh493/ygo-duel-odds/releases/latest/download/ygo-duel-odds.zip), replace your old `ygo-duel-odds` folder with the new one, then click the circular-arrow **reload** button on the extension in your browser's extensions page. |
| The numbers look wrong | Open **Settings** and click **Restart tracking from the current board**. If it's still wrong, [report it](#reporting-a-problem). |
| The panel is blank or stuck | Close the panel and open it again. If that doesn't help, reload DuelingBook. |

### Reporting a problem

Click **Report a problem** at the bottom of the panel.

1. Describe what went wrong in a sentence or two.
2. Check what's attached. It's a summary of what the extension saw: versions, recent errors and the last few plays. Player names are swapped for "Me" and "Opponent" unless you untick that box.
3. Choose how to send it:
   - **Open a GitHub issue**: opens a filled-in report on the project page. Read it, then press **Submit**. You need a free GitHub account.
   - **Copy report**: copies it so you can paste it into a message to whoever gave you the extension.
   - **Download report**: saves it as a file you can send.

Nothing is sent until you do one of these.

## What it can and can't see

It reads only what DuelingBook shows to both players:

- How many cards your opponent has in their hand and deck.
- Every face-down card's position.
- Every card that's face-up, in the graveyard or banished.
- Cards they reveal, or add to their hand where both players can see them, such as a search.
- DuelingBook's public duel log.

It never reads the names of cards in your opponent's hand, or of face-down cards that haven't been shown to both players. It doesn't read passwords, account details or private messages. Everything stays in your browser, except the decks from your past duels, which it keeps on your computer to make better guesses.

How the deck guess works: the extension learned what Goat and Edison decks look like from about 3,500 decklists that placed in tournaments, plus about 2,500 decklists people have posted online. Tournament decks count the most. During a duel, every card your opponent shows narrows down which of those decks they're likely playing. Decks you've faced before count too, and an earlier game against the same opponent counts the most.

## For developers

### What's in the repository

| Path | What it is |
|---|---|
| `extension/` | The browser extension (Manifest V3: Chromium, Firefox 128+, and Safari through `tools/build_safari.sh`). |
| `goat-odds.html`, `edison-odds.html` | The original single-page calculators. You log what the opponent does by hand. Open either in a browser, with `cards.js` in the same folder. Keyboard shortcuts: D draw, S set spell/trap, M set monster, E end turn, Z undo. |
| `cards.js` | Card database built from the YGOPRODeck API. `extension/cards.js` is a copy. |
| `tools/build_cards.py` | Builds `cards.js`. |
| `tools/train_decks.py` | Learns the deck archetypes in `extension/learned.js`. |
| `tools/make_icons.py` | Draws the toolbar icons. |
| `tools/build_safari.sh` | Builds the Safari app with Xcode. The GitHub workflows run it on a macOS runner. |

### How the extension works

- **`page-hook.js`** runs in DuelingBook's page context. It wraps the client's `duelResponse()`, through which every duel event passes, and reads the board from the client's `player1` and `player2` objects. It passes on only public information: names of face-up and revealed cards, never names from hand or face-down cards. It also returns the public text of the client's `duel_logs` when asked.
- **`tracker.js`** is a content script. It keeps the public identity of each card instance and the numbering of face-down cards. It detects "no response" by opening a window after your attack, summon or spell/trap activation, which closes on your next action or on any play by the opponent. When tracking starts partway through a duel, it catches up from `duel_logs`:
  - Every quoted card name in the opponent's lines is counted as at least one copy in their deck. Lines about targeting or attacking are skipped, because they name the other player's cards.
  - A card sent "to hand" and not mentioned since is softly marked as known in their hand. The mark moves off when they play a copy of it.
- **`panel.js`** runs the model and draws the panel.
  - With no decklist, the opponent's deck is a mixture of archetypes from `learned.js` and decks from your past duels. Each archetype gives every card a distribution over 0–3 copies.
  - Each card shown reweights the archetypes and updates copy counts through a binomial model of how much of the deck has been seen.
  - Each of 15,000 simulated deals samples a whole deck, conditioned on the deck size DuelingBook shows. It then deals the hidden cards with importance weights from the face-down and hand evidence.
- **Auto-play** has two halves:
  - `page-hook.js` is the executor. It lists the plays on offer by running the client's own menu builders (`cardMenuE`, `showDeckMenu`) with `showMenu` briefly swapped for a recorder, so nothing appears on screen. It makes a play the way a click does, through `cardMenuClicked`. Attacks on a monster go through `Send` with the chosen target, and phase plays use `Send` directly.
  - The executor refuses anything when `solo` isn't true, anything that isn't on that card's menu right now, and anything less than 300 ms after its last play.
  - `autoplay.js` runs the loop in the panel. A strategy is an entry in `STRATEGIES` with a `decide(state)` function that returns an action or `null`. The comment at the top of the file lists what `state` holds and what an action looks like.
- **`report.html`** gathers diagnostics from the panel and the DuelingBook tab, and opens a prefilled GitHub issue.

If DuelingBook changes its client, the panel says duel events aren't coming through. Board reading may keep working in that case.

### Releasing a new version

1. Raise `version` in `extension/manifest.json`, for example to `0.3.1`, and commit.
2. Tag and push: `git tag v0.3.1 && git push origin v0.3.1`.

The `Release` GitHub workflow checks that the tag matches the manifest. It then attaches two files to a release for that tag: `ygo-duel-odds.zip`, which is `extension/` zipped, and `ygo-duel-odds-safari.zip`, the Safari app built on a macOS runner. The README's download links always point at the newest release. The `Safari build` workflow also builds the Safari app on every branch push that changes the extension, and keeps it as a downloadable artifact on the run.

Safari doesn't support `world: "MAIN"` content scripts. When `page-hook.js` hasn't answered 1.5 seconds after load, `tracker.js` injects it from a web-accessible script tag instead. Safari also ignores `sidePanel`, `side_panel` and `sidebar_action`, so the toolbar button opens the panel in a window, or a tab if that fails.

### Refreshing the card database

```
curl -o cardinfo.json https://db.ygoprodeck.com/api/v7/cardinfo.php
python3 tools/build_cards.py cardinfo.json cards.js
cp cards.js extension/cards.js
```

Common staples use hand-tuned values in `extension/formats.js` and the two calculator pages. For every other card, the chance it gets set and its tags are guessed from its text: stops attacks, answers summons, removal, negation, hand trap.

### Retraining the deck archetypes

```
python3 tools/train_decks.py            # uses cached decklists if there are any
python3 tools/train_decks.py --refresh  # downloads the published decklists again
```

The script needs no extra packages. It fetches about one request a second. The first run downloads every topping decklist, roughly 3,500 of them, which takes about an hour. You can stop it at any time and rerun it, and it picks up where it left off. Everything is cached in `tools/.cache`.

It uses two sources:

- **Topping decks from Format Library.** These are tournament results labeled with their deck type. Each one counts as 4 published decks, with more for higher placements. Older events count for less, losing half their weight every 2 years. Each deck type with at least 8 topping decks becomes its own archetype.
- **Decks published on YGOPRODeck.** These are dropped if they have unknown cards, aren't 40 to 60 cards, include a card released after the format's cutoff, break the Goat banlist, or duplicate another deck.

A semi-supervised latent class model then fits a 0 to 3 copy distribution for every card in each archetype. Labeled topping decks train only their own archetype. Published decks are shared out among those archetypes and a few extra ones for decks that don't match a known type. The number of extra archetypes is picked by how well the model predicts held-out decks. Each archetype's starting weight in the panel is 80% its share of topping lists and 20% its share of published decks.
