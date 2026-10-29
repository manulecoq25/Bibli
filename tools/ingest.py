#!/usr/bin/env python3
"""Bibli — ingestion of public-domain books from Project Gutenberg.

Usage:
  python tools/ingest.py --lang fr --count 100
  python tools/ingest.py --lang en --count 100
  python tools/ingest.py --ids 17489 4650 1342        # specific Gutenberg ids
  python tools/ingest.py --from-file tools/seed.txt   # one id per line

Writes:
  site/data/catalogue.json           all books (metadata + chapter list)
  site/data/books/<id>/p<k>.json     chapter text grouped in ~45 KB parts

Only books that Gutendex marks copyright=false are kept, and every
author must have died before 1956 (life + 70 in France / Côte d'Ivoire / EU),
so US-only public domain titles are excluded.

Rate: ~1 request/second, with a cache in tools/cache/ so re-runs are free.
Gutenberg's robot policy: https://www.gutenberg.org/policy/robot_access.html
"""
import argparse, json, os, re, sys, time, urllib.request, urllib.parse, hashlib, html

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
DATA = os.path.join(SITE, "data")
CACHE = os.path.join(ROOT, "tools", "cache")
PD_DEATH_BEFORE = 1956          # life + 70 as of 2026
PART_BYTES = 45_000             # target size of one chapter part (uncompressed)
UA = "Bibli/1.0 (public-domain library; contact: admin@example.org)"

GENRE_MAP = [  # (regex on Gutendex bookshelves/subjects, genre key)
    (r"children|juvenile|fairy", "children"),
    (r"poetry|po[eé]sie|poems", "poetry"),
    (r"drama|plays|th[eé][aâ]tre", "drama"),
    (r"philosoph", "philosophy"),
    (r"history|histoire|biograph", "history"),
    (r"science fiction|fantasy|adventure|aventure|voyage|travel", "adventure"),
    (r"detective|mystery|crime|policier", "mystery"),
    (r"romance|love", "romance"),
    (r"science|nature|math|medicine", "science"),
    (r"religion|bible|spirit", "religion"),
    (r"fiction|roman|novel|contes|short stories", "fiction"),
]

def log(*a):
    print(*a, file=sys.stderr, flush=True)

def fetch(url, binary=False):
    os.makedirs(CACHE, exist_ok=True)
    key = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest())
    if os.path.exists(key):
        with open(key, "rb") as f:
            raw = f.read()
    else:
        raw, last = None, None
        for attempt in range(4):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
                break
            except Exception as e:  # network hiccup, 429, 5xx: back off and retry
                last = e
                log(f"    retry {attempt+1} {url}: {e}")
                time.sleep(3 * (attempt + 1))
        if raw is None:
            raise last
        with open(key, "wb") as f:
            f.write(raw)
        time.sleep(1.0)
    if binary:
        return raw
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            pass
    return raw.decode("utf-8", "replace")

# ---------- metadata ----------

def gutendex_list(lang, count):
    books, url = [], f"https://gutendex.com/books?languages={lang}&copyright=false&sort=popular"
    while url and len(books) < count:
        try:
            page = json.loads(fetch(url))
        except Exception as e:
            log(f"  gutendex unavailable ({e}); keeping {len(books)} listed so far")
            break
        books += page["results"]
        url = page.get("next")
    return books[:count]

def gutendex_one(gid):
    return json.loads(fetch(f"https://gutendex.com/books/{gid}"))

def text_url(meta):
    f = meta.get("formats", {})
    for k in ("text/plain; charset=utf-8", "text/plain; charset=us-ascii", "text/plain", "text/plain; charset=iso-8859-1"):
        if k in f and not f[k].endswith(".zip"):
            return f[k]
    for k, v in f.items():
        if k.startswith("text/plain") and not v.endswith(".zip"):
            return v
    return None

def genres_of(meta):
    tags = " ".join(meta.get("bookshelves", []) + meta.get("subjects", [])).lower()
    out = [g for rx, g in GENRE_MAP if re.search(rx, tags)]
    return out[:3] or ["fiction"]

def authors_ok(meta):
    """All authors dead before PD_DEATH_BEFORE (or unknown and born before 1850)."""
    for a in meta.get("authors", []):
        d, b = a.get("death_year"), a.get("birth_year")
        if d is not None and d >= PD_DEATH_BEFORE:
            return False
        if d is None and (b is None or b >= 1850):
            return False
    return True

