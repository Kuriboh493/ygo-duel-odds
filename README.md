# YGO Duel Odds

Two single-page calculators for retro-format Yu-Gi-Oh! duels on DuelingBook. You log what your opponent does, and the page estimates what their face-down cards, hand and next draw are likely to be. It only uses public information.

- `goat-odds.html`: Goat format, with a sample Goat Control list.
- `edison-odds.html`: Edison format, with a sample Blackwing list and hand-trap tracking for Gorz, Tragoedia and Battle Fader.

Open either file in a browser. No build step or server is needed.

## How it works

Every card in the opponent's list that you haven't seen is treated as equally likely to be in their hand, face-down on the field, or in their deck. Face-down cards add rules: set monsters must be monsters, and traps are far more likely to be set than cards like Pot of Greed. Logging what they didn't do, such as ignoring an attack, lowers the odds of cards that would have responded. The page simulates 30,000 deals that fit everything logged and reports the results.

The sample decklists were written from memory. Paste your opponent's real list under "Opponent decklist".

Keyboard shortcuts: D draw, S set spell/trap, M set monster, E end turn, Z undo.
