import http.server, threading, pathlib, sys, functools, json
from playwright.sync_api import sync_playwright

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
from _paths import REPO, TESTS, TMP
ROOT = REPO   # โฟลเดอร์ที่เซิร์ฟเวอร์ทดสอบเสิร์ฟ (index.html, sw.js)
state = {"fail503": False, "swv": "v6", "reqs": [], "indexB": False, "redirIndex": False, "xmode": "ok", "down": False}
fails = []

def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond:
        fails.append(name)

class H(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(ROOT), **k)
    def log_message(self, *a): pass
    def end_headers(self):
        # เหมือน GitHub Pages: ไฟล์ static ส่ง max-age=600 (ทำให้ HTTP cache ตอบแทนเซิร์ฟเวอร์ได้ 10 นาที)
        if not any(h.lower().startswith(b"cache-control") for h in getattr(self, "_headers_buffer", [])):
            self.send_header("Cache-Control", "max-age=600")
        super().end_headers()
    def do_GET(self):
        if state["down"]:
            # จำลอง "ออฟไลน์" แบบตัดการเชื่อมต่อจริงที่ฝั่งเซิร์ฟเวอร์ (ไม่ใช้ set_offline ของ Playwright: บน WebKit มันทำให้แม้หน้าที่ service worker ตอบจากแคชก็ล้ม)
            self.close_connection = True
            try: self.connection.shutdown(2)
            except Exception: pass
            return
        path = self.path.split("?")[0]
        state["reqs"].append((path, self.headers.get("Cache-Control")))
        if state["fail503"] and path in ("/", "/index.html"):
            body = b"ERR503 deploying"
            self.send_response(503); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if state["redirIndex"] and path == "/index.html":
            self.send_response(302); self.send_header("Location", "/"); self.send_header("Content-Length", "0"); self.end_headers(); return
        if path == "/other.html":
            body = "<title>OTHER</title>OTHER PAGE".encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if state["indexB"] and path in ("/", "/index.html"):
            body = (ROOT / "index.html").read_text(encoding="utf-8").replace("<title>สมุดบันทึกการเทรด — Trading Ledger</title>", "<title>VERSION-B</title>").encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        if path == "/sw.js" and state["swv"] != "v6":
            body = (ROOT / "sw.js").read_text(encoding="utf-8").replace("'v6'", f"'{state['swv']}'").encode("utf-8")
            self.send_response(200); self.send_header("Content-Type", "application/javascript"); self.send_header("Cache-Control", "no-store"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body); return
        return super().do_GET()

import time
class X(http.server.BaseHTTPRequestHandler):
    # "โดเมนอื่น" จำลอง Google Fonts: CORS เปิด, โหมด ok/slow/err สลับได้
    def log_message(self, *a): pass
    def do_GET(self):
        if state["down"]:
            self.close_connection = True
            try: self.connection.shutdown(2)
            except Exception: pass
            return
        m = state["xmode"]
        if m == "slow": time.sleep(6)
        body = (b"v2-slow" if m == "slow" else (b"err" if m == "err" else b"v1"))
        try:
            self.send_response(503 if m == "err" else 200)
            self.send_header("Access-Control-Allow-Origin", "*"); self.send_header("Content-Type", "text/plain"); self.send_header("Content-Length", str(len(body))); self.send_header("Cache-Control", "no-store")
            self.end_headers(); self.wfile.write(body)
        except Exception:
            pass
srvx = http.server.ThreadingHTTPServer(("127.0.0.1", 0), X)
threading.Thread(target=srvx.serve_forever, daemon=True).start()
XBASE = f"http://127.0.0.1:{srvx.server_address[1]}"

srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = f"http://127.0.0.1:{port}"

