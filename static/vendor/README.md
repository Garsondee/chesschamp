# Vendored third-party code

This directory contains **unmodified, vendored files from Lichess's [Chessground](https://github.com/lichess-org/chessground) board library** — bundled directly (no build step, no CDN, fully offline-capable) rather than pulled in via a package manager.

| File | What it is |
|---|---|
| `chessground.min.js` | The board renderer/interaction library (ESM, exports `Chessground`). |
| `chessground.base.css` | Core board layout rules. |
| `chessground.brown.css` | The board colour theme in use. |
| `chessground.cburnett.css` | The piece set in use — SVGs embedded as base64 data URIs. |

**Source:** <https://github.com/lichess-org/chessground>, version `9.2.1`.

**License:** GPL-3.0-or-later (Chessground's own license, unrelated to and unchanged by this
repository's license). These files are used as-is and are **not** covered by the MIT license
in this project's root [`LICENSE`](../../LICENSE) file — that license applies only to the
original ChessChamp application code (`chesscoach/`, `web/`, `play.py`, `static/*.js`,
`static/*.css`, `static/index.html`, excluding this directory). See Chessground's own
license terms if you intend to redistribute these specific files.
