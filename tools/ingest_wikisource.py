"""Bibli — ingestion from French Wikisource (public-domain transcriptions, CC BY-SA for the editing work).

A Wikisource "work" is either a single page or an index page whose chapters are subpages
("Title/Chapitre 1"). We read the page through the MediaWiki API, follow subpages in the
order they are linked, and convert the HTML to our chapter format.

Usage: python tools/ingest_wikisource.py "L'Art de la guerre (Sun Tzu, trad. Amiot)" ...
Called by ingest.py for "ws:" lines in shelves.txt.
"""
import hashlib, html, json, os, re, sys, urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import ingest  # noqa: E402  (fetch cache, para grouping, DATA dir)

API = "https://fr.wikisource.org/w/api.php"

def api(params):
    q = urllib.parse.urlencode(dict(params, format="json", formatversion=2))
    return json.loads(ingest.fetch(f"{API}?{q}"))

def page_html(title):
    r = api({"action": "parse", "page": title, "prop": "text|links|displaytitle", "disableeditsection": 1})
    if "error" in r:
        raise RuntimeError(r["error"].get("info", "api error"))
    p = r["parse"]
    return p["text"], [l["title"] for l in p.get("links", []) if l.get("ns") == 0], p.get("displaytitle", title)

DROP_RX = re.compile(r"<(script|style|table|sup|figure|span class=\"mw-editsection\")[\s\S]*?</\1>", re.I)
DROP_CLASS = re.compile(r"<(div|span|p|ul|ol)[^>]*class=\"[^\"]*(ws-noexport|noprint|headertemplate|header|mw-empty-elt|ws-summary|toc|navbox|ws-notes?)[^\"]*\"[^>]*>[\s\S]*?</\1>", re.I)

def html_to_paras(h):
    h = DROP_RX.sub("", h)
    for _ in range(3):
        h = DROP_CLASS.sub("", h)
    h = re.sub(r"<br\s*/?>", "\n", h)
    out = []
    for m in re.finditer(r"<(p|div|h[1-6])\b[^>]*>([\s\S]*?)</\1>", h, re.I):
        tag, inner = m.group(1).lower(), m.group(2)
        if re.search(r"<(p|div)\b", inner, re.I):
            continue  # container, its children are matched separately
        txt = re.sub(r"<[^>]+>", "", inner)
        txt = html.unescape(txt).replace("\xa0", " ")
        txt = re.sub(r"[ \t]+", " ", txt).strip()
        if len(txt) < 2:
            continue
        if tag.startswith("h"):
            out.append("## " + txt)
        else:
            out.append(txt)
    return out

def chapters_of(title):
    text, links, display = page_html(title)
    subs = [l for l in links if l.startswith(title + "/")]
    seen, order = set(), []
    for s in subs:
        if s not in seen:
            seen.add(s); order.append(s)
    chapters = []
    if order:
        for s in order:
            t, _, _ = page_html(s)
            paras = html_to_paras(t)
            if sum(len(p) for p in paras) < 300:
                continue
            ctitle = s.split("/", 1)[1].replace("_", " ")
            chapters.append({"title": ctitle, "paras": paras})
    else:
        paras = html_to_paras(text)
        cur, ctitle = [], None
        for p in paras:
            if p.startswith("## "):
                if cur:
                    chapters.append({"title": ctitle, "paras": cur})
                cur, ctitle = [], p[3:]
            else:
                cur.append(p)
        if cur:
            chapters.append({"title": ctitle, "paras": cur})
        if len(chapters) <= 1:
            chapters = ingest.split_chapters("\n\n".join(p for p in paras if not p.startswith("## ")))
    return chapters, re.sub(r"<[^>]+>", "", display)

def ingest_ws(title, author="", lang="fr", genres=("fiction",)):
    gid = "ws-" + hashlib.sha1(title.encode()).hexdigest()[:8]
    ingest.log(f"  {gid} {title}")
    chapters, display = chapters_of(title)
    words = sum(len(" ".join(c["paras"]).split()) for c in chapters)
    if words < 1500:
        ingest.log(f"  skip {title}: too short ({words} words)"); return None
    parts, cur, size, index = [], [], 0, []
    for ch in chapters:
        h = "".join(ingest.para_html(p) for p in ch["paras"])
        item = {"t": ch["title"], "h": h}
        if size + len(h) > ingest.PART_BYTES and cur:
            parts.append(cur); cur, size = [], 0
        index.append([len(parts), len(cur)]); cur.append(item); size += len(h)
    if cur:
        parts.append(cur)
    out_dir = os.path.join(ingest.DATA, "books", gid)
    os.makedirs(out_dir, exist_ok=True)
    for k, p in enumerate(parts):
        with open(os.path.join(out_dir, f"p{k}.json"), "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, separators=(",", ":"))
    m = re.match(r"^(.*?)\s*\((.*)\)\s*$", title)
    nice_title, note = (m.group(1), m.group(2)) if m else (title, "")
    return {"id": gid, "title": nice_title, "author": author or note or "Anonyme", "author_dates": [],
            "lang": lang, "genres": list(genres), "words": words, "chapters": [c["title"] for c in chapters],
            "index": index, "parts": len(parts), "downloads": 0, "source": "Wikisource",
            "source_url": "https://fr.wikisource.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
            "epub_url": "https://ws-export.wmcloud.org/?lang=fr&format=epub&page=" + urllib.parse.quote(title),
            "license": "Domaine public / Public domain"}

if __name__ == "__main__":
    for t in sys.argv[1:]:
        print(json.dumps(ingest_ws(t), ensure_ascii=False)[:300])
