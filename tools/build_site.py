#!/usr/bin/env python3
"""Itanva — derived site files, built after ingestion (run by CI, or locally: python3 tools/build_site.py).

From site/data/catalogue.json (full, ~600 KB) it writes:
  site/data/index.json            light catalogue for browsing (~60 KB): one line per book
  site/data/books/<id>/meta.json  chapters, part index, sources — loaded when a book is opened
  site/data/books/<id>/sample.txt first paragraphs of the actual text, for the book page preview
  site/livre/<id>.html            indexable landing page per book (title, author, hook, sample, OG tags)
  site/sitemap.xml, site/robots.txt
"""
import html, json, os, re, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
DATA = os.path.join(SITE, "data")
BASE_URL = os.environ.get("ITANVA_URL", "https://manulecoq25.github.io/Itanva/")

LIGHT = ("id", "title", "author", "lang", "genres", "words", "orig", "source", "downloads", "added")

def strip_html(h):
    return html.unescape(re.sub(r"<[^>]+>", " ", h)).replace("\xa0", " ")

def sample_of(b):
    """First real paragraphs of the text: skips tables of contents, dedications and front matter
    (chapters whose paragraphs are all short, or that start with a list of 'Chapitre…' lines)."""
    for k in range(min(2, b.get("parts", 1))):
        pk = os.path.join(DATA, "books", b["id"], f"p{k}.json")
        if not os.path.exists(pk):
            break
        for ch in json.load(open(pk, encoding="utf-8")):
            if re.search(r"(?i)pr[eé]face|introduction|notice|avertissement|avant-propos|d[ée]dicace|personnages|contents|table", ch.get("t") or ""):
                continue
            paras = [re.sub(r"\s+", " ", strip_html(m)).strip() for m in re.findall(r"<p[^>]*>(.*?)</p>", ch["h"])]
            long = [p for p in paras if len(p) >= 80 and not re.search(r"(?i)press|printed|copyright|all rights|in acknowledgment|^to [A-Z]", p) and p.upper() != p]
            if len(long) < 2 or re.match(r"(?i)^(chap|table|contents|livre|tome|partie|acte|personnages|préface|preface|avant|introduction|notice|dédicace|to |à )", paras[0] if paras else ""):
                continue
            out, n = [], 0
            for p in long:
                if re.search(r"(?i)\b(chapitre|chapter)\b.*\b(chapitre|chapter)\b", p):
                    continue
                out.append(p); n += len(p)
                if n > 900 or len(out) >= 3:
                    break
            if out:
                return "\n\n".join(out)
    return ""