def author_name(a):
    n = a.get("name", "")
    if "," in n:
        last, first = n.split(",", 1)
        return f"{first.strip()} {last.strip()}"
    return n

MIRRORS = [  # gutenberg.org sometimes blocks cloud IP ranges; the mirrors carry the same files
    "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt",
    "https://aleph.gutenberg.org/cache/epub/{id}/pg{id}.txt",
    "https://gutenberg.pglaf.org/cache/epub/{id}/pg{id}.txt",
    "https://aleph.gutenberg.org/{path}/{id}/{id}-0.txt",
    "https://aleph.gutenberg.org/{path}/{id}/{id}-8.txt",
    "https://aleph.gutenberg.org/{path}/{id}/{id}.txt",
]

def fetch_text(gid, preferred=None):
    s = str(gid); path = "/".join(s[:-1]) if len(s) > 1 else "0"
    urls = ([preferred] if preferred else []) + [m.format(id=gid, path=path) for m in MIRRORS]
    last = None
    for u in urls:
        try:
            t = fetch(u)
            if "PROJECT GUTENBERG" in t.upper()[:3000] or len(t) > 20000:
                return t
        except Exception as e:
            last = e
    raise RuntimeError(f"no text source reachable for {gid}: {last}")

# ---------- text processing ----------

START_RX = re.compile(r"^\*\*\*\s*START OF (THE|THIS) PROJECT GUTENBERG.*$", re.M)
END_RX = re.compile(r"^\*\*\*\s*END OF (THE|THIS) PROJECT GUTENBERG.*$", re.M)
HEAD_RX = re.compile(
    r"^(?:(?:CHAPTER|CHAPITRE|CHAP\.|BOOK|LIVRE|PART|PARTIE|TOME|ACT|ACTE|SCENE|SCÈNE|SECTION|LETTER|LETTRE|CANTO|CHANT)\s+"
    r"(?:[IVXLCDM]+|\d+|[A-Z][A-Za-z-]+)\.?[^\n]{0,80}|[IVXLCDM]{1,7}\.?|\d{1,3}\.?|(?:PROLOGUE|ÉPILOGUE|EPILOGUE|PREFACE|PRÉFACE|INTRODUCTION|CONCLUSION)\.?)$",
    re.I)

def strip_boilerplate(txt):
    m = START_RX.search(txt)
    if m:
        txt = txt[m.end():]
    m = END_RX.search(txt)
    if m:
        txt = txt[:m.start()]
    return txt.replace("\r\n", "\n").replace("\r", "\n")

def split_chapters(txt):
    lines = txt.split("\n")
    heads = []
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s or len(s) > 90:
            continue
        prev_blank = i == 0 or not lines[i - 1].strip()
        next_blank = i + 1 >= len(lines) or not lines[i + 1].strip()
        if prev_blank and next_blank and HEAD_RX.match(s):
            heads.append(i)
    # keep only headings that cut the text into reasonable pieces
    if len(heads) >= 3:
        chapters, pos = [], 0
        for h in heads:
            if sum(len(x) for x in lines[pos:h]) > 400:
                chapters.append(lines[pos:h])
            pos = h
        chapters.append(lines[pos:])
        chapters = [c for c in chapters if "".join(c).strip()]
        if len(chapters) >= 3:
            return [_chapter(c) for c in chapters]
    # fallback: ~2500-word slices on paragraph boundaries
    paras, out, cur, n = re.split(r"\n\s*\n", txt), [], [], 0
    for p in paras:
        w = len(p.split())
        if n + w > 2500 and cur:
            out.append(cur); cur, n = [], 0
        cur.append(p); n += w
    if cur:
        out.append(cur)
    return [{"title": None, "paras": c} for c in out]

def _chapter(lines):
    title = lines[0].strip()
    body = "\n".join(lines[1:])
    # a subtitle line right after the heading
    paras = [p for p in re.split(r"\n\s*\n", body) if p.strip()]
    if paras and len(paras[0].strip()) < 90 and "\n" not in paras[0].strip():
        title = title + " — " + paras[0].strip(); paras = paras[1:]
    return {"title": title, "paras": paras}

