#!/usr/bin/env python3
"""Itanva — per-book glossary of rare and archaic words (site/data/books/<id>/glossary.json).

Generated once per book with the Anthropic API (ANTHROPIC_API_KEY), from a sample of the text:
words a lycéen of today would stumble on, each with a short plain-language gloss in the book's
language (French for FR books, English for EN books). Skipped when the file exists or no key is set.
Usage: python3 tools/glossary.py [--limit N] [--ids id ...]
"""
import json, os, re, sys, html, urllib.request, collections

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "site", "data")
KEY = os.environ.get("ANTHROPIC_API_KEY")
MODEL = os.environ.get("EXPLAIN_MODEL", "claude-haiku-5-5")
COMMON = None
BOILER = set("""gutenberg project license licence copyright domain public ebook ebooks electronic foundation trademark
donations donate volunteers distributed distribution proofreading archive website subfolder folder files edition editions
royalty royalties refund warranty damages agreement terms internet online http https html ascii format formats""".split())

def words_of(book_id):
    """Candidate rare words: frequency across the first parts, excluding capitalised names."""
    cnt = collections.Counter()
    for k in range(min(3, 6)):
        p = os.path.join(DATA, "books", book_id, f"p{k}.json")
        if not os.path.exists(p):
            break
        for ch in json.load(open(p, encoding="utf-8")):
            txt = html.unescape(re.sub(r"<[^>]+>", " ", ch["h"]))
            for w in re.findall(r"[a-zà-ÿœæ'’-]{5,}", txt):
                cnt[w.strip("'’-").lower()] += 1
    return [w for w, n in cnt.most_common(4000) if n >= 2 and w not in BOILER][:1500]

def ask(book, author, lang, cands):
    sysm = ("Tu es lexicographe pour Itanva, une bibliothèque de classiques lue par des lycéens francophones d'Afrique de l'Ouest. "
            "Dans la liste de mots tirés du livre, choisis ceux qu'un lycéen d'aujourd'hui ne comprendrait probablement pas (mots anciens, rares, techniques, régionaux ; pas les noms propres). "
            "Réponds UNIQUEMENT en JSON : un objet {mot: explication}. Explication en français simple, 4 à 14 mots, le sens dans ce livre. 40 à 80 entrées." if lang == "fr" else
            "You are the lexicographer for Itanva, a library of classics read by students. From the list of words taken from the book, pick those a student today would likely not understand (archaic, rare, technical, dialect; no proper names). "
            "Answer ONLY in JSON: an object {word: gloss}. Gloss in plain English, 4 to 14 words, the meaning in this book. 40 to 80 entries.")
    body = {"model": MODEL, "max_tokens": 8000, "system": sysm, "messages": [{"role": "user", "content": f"Livre : {book} — {author}\nMots : " + ", ".join(cands)}]}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), headers={"content-type": "application/json", "x-api-key": KEY, "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=120) as r:
        j = json.load(r)
    text = "".join(x.get("text", "") for x in j.get("content", []))
    out = {}
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            out = json.loads(m.group(0))
        except Exception:
            out = {}
    if not out:  # truncated or malformed JSON: salvage every complete "key": "value" pair
        out = dict(re.findall(r'"([^"\n]{2,40})"\s*:\s*"([^"\n]{3,200})"', text))
    return {k.lower().strip(): str(v).strip() for k, v in out.items() if isinstance(k, str) and 1 < len(k) < 40 and v}

def main():
    if not KEY:
        print("glossary: no ANTHROPIC_API_KEY, skipped", file=sys.stderr); return
    args = sys.argv[1:]
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 40
    ids = args[args.index("--ids") + 1:] if "--ids" in args else None
    books = json.load(open(os.path.join(DATA, "index.json"), encoding="utf-8"))["books"]
    if ids:
        books = [b for b in books if b["id"] in ids]
    done = 0
    for b in sorted(books, key=lambda x: -(x.get("downloads") or 0)):
        out = os.path.join(DATA, "books", b["id"], "glossary.json")
        if os.path.exists(out):
            continue
        try:
            g = ask(b["title"], b["author"], b["lang"], words_of(b["id"]))
        except Exception as e:
            print(f"  glossary error {b['id']}: {e}", file=sys.stderr); continue
        g = {k: v for k, v in g.items() if k not in BOILER}
        if len(g) < 5:
            print(f"  glossary {b['id']}: only {len(g)} entries, not saved (retried next run)", file=sys.stderr); continue
        with open(out, "w", encoding="utf-8") as f:
            json.dump(g, f, ensure_ascii=False, separators=(",", ":"))
        print(f"  glossary {b['id']} {b['title'][:40]}: {len(g)} words", file=sys.stderr)
        done += 1
        if done >= limit:
            break
    print(f"glossary: {done} books", file=sys.stderr)

if __name__ == "__main__":
    main()