def main():
    cat = json.load(open(os.path.join(DATA, "catalogue.json"), encoding="utf-8"))
    books = cat["books"]
    ed = {}
    try:
        ed = json.load(open(os.path.join(DATA, "editorial.json"), encoding="utf-8"))
    except Exception:
        pass
    prev = {}
    ip = os.path.join(DATA, "index.json")
    if os.path.exists(ip):
        for b in json.load(open(ip, encoding="utf-8"))["books"]:
            prev[b["id"]] = b
    today = time.strftime("%Y-%m-%d")
    light, urls = [], []
    os.makedirs(os.path.join(SITE, "livre"), exist_ok=True)
    for b in books:
        b["added"] = prev.get(b["id"], {}).get("added") or b.get("added") or today
        light.append({k: b.get(k) for k in LIGHT if b.get(k) is not None} | {"n": len(b["chapters"])})
        d = os.path.join(DATA, "books", b["id"])
        os.makedirs(d, exist_ok=True)
        meta = {k: b[k] for k in ("chapters", "index", "parts", "source_url", "epub_url", "license", "author_dates") if k in b}
        with open(os.path.join(d, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, separators=(",", ":"))
        sample = sample_of(b)
        with open(os.path.join(d, "sample.txt"), "w", encoding="utf-8") as f:
            f.write(sample)
        e = ed.get(b["id"], {})
        hook = (e.get("hook") or {}).get("fr") or ""
        url = f"{BASE_URL}livre/{b['id']}.html"
        urls.append(url)
        og = f"{BASE_URL}data/orig/{b['id']}.jpg" if b.get("orig") else f"{BASE_URL}icon-512.png"
        mins = round(b["words"] / 230)
        dur = f"{mins} min" if mins < 75 else f"{round(mins/60)} h"
        page = f"""<!doctype html><html lang="{b['lang']}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(b['title'])} — {html.escape(b['author'])} | Itanva</title>
<meta name="description" content="{html.escape(hook or ('Lire ' + b['title'] + ' de ' + b['author'] + ' gratuitement sur Itanva, en ligne et hors ligne, sur téléphone.'))}">
<link rel="canonical" href="{url}"><meta property="og:type" content="book"><meta property="og:title" content="{html.escape(b['title'])}"><meta property="og:description" content="{html.escape(hook or b['author'])}"><meta property="og:image" content="{og}"><meta property="og:url" content="{url}"><meta name="twitter:card" content="summary_large_image">
<script type="application/ld+json">{json.dumps({"@context":"https://schema.org","@type":"Book","name":b['title'],"author":{"@type":"Person","name":b['author']},"inLanguage":b['lang'],"isAccessibleForFree":True,"url":url}, ensure_ascii=False)}</script>
<style>body{{margin:0;background:#F7F3E9;color:#182D3B;font:17px/1.6 Georgia,serif}}main{{max-width:640px;margin:0 auto;padding:24px 20px 60px}}h1{{font-size:30px;line-height:1.15;margin:12px 0 4px}}.a{{color:#5A6672;font:15px system-ui,sans-serif}}.btn{{display:inline-block;background:#A2552A;color:#fff;padding:14px 22px;border-radius:14px;font:700 16px system-ui,sans-serif;text-decoration:none;margin:18px 0}}.hook{{font-style:italic;font-size:19px}}.s{{white-space:pre-line;border-left:3px solid #E6C78B;padding-left:14px;color:#2b3a44}}.l{{font:13px system-ui,sans-serif;color:#5A6672}}a{{color:#287D64}}</style></head>
<body><main><a class="l" href="../">‹ Itanva</a><h1>{html.escape(b['title'])}</h1><div class="a">{html.escape(b['author'])} · {('Français' if b['lang']=='fr' else 'English')} · {dur}</div>
{('<p class="hook">' + html.escape(hook) + '</p>') if hook else ''}
<a class="btn" href="../#/book/{b['id']}">Lire gratuitement sur Itanva</a>
<h2 style="font-size:18px">Extrait</h2><p class="s">{html.escape(sample)}</p>
<p class="l">Domaine public. Source : <a href="{b.get('source_url','#')}">{html.escape(b.get('source','') )}</a>. Itanva prépare les textes du domaine public pour la lecture sur téléphone, gratuitement et légalement.</p></main></body></html>"""
        with open(os.path.join(SITE, "livre", f"{b['id']}.html"), "w", encoding="utf-8") as f:
            f.write(page)
    # remove landing pages, meta and text of books no longer in the catalogue
    ids = {b["id"] for b in books}
    for f in os.listdir(os.path.join(SITE, "livre")):
        if f.endswith(".html") and f[:-5] not in ids:
            os.remove(os.path.join(SITE, "livre", f))
    import shutil
    for d in os.listdir(os.path.join(DATA, "books")):
        if d not in ids:
            shutil.rmtree(os.path.join(DATA, "books", d), ignore_errors=True)
    light.sort(key=lambda x: (-(x.get("downloads") or 0), x["title"]))
    with open(ip, "w", encoding="utf-8") as f:
        json.dump({"generated": today, "books": light}, f, ensure_ascii=False, separators=(",", ":"))
    with open(os.path.join(SITE, "sitemap.xml"), "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        f.write(f"<url><loc>{BASE_URL}</loc><changefreq>weekly</changefreq></url>\n")
        for u in urls:
            f.write(f"<url><loc>{u}</loc><changefreq>monthly</changefreq></url>\n")
        f.write("</urlset>\n")
    with open(os.path.join(SITE, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nSitemap: {BASE_URL}sitemap.xml\n")
    print(f"index: {len(light)} books, {os.path.getsize(ip)//1024} KB; {len(urls)} book pages", file=sys.stderr)

if __name__ == "__main__":
    main()
