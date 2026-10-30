# Bibli — measurement plan (privacy first)

## Principles
- No third-party tracker, no cookies, no fingerprinting, no consent banner needed.
- Two layers: (1) **first-party, device-only event log** already in the app (`bibli.events` in localStorage, capped at 600 events, never sent anywhere — it powers the reader's own dashboard and lets us debug with a volunteer's export); (2) **aggregate page analytics** to add when traffic starts: Cloudflare Web Analytics or GoatCounter (both cookieless, no personal data, exempt from consent under CNIL/ARTCI guidance for audience measurement). Toggle: one `<script>` line in `index.html`, documented here, off by default.
- Nothing shown to users is derived from invented numbers: streaks, minutes, challenges, recaps all come from the device's own log.

## Event definitions (first-party log, `track(e, data)`)
| event | when | data |
|---|---|---|
| `view` | route change | `p` (home, catalogue, book, read, mine, blog, about, shelf) |
| `search` | catalogue search submitted | `q`, `n` results |
| `book_view` | book page opened | `id` |
| `read` | a chapter opened in the reader | `id`, `ch` |
| `shelf` | save / unsave to a list | `k` (toread, fav), `id`, `on` |
| `highlight` | passage highlighted or noted | `id` |
| `define` | dictionary lookup | `w` |
| `tts` | read-aloud started | `id` |
| `share` | share sheet opened | `id` |
| `book_done` | all chapters ticked or marked finished | `id`, `manual` |
| `onboard` | onboarding completed | `n` interests, `goal` |

Reading time: `stats.days[YYYY-MM-DD].min` accumulates while the reader is open and the tab visible (15 s ticks, gaps > 2 min ignored).

## Metrics and how they are computed (aggregate layer, once enabled)
- Homepage → catalogue engagement: sessions with `view:catalogue` after `view:home` / sessions with `view:home`.
- Book detail views: count of `book_view`.
- Start-reading conversion: distinct `id` with `read` / distinct `id` with `book_view`.
- Average engaged reading time: mean of `stats.days.min` per active day (device) · sessions via page analytics.
- Reading-session completion: `book_done` / distinct books with `read`.
- 7-day returning reader rate: readers with activity on ≥ 2 distinct days in a 7-day window / readers active in the window (device log; page analytics gives the site-level proxy).
- Books started and completed: distinct `read` ids; `book_done` count.
- Search usage: `search` events per session; zero-result rate (`n = 0`).
- Feature adoption: share of readers with ≥ 1 `highlight`, `define`, `tts`, `share`, `shelf`.

## Consent
Audience measurement with a cookieless tool configured without cross-site tracking does not require prior consent (CNIL exemption, art. 82 Loi Informatique et Libertés; same approach is accepted in Côte d'Ivoire's law 2013-450). The About page states that reading data stays on the device. If a future feature sends device logs to a server (sync, accounts), that becomes opt-in and this document must be updated first.

## Enable page analytics (later)
Add to `site/index.html` before `</body>`:
`<script defer src="https://static.cloudflareinsights.com/beacon.min.js" data-cf-beacon='{"token": "…"}'></script>`
and list the domain in the CSP/allowlist notes of README.
