"""Project Gutenberg catalogue (pg_catalog.csv) — search by author/title, no Gutendex needed.

The CSV (~15 MB) is published by Gutenberg at
https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv
Columns: Text#, Type, Issued, Title, Language, Authors, Subjects, LoCC, Bookshelves
Authors look like "Hugo, Victor, 1802-1885; Lefèvre, Jean [Illustrator], 1840-1910".
"""
import csv, io, os, re, sys, unicodedata

CSV_URL = "https://www.gutenberg.org/cache/epub/feeds/pg_catalog.csv"
csv.field_size_limit(10_000_000)

def norm(s):
    s = unicodedata.normalize("NFD", s or "").lower()
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()

AUTH_RX = re.compile(r"^(?P<name>.*?)(?:\s*\[(?P<role>[^\]]+)\])?,?\s*(?P<birth>\d{3,4})?\s*-\s*(?P<death>\d{3,4})?\s*$")

def parse_authors(field):
    out = []
    for raw in (field or "").split(";"):
        raw = raw.strip()
        if not raw:
            continue
        m = AUTH_RX.match(raw)
        if m and (m.group("birth") or m.group("death")):
            name = m.group("name").strip().rstrip(",")
            birth = int(m.group("birth")) if m.group("birth") else None
            death = int(m.group("death")) if m.group("death") else None
        else:
            name, birth, death = re.sub(r"\s*\[[^\]]+\]", "", raw).strip(), None, None
        if re.search(r"\bBC\b|B\.C\.", raw):   # antiquity: certainly public domain
            death = -1
        name = re.sub(r",?\s*\d{3,4}\??\s*(BC)?\s*-\s*\d{0,4}\??\s*(BC)?$", "", name).strip().rstrip(",")
        out.append({"name": name, "birth_year": birth, "death_year": death})
    return out

class Catalog:
    def __init__(self, text):
        self.rows = []
        for r in csv.DictReader(io.StringIO(text)):
            if r.get("Type") != "Text":
                continue
            self.rows.append(r)
        self._n = [(norm(r["Title"]), norm(r["Authors"]), r) for r in self.rows]

    def get(self, gid):
        for r in self.rows:
            if r["Text#"] == str(gid):
                return self.meta(r)
        return None

    def find(self, author, title, lang=None):
        """Best row whose title contains all words of `title` and authors contain all words of `author`."""
        ta, tt = norm(author).split(), norm(title).split()
        best = None
        for nt, na, r in self._n:
            if lang and r["Language"] != lang:
                continue
            if all(w in na.split() for w in ta) and all(w in nt for w in tt):
                score = len(nt) - len(" ".join(tt))      # shortest matching title wins (avoids "Tome II" / anthologies)
                if "volume" in nt or "tome" in nt or "vol" in nt.split():
                    score += 100
                if best is None or score < best[0]:
                    best = (score, r)
        return self.meta(best[1]) if best else None

    @staticmethod
    def meta(r):
        subjects = [s.strip() for s in (r.get("Subjects") or "").split(";") if s.strip()]
        shelves = [s.strip() for s in (r.get("Bookshelves") or "").split(";") if s.strip()]
        return {"id": int(r["Text#"]), "title": r["Title"], "authors": parse_authors(r["Authors"]),
                "languages": [r["Language"]], "copyright": False, "subjects": subjects,
                "bookshelves": shelves, "download_count": 0, "formats": {}, "issued": r.get("Issued")}

def load(fetch):
    return Catalog(fetch(CSV_URL))

if __name__ == "__main__":
    # quick self-test on a fragment
    sample = 'Text#,Type,Issued,Title,Language,Authors,Subjects,LoCC,Bookshelves\n17489,Text,2005-12-30,"Les misérables Tome I: Fantine",fr,"Hugo, Victor, 1802-1885",Fiction,PQ,FR Littérature\n'
    c = Catalog(sample)
    print(c.find("Hugo", "misérables"))
