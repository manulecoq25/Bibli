# Bibli — deployment checklist

## Branches
- `main` → live site (GitHub Pages, https://manulecoq25.github.io/Bibli/). Deploys on every push touching `site/`, and after each weekly ingest.
- `v4` → preview (Render static site, https://bibli-preview.onrender.com). Auto-deploys on push.

## Before merging a redesign into `main`
1. `python3 tools/test_site.py` passes (320/390/768/1440, reading flow, persistence).
2. Open the preview on a real Android phone: home, a book page, read two pages, rotate, go offline (airplane mode) and reopen a chapter already read, highlight a passage, share card to WhatsApp.
3. Check dark mode and the contrast theme.
4. `python3 tools/build_site.py` has been run after the last ingest (CI does it): `site/data/index.json`, `site/livre/*.html`, `site/sitemap.xml` are fresh.
5. Bump `V` in `site/sw.js` if the shell changed (CSS/JS paths or new cached files), so phones pick up the new version.
6. Update `BASE_URL` in `tools/build_site.py` (or set `BIBLI_URL` in the workflow) when the domain changes — it is written into every book page's canonical/OG tags.

## Merge and release
```
git checkout main && git merge --no-ff v4 && git push
```
The deploy workflow publishes `site/` in about a minute. Verify https://manulecoq25.github.io/Bibli/ and one book page `livre/<id>.html` (share preview: paste the link in WhatsApp).

## Custom domain
GitHub → Settings → Pages → Custom domain (adds `site/CNAME`; keep that file in the repo). Registrar: `CNAME www → manulecoq25.github.io`, A records for the apex as listed by GitHub. Then update `BASE_URL`, `og:image` in `index.html`, `manifest.json` `start_url`, and the share-card footer (reads the current origin automatically).

## Rollback
`git revert` the merge commit on `main` and push; Pages redeploys the previous site. Reader data lives on devices and is unaffected by any deploy.

## Analytics (optional, later)
See `docs/ANALYTICS.md`; enabling is a one-line script in `index.html`.