with sync_playwright() as p:
    b = getattr(p, __import__('os').environ.get('BROWSER','chromium')).launch()
    ctx = b.new_context()
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(BASE + "/")
    pg.evaluate("navigator.serviceWorker.ready.then(()=>true)")
    pg.wait_for_function("navigator.serviceWorker.controller !== null || true")
    pg.evaluate("new Promise(r=>navigator.serviceWorker.ready.then(()=>r(true)))")
    pg.reload()   # ให้หน้าถูกควบคุมโดย SW
    pg.wait_for_function("!!navigator.serviceWorker.controller", timeout=8000)

    names = pg.evaluate("caches.keys()")
    check("SW installed with versioned cache", names == ["trading-journal-v6"], names)
    cached = pg.evaluate("caches.open('trading-journal-v6').then(c=>c.keys()).then(ks=>ks.map(k=>new URL(k.url).pathname))")
    check("precache has ./ index manifest icons", set(cached) >= {"/", "/index.html", "/manifest.json", "/icon-192.png", "/icon-512.png"}, cached)
    precache_hdrs = [h for (pth, h) in state["reqs"] if pth == "/index.html"]
    check("precache request bypasses HTTP cache (Cache-Control no-cache)", any(h and "no-cache" in h for h in precache_hdrs), precache_hdrs)

    # ออฟไลน์: ลิงก์ที่มี query ต้องเปิดได้
    state["down"] = True
    for u in ("/", "/?utm=1", "/index.html?x=1", "/?fbclid=abc&z=2"):
        try:
            pg.goto(BASE + u)
            ok = "Trading Ledger" in pg.title() or "สมุดบันทึกการเทรด" in pg.title()
        except Exception as ex:
            ok = False
        check(f"offline navigation {u}", ok, pg.title() if True else "")
    state["down"] = False

    # คำตอบ 503 ต้องไม่ทับแคชที่ดี
    state["fail503"] = True
    pg.goto(BASE + "/")                 # ตอบจากแคช (ดี) แล้ว refresh เบื้องหลังได้ 503
    pg.wait_for_timeout(800)
    check("page still served from good cache while server returns 503", "สมุดบันทึกการเทรด" in pg.title())
    state["fail503"] = False
    state["down"] = True
    pg.goto(BASE + "/")
    check("503 body was NOT stored: offline reload still shows the real page", "ERR503" not in pg.content() and "สมุดบันทึกการเทรด" in pg.title(), pg.content()[:80])
    state["down"] = False

    # navigation ไปหน้าในขอบเขตที่ไม่เคยแคช: ต้องได้หน้านั้นจริงจากเครือข่าย ไม่ใช่ index.html แทน
    pg.goto(BASE + "/other.html")
    check("uncached in-scope page is fetched from network (not replaced by index.html)", pg.title() == "OTHER", pg.title())
    pg.goto(BASE + "/never-existed.html")
    check("online 404 page is shown as 404 (not masked by index.html)", "สมุดบันทึกการเทรด" not in pg.title(), pg.title())
    state["down"] = True
    pg.goto(BASE + "/never-existed.html")
    check("offline + uncached navigation falls back to index.html", "สมุดบันทึกการเทรด" in pg.title(), pg.title())
    state["down"] = False

    # revalidation ต้องข้าม HTTP cache (max-age=600) — เวอร์ชันใหม่ของ index.html ต้องเข้าแคช worker ภายในการเปิด 2 ครั้ง
    pg.goto(BASE + "/")
    state["indexB"] = True
    pg.goto(BASE + "/")                   # ตอบจากแคช (ยังเป็นเวอร์ชันเก่า) แล้วถามเซิร์ฟเวอร์เบื้องหลัง
    pg.wait_for_timeout(800)
    pg.goto(BASE + "/")
    check("new index.html reaches the SW cache despite max-age=600 (shown on the next open)", pg.title() == "VERSION-B", pg.title())
    state["indexB"] = False

    # ข้ามโดเมน: network-first แต่ไม่รอเครือข่ายที่ค้างเกิน 2.5 วินาทีเมื่อมีแคช · 5xx ไม่ถูกเก็บทับของดี
    first = pg.evaluate("(u)=>fetch(u).then(r=>r.text())", XBASE + "/font.css")
    check("cross-origin first fetch goes to network", first == "v1", first)
    pg.wait_for_timeout(300)
    state["xmode"] = "slow"
    t0 = pg.evaluate("performance.now()")
    second = pg.evaluate("(u)=>fetch(u).then(r=>r.text())", XBASE + "/font.css")
    dt = pg.evaluate("performance.now()") - t0
    check("cross-origin stalled network: cached copy used after ~2.5s (not 6s)", second == "v1" and 2000 < dt < 4500, (second, dt))
    state["xmode"] = "err"
    errtxt = pg.evaluate("(u)=>fetch(u).then(r=>r.status)", XBASE + "/font.css")
    pg.wait_for_timeout(300)
    state["down"] = True
    off = pg.evaluate("(u)=>fetch(u).then(r=>r.text())", XBASE + "/font.css")
    state["down"] = False
    state["xmode"] = "ok"
    check("cross-origin 503 was not stored over the good copy (offline returns v1)", off == "v1", (errtxt, off))

    # activate ลบเฉพาะแคชของแอปนี้ ไม่แตะแคชของโปรเจกต์อื่นบน origin เดียวกัน
    pg.evaluate("caches.open('other-app-v3').then(c=>c.put('/x', new Response('hi')))")
    state["swv"] = "v7"
    pg.evaluate("navigator.serviceWorker.getRegistration().then(r=>r.update())")
    pg.wait_for_function("caches.keys().then(k=>k.includes('trading-journal-v7'))", timeout=8000) if False else None
    for _ in range(40):
        ks = pg.evaluate("caches.keys()")
        if "trading-journal-v7" in ks and "trading-journal-v6" not in ks: break
        pg.wait_for_timeout(250)
    ks = pg.evaluate("caches.keys()")
    check("old app cache v6 removed, new v7 present", "trading-journal-v7" in ks and "trading-journal-v6" not in ks, ks)
    check("other project's cache is untouched", "other-app-v3" in ks, ks)

    check("no page errors", not errors, str(errors))

    # โฮสต์ที่ redirect /index.html → / : precache ต้องล้างธง redirected ไม่งั้น Chrome ปฏิเสธตอบ navigation ออฟไลน์
    ctx2 = b.new_context()
    pr = ctx2.new_page()
    state["redirIndex"] = True; state["swv"] = "v6"
    pr.goto(BASE + "/")
    pr.evaluate("new Promise(r=>navigator.serviceWorker.ready.then(()=>r(true)))")
    pr.reload(); pr.wait_for_function("!!navigator.serviceWorker.controller", timeout=8000)
    state["down"] = True
    try:
        pr.goto(BASE + "/index.html"); okr = "สมุดบันทึกการเทรด" in pr.title()
    except Exception as ex:
        okr = False
    check("redirected precache entry still serves /index.html offline (redirected flag cleaned)", okr, pr.title() if okr else "navigation failed")
    ctx2.close()
    b.close()

srv.shutdown()
print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
