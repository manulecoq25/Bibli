# Bibli — free public-domain books, phone-first (FR + EN)

Static site + ingestion script. No server, no database, no account.

## Layout
- `site/` — the website (deploy this folder as-is)
  - `index.html` — the whole app (catalogue, search, book page, reader, FR/EN UI)
  - `sw.js` — offline cache (shell + catalogue on install, chapters as they are read)
  - `data/catalogue.json` — all books (metadata, chapter titles, part index)
  - `data/books/<id>/p<k>.json` — chapter text in ~45 KB parts (gzip ≈ 15 KB)
- `tools/ingest.py` — pulls books from Project Gutenberg via the Gutendex API

## Add books
```
python3 tools/ingest.py --lang fr --count 150     # most popular French titles
python3 tools/ingest.py --lang en --count 150     # most popular English titles
python3 tools/ingest.py --ids 17489 4650          # specific Gutenberg ids
```
Re-runs are incremental (a cache lives in `tools/cache/`). The script keeps only
books Gutendex marks public domain AND whose authors died before 1956
(life + 70, the rule in Côte d'Ivoire, France and the EU).

## Run locally
```
cd site && python3 -m http.server 8080     # open http://localhost:8080
```

## Deploy (free)
- **Cloudflare Pages**: new project → upload `site/` (or connect the repo, build output = `site`).
  `site/_headers` already sets long caching for book parts.
- **Render static site**: publish directory = `site`, no build command.
- Add a custom domain in either; HTTPS is automatic. The PWA (home-screen icon, offline) only works over HTTPS.

## Legal
Only public-domain texts (Project Gutenberg, life + 70 check). Keep the About page's
takedown contact up to date. Gutenberg trademark rules: we link to the source book
page and do not claim affiliation. See https://www.gutenberg.org/policy/permission.html

## Next (not in V1)
Standard Ebooks (better English typesetting), Wikisource FR, CC African children's
stories (African Storybook, StoryWeaver), LibriVox audio, accounts/sync, curated
school shelves (BAC/BEPC), sitemap + per-book HTML pages for Google.