def para_html(p):
    p = p.strip()
    if not p:
        return ""
    is_verse = p.count("\n") >= 2 and max(len(x) for x in p.split("\n")) < 70
    if is_verse:
        return "<p class=v>" + "<br>".join(html.escape(x.strip()) for x in p.split("\n")) + "</p>"
    text = html.escape(re.sub(r"\s*\n\s*", " ", p))
    text = re.sub(r"_(.+?)_", r"<em>\1</em>", text)
    return "<p>" + text + "</p>"

def clean_title(t):
    return re.sub(r"\s+", " ", t.split("\n")[0]).strip()

def ingest(meta, lang_hint=None):
    gid = meta["id"]
    if meta.get("copyright") is not False or not authors_ok(meta):
        log(f"  skip {gid}: not public domain under life+70"); return None
    url = text_url(meta)
    if not url:
        log(f"  skip {gid}: no plain text"); return None
    log(f"  {gid} {clean_title(meta['title'])}")
    txt = strip_boilerplate(fetch_text(gid, url))
    chapters = split_chapters(txt)
    words = sum(len(" ".join(c["paras"]).split()) for c in chapters)
    if words < 1500:
        log(f"  skip {gid}: too short"); return None
    # group chapters into parts
    parts, cur, size, index = [], [], 0, []
    for ci, ch in enumerate(chapters):
        h = "".join(para_html(p) for p in ch["paras"])
        item = {"t": ch["title"], "h": h}
        if size + len(h) > PART_BYTES and cur:
            parts.append(cur); cur, size = [], 0
        index.append([len(parts), len(cur)])
        cur.append(item); size += len(h)
    if cur:
        parts.append(cur)
    out_dir = os.path.join(DATA, "books", str(gid))
    os.makedirs(out_dir, exist_ok=True)
    for k, p in enumerate(parts):
        with open(os.path.join(out_dir, f"p{k}.json"), "w", encoding="utf-8") as f:
            json.dump(p, f, ensure_ascii=False, separators=(",", ":"))
    lang = (meta.get("languages") or [lang_hint or "en"])[0]
    authors = [author_name(a) for a in meta.get("authors", [])]
    years = [a.get("birth_year") for a in meta.get("authors", []) if a.get("birth_year")]
    return {
        "id": str(gid),
        "title": clean_title(meta["title"]),
        "author": ", ".join(authors) or "Anonyme",
        "author_dates": [[a.get("birth_year"), a.get("death_year")] for a in meta.get("authors", [])],
        "lang": lang,
        "genres": genres_of(meta),
        "words": words,
        "chapters": [c["title"] for c in chapters],
        "index": index,
        "parts": len(parts),
        "downloads": meta.get("download_count", 0),
        "source": "Project Gutenberg",
        "source_url": f"https://www.gutenberg.org/ebooks/{gid}",
        "epub_url": f"https://www.gutenberg.org/ebooks/{gid}.epub3.images",
        "license": "Domaine public / Public domain",
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lang", choices=["fr", "en"])
    ap.add_argument("--count", type=int, default=100)
    ap.add_argument("--ids", nargs="*", type=int)
    ap.add_argument("--from-file")
    args = ap.parse_args()

    cat_path = os.path.join(DATA, "catalogue.json")
    catalogue = {}
    if os.path.exists(cat_path):
        for b in json.load(open(cat_path, encoding="utf-8"))["books"]:
            catalogue[b["id"]] = b

    metas = []
    if args.lang:
        metas = gutendex_list(args.lang, args.count)
    ids = list(args.ids or [])
    if args.from_file:
        ids += [int(x) for x in open(args.from_file) if x.strip().isdigit()]
    for gid in ids:
        if str(gid) not in catalogue:
            metas.append(gutendex_one(gid))

    for m in metas:
        if str(m["id"]) in catalogue:
            continue
        try:
            b = ingest(m, args.lang)
        except Exception as e:  # keep going on one bad book
            log(f"  error {m.get('id')}: {e}"); b = None
        if b:
            catalogue[b["id"]] = b
            os.makedirs(DATA, exist_ok=True)
            with open(cat_path, "w", encoding="utf-8") as f:
                json.dump({"generated": time.strftime("%Y-%m-%d"), "books": sorted(catalogue.values(), key=lambda x: -x["downloads"])},
                          f, ensure_ascii=False, separators=(",", ":"))
    log(f"catalogue: {len(catalogue)} books")

if __name__ == "__main__":
    main()
