# Decision log (why things are the way they are)

| Decision | Reason |
|---|---|
| Letterboxd feed replaced by TMDB | Letterboxd sits behind a Cloudflare challenge (403) that scripts can't pass. TMDB has an official API. |
| TMDB discovery in 7-day windows, 2 pages each | A single popularity-sorted query let blockbusters crowd out everything else. |
| TVmaze `/schedule/full` is a default TV feed | Metacritic's "new" list only has already-released shows; TVmaze lists future premieres and specials. |
| Empty Metacritic result = feed error | A blocked/changed page used to look like "no new shows". |
| Manual archives are sticky (`manually_archived`) | Users were annoyed by archived items reappearing after enrichment. Auto-archive is still reversible. |
| Auto-archive needs >= 2 missing of title/network/cast/plot | Avoids hiding items for a single missing field; badge appears when data arrives later. |
| Returning (season 2+) shows, library items and archived items hidden by default | Default view is "new things I don't have yet". Specials are not flagged as returning. |
| `slug()` is Unicode-aware | ASCII-only keys turned every Greek/Cyrillic title into `''`, making one cache row appear many times and causing false library matches. |
| `dedupe_movies` never merges conflicting TMDB/IMDb ids | "Beast" and "The Beast" are different films. Prefix/suffix merging needs >= 8 chars and dates within 30 days. |
| Country for movies only after enrichment | TMDB discover lists have no origin country; it needs a per-movie call. |
| `build.py` is the single build implementation | Three scripts had drifted; wrappers only ensure the venv. |
| No Makefile | `make` isn't available on stock Windows; per-OS differences live in `build.py`. |
| Tests blank the TMDB key (`tests/conftest.py`) | Tests must be offline and must never use the real credential. |
| Credentials only in DB/`.env` | Both git-ignored; history was audited and is clean. |
| Frontend behaviour tested via Node + DOM stub | No browser tooling available; keeps JS logic regression-tested without new dependencies. |
