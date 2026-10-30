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
    r = api({"action": "parse", "page": title, "prop": "text|displaytitle", "disableeditsection": 1})
    if "error" in r:
        raise RuntimeError(r["error"].get("info", "api error"))
    p = r["parse"]
    return p["text"], ordered_links(p["text"]), p.get("displaytitle", title)

def ordered_links(h):
    """Main-namespace wiki links in document order (the API's `links` list is alphabetical)."""
    out, seen = [], set()
    for m in re.finditer(r'href="/wiki/([^"#?]+)', h):
        t = urllib.parse.unquote(m.group(1)).replace("_", " ")
        if ":" in t.split("/")[0] or t in seen:
            continue
        seen.add(t); out.append(t)
    return out

PARATEXT = re.compile(r"^(texte entier|appendice|notice|variantes?|pr[ée]face|avertissement|placet|.*placet|table|table des mati[èe]res|d[ée]dicace|[àa] (madame|monseigneur|monsieur).*|avis|privil[èe]ge|notes?|introduction du traducteur|bibliographie)$", re.I)

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
        txt = re.sub(r"(^|\n)\s*\d{1,4}(?=[A-ZÀ-Ü«])", r"\1", txt)  # verse line numbers glued to the first word
        txt = re.sub(r"[ \t]+", " ", txt).strip()
        if len(txt) < 2:
            continue
        if tag.startswith("h"):
            out.append("## " + txt)
        else:
            out.append(txt)
    return out

def resolve(title):
    """Exact page, else the best search hit; a short disambiguation page is followed to its first edition."""
    found = None
    try:
        page_html(title); found = title
    except Exception:
        r = api({"action": "query", "list": "search", "srsearch": title, "srnamespace": 0, "srlimit": 5})
        hits = [h["title"] for h in r.get("query", {}).get("search", [])]
        if not hits:
            raise RuntimeError("not found on Wikisource: " + title)
        found = hits[0]
    text, links, _ = page_html(found)
    words = len(re.sub(r"<[^>]+>", " ", text).split())
    has_subs = any(l.startswith(found + "/") for l in links)
    if words < 400 and not has_subs:
        base = found.split(" (")[0]
        editions = [l for l in links if l.startswith(base + " (") or (l.startswith(base + "/"))]
        if editions:
            ingest.log(f"    wikisource: '{title}' -> '{editions[0]}' (edition page)")
            return editions[0]
    if found != title:
        ingest.log(f"    wikisource: '{title}' -> '{found}'")
    return found

def walk(title, depth=0, seen=None, root=None):
    """Yield (page title, html) for the work, following subpages in document order, up to 3 levels.
    When a page links to several editions (Title/Édition A/…, Title/Édition B/…), only the first is used.
    Paratext pages (Texte entier, Notice, Préface, Placets…) are skipped."""
    seen = seen if seen is not None else set()
    root = root or title
    text, links, _ = page_html(title)
    subs = []
    for l in links:
        if l.startswith(title + "/") and l not in seen:
            last = l.rsplit("/", 1)[1]
            if PARATEXT.match(last.strip()):
                continue
            seen.add(l); subs.append(l)
    # several editions under the root: keep the first edition's subtree only
    if title == root:
        groups = []
        for l in subs:
            g = l[len(root) + 1:].split("/")[0]
            if g not in groups:
                groups.append(g)
        nested = [g for g in groups if any(l.startswith(f"{root}/{g}/") for l in subs)]
        if len(nested) >= 2:
            keep = nested[0]
            subs = [l for l in subs if l.startswith(f"{root}/{keep}/") or l == f"{root}/{keep}"]
        elif len(nested) == 1:  # one real edition plus flat sibling edition pages: drop the siblings
            keep = nested[0]
            subs = [l for l in subs if l.startswith(f"{root}/{keep}") or not re.match(r"(?i)^(édition|edition|traduction|texte)", l[len(root) + 1:])]
    if subs and depth < 3:
        for s in subs:
            yield from walk(s, depth + 1, seen, root)
    else:
        yield title, text

def chapters_of(title):
    title = resolve(title)
    text, links, display = page_html(title)
    pages = list(walk(title))
    chapters = []
    if len(pages) > 1:
        for s, t in pages:
            paras = [p for p in html_to_paras(t) if not p.startswith("## ") and not re.search(r"[►◄▶◀]|^(variantes|texte entier)$", p, re.I)]
            if sum(len(p) for p in paras) < 300:
                continue
            ctitle = s.split("/", 1)[1].replace("_", " ").replace("/", " · ") if "/" in s else s
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
    # several editions or translations of the same work: keep the first one that has real chapters
    def seg0(c):
        t = c["title"] or ""
        return t.split(" · ")[0] if " · " in t else t
    groups = []
    for c in chapters:
        g = seg0(c)
        if g not in groups:
            groups.append(g)
    ed = [g for g in groups if re.match(r"(?i)^(édition|edition|traduction|texte|dentu|[a-zé]+,? \d{4})", g)]
    if len(ed) >= 2 or (len(ed) == 1 and len(groups) > 1 and any(" · " in (c["title"] or "") for c in chapters)):
        sizes = {g: sum(1 for c in chapters if seg0(c) == g) for g in groups}
        keep = next((g for g in groups if sizes[g] >= 2), groups[0])
        ingest.log(f"    keeping edition '{keep}' of {len(groups)} ({', '.join(groups[:4])}…)")
        chapters = [c for c in chapters if seg0(c) == keep]
    # drop a chapter-title prefix shared by every chapter ("Édition Louandre, 1910 · Acte I" -> "Acte I")
    titles = [c["title"] or "" for c in chapters]
    while len(chapters) > 1 and all(" · " in t for t in titles) and len({t.split(" · ")[0] for t in titles}) == 1:
        for c in chapters:
            c["title"] = c["title"].split(" · ", 1)[1]
        titles = [c["title"] for c in chapters]
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
    return {"id": gid, "fmt": ingest.FMT, "title": nice_title, "author": author or note or "Anonyme", "author_dates": [],
            "lang": lang, "genres": list(genres), "words": words, "chapters": [c["title"] for c in chapters],
            "index": index, "parts": len(parts), "downloads": 0, "source": "Wikisource",
            "source_url": "https://fr.wikisource.org/wiki/" + urllib.parse.quote(title.replace(" ", "_")),
            "epub_url": "https://ws-export.wmcloud.org/?lang=fr&format=epub&page=" + urllib.parse.quote(title),
            "license": "Domaine public / Public domain"}

if __name__ == "__main__":
    for t in sys.argv[1:]:
        print(json.dumps(ingest_ws(t), ensure_ascii=False)[:300])
