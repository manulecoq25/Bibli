#!/usr/bin/env python3
"""Bibli — end-to-end checks with Playwright (python3 tools/test_site.py [--shots DIR]).
Serves site/ locally, then for 320/390/768/1440 px: loads every route, fails on page errors,
horizontal overflow, missing covers; exercises reading, progress persistence, highlights, shelves,
onboarding, search, and measures transfer sizes for the first paint."""
import http.server, json, os, socketserver, sys, threading, time
from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SITE = os.path.join(ROOT, "site")
PORT = 8799
SHOTS = sys.argv[sys.argv.index("--shots") + 1] if "--shots" in sys.argv else None

class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def __init__(self, *a, **k): super().__init__(*a, directory=SITE, **k)

def serve():
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("127.0.0.1", PORT), Quiet)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd

fails = []
def check(cond, msg):
    if not cond:
        fails.append(msg); print("  FAIL", msg)

def main():
    serve(); time.sleep(.3)
    idx = json.load(open(os.path.join(SITE, "data", "index.json"), encoding="utf-8"))["books"]
    fr = next(b for b in idx if b["lang"] == "fr" and b["n"] > 3)
    base = f"http://127.0.0.1:{PORT}/"
    with sync_playwright() as p:
        br = p.chromium.launch()
        for w in (320, 390, 768, 1440):
            print(f"== width {w}")
            ctx = br.new_context(viewport={"width": w, "height": 740 if w < 700 else 900}, device_scale_factor=2 if w < 700 else 1, locale="fr-FR", has_touch=w < 700)
            pg = ctx.new_page(); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e)))
            routes = ["#/", "#/catalogue", "#/catalogue?q=hugo", "#/catalogue?goal=evasion&len=short", f"#/book/{fr['id']}", "#/mine", "#/blog", "#/about", "#/shelf/bac"]
            for r in routes:
                pg.goto(base + r); pg.wait_for_timeout(700)
                sw = pg.evaluate("document.documentElement.scrollWidth"); cw = pg.evaluate("document.documentElement.clientWidth")
                check(sw <= cw + 1, f"{w}px {r}: horizontal overflow {sw}>{cw}")
                if r == "#/":
                    check(pg.locator(".cov svg").count() >= 8, f"{w}px home: covers missing")
                if SHOTS and w in (390, 1440):
                    pg.screenshot(path=os.path.join(SHOTS, f"{w}-{r.strip('#/').replace('/', '_').replace('?', '_') or 'home'}.png"), full_page=(r in ("#/", f"#/book/{fr['id']}")))
            # reading flow
            pg.goto(base + f"#/read/{fr['id']}/1"); pg.wait_for_timeout(900)
            check(pg.locator("#pgcols p").count() > 3, f"{w}px reader: no paragraphs")
            before = pg.evaluate("document.getElementById('pct').innerText")
            if w < 700:
                pg.touchscreen.tap(w - 20, 400)
            else:
                pg.keyboard.press("ArrowRight")
            pg.wait_for_timeout(400)
            after = pg.evaluate("document.getElementById('pct').innerText")
            check(before != after, f"{w}px reader: page did not turn ({before!r} -> {after!r})")
            # highlight via selection
            pg.evaluate("""()=>{const p=document.querySelector('#pgcols p');const r=document.createRange();r.setStart(p.firstChild,0);r.setEnd(p.firstChild,Math.min(20,p.firstChild.length));const s=getSelection();s.removeAllRanges();s.addRange(r);document.dispatchEvent(new Event('selectionchange'))}""")
            pg.wait_for_timeout(300)
            check(pg.locator(".selbar").count() == 1, f"{w}px reader: selection toolbar missing")
            pg.locator(".selbar button").first.click(); pg.wait_for_timeout(300)
            check(pg.locator("#pgcols mark").count() >= 1, f"{w}px reader: highlight not applied")
            # progress persisted and shown on home / book page
            pg.goto(base + "#/"); pg.wait_for_timeout(800)
            check(pg.locator(".cont").count() >= 1, f"{w}px home: continue card missing after reading")
            pg.goto(base + "#/mine/notes"); pg.wait_for_timeout(500)
            check(pg.locator(".notes q").count() >= 1, f"{w}px my books: note not listed")
            # save to list from catalogue
            pg.goto(base + "#/catalogue"); pg.wait_for_timeout(700)
            pg.locator(".lcard [data-sv]").first.click(); pg.wait_for_timeout(200)
            pg.goto(base + "#/mine/todo"); pg.wait_for_timeout(500)
            check(pg.locator(".grid .card").count() >= 1, f"{w}px my books: to-read list empty after save")
            # search suggestions
            pg.goto(base + "#/catalogue"); pg.wait_for_timeout(500)
            pg.fill("#cq", "cand"); pg.wait_for_timeout(200)
            check(pg.locator("#sugg a").count() >= 1, f"{w}px catalogue: no suggestions")
            check(not errs, f"{w}px: page errors {errs[:3]}")
            ctx.close()
        # performance: bytes needed for first home paint (fresh context)
        ctx = br.new_context(viewport={"width": 390, "height": 740}); pg = ctx.new_page(); sizes = {}
        pg.on("response", lambda r: sizes.__setitem__(r.url.split("/")[-1] or "index", int(r.headers.get("content-length") or 0)))
        t0 = time.time(); pg.goto(base); pg.wait_for_selector(".cov svg"); t1 = time.time()
        first = {k: v for k, v in sizes.items() if k.endswith((".html", ".css", ".js", ".json", "index"))}
        print(f"first paint (local): {round((t1-t0)*1000)} ms; bytes: {sum(first.values())//1024} KB", first)
        br.close()
    print("\nRESULT:", "OK" if not fails else f"{len(fails)} failure(s)")
    sys.exit(1 if fails else 0)

if __name__ == "__main__":
    main()
