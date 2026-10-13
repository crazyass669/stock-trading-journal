"""
เวอร์ชันของแอปและวันที่ปล่อย (แสดงเป็น "V1.1 13/10/2026"): ค่าคงที่ในโค้ดต้องรูปแบบถูก, แสดงบนหน้าจอตรงกัน,
ไม่เลื่อนวันตามเขตเวลาของเครื่อง, ไม่ล้น/ไม่ถูกตัดบนมือถือ, รูปแบบวันที่ผิดต้องไม่ทำให้แอปล้ม
"""
import datetime, os, pathlib, re, sys
from playwright.sync_api import sync_playwright
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _paths import REPO

URL = (REPO / "index.html").as_uri()
src = (REPO / "index.html").read_text(encoding="utf-8")
fails = []

def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond:
        fails.append(name)

def const(name):
    # ยอมรับ ' หรือ " และ const/let เพื่อไม่ให้การจัดรูปแบบโค้ดทำให้เทสต์ล้มด้วย traceback
    m = re.search(rf"(?:const|let|var)\s+{name}\s*=\s*(['\"])(.*?)\1\s*;", src)
    return m.group(2) if m else None

VERSION, DATE = const("APP_VERSION"), const("APP_DATE")
check("APP_VERSION and APP_DATE are defined once each", VERSION is not None and DATE is not None
      and len(re.findall(r"\bAPP_VERSION\s*=", src)) == 1 and len(re.findall(r"\bAPP_DATE\s*=", src)) == 1, (VERSION, DATE))
check("version is major.minor (e.g. 2.1)", VERSION is not None and re.fullmatch(r"\d+\.\d+", VERSION) is not None, VERSION)
d, ok = None, False
try:
    d = datetime.date.fromisoformat(DATE or ""); ok = re.fullmatch(r"\d{4}-\d{2}-\d{2}", DATE) is not None
except ValueError:
    pass
check("release date is a real YYYY-MM-DD date", ok, DATE)
# เผื่อ 1 วัน: นักพัฒนาอยู่เขตเวลาที่นำหน้า UTC (วันที่ในไฟล์อาจ "ล้ำ" วันที่ของเครื่องที่ล้าหลัง) — เช็กแค่ว่าไม่ได้ตั้งไว้ไกลในอนาคต
check("release date is not set in the future (1-day tolerance for timezones)", ok and d <= datetime.date.today() + datetime.timedelta(days=1), DATE)
expected = f"V{VERSION} {d.day:02d}/{d.month:02d}/{d.year}" if ok and VERSION else ""

with sync_playwright() as p:
    b = getattr(p, os.environ.get("BROWSER", "chromium")).launch()
    errors = []

    def run(tz="Asia/Bangkok", width=1280, init_script=None):
        ctx = b.new_context(viewport={"width": width, "height": 900}, timezone_id=tz)
        pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append(str(e)))
        if init_script: pg.add_init_script(init_script)
        pg.goto(URL); pg.wait_for_timeout(200)
        out = {
            "text": pg.inner_text("#appVersion").strip(),
            "title_attr": pg.get_attribute("#appVersion", "title"),
            "visible": pg.is_visible("#appVersion"),
            "noHScroll": pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"),
            "inside": pg.evaluate("""() => { const v = document.getElementById('appVersion').getBoundingClientRect();
                                           const h = document.querySelector('.ledger-head').getBoundingClientRect();
                                           return v.left >= h.left - 1 && v.right <= h.right + 1; }"""),
            "loaded": pg.inner_text("#statusStamp").strip(),
        }
        ctx.close(); return out

    r = run()
    check("label shows exactly 'V<major.minor> DD/MM/YYYY'", r["text"] == expected, (r["text"], expected))
    check("label has no extra decoration (no tooltip)", r["title_attr"] is None, r["title_attr"])
    check("label is visible", r["visible"])
    check("app finished loading normally (status stamp set)", "กำลังโหลด" not in r["loaded"], r["loaded"])
    # วันที่ต่อข้อความเอง ไม่ผ่านเขตเวลา → ต้องเหมือนกันทุกเขต
    for tz in ("Pacific/Kiritimati", "Pacific/Pago_Pago", "America/Los_Angeles"):
        rr = run(tz)
        check(f"date identical in timezone {tz}", rr["text"] == expected, (rr["text"], expected))
    for w in (390, 320):
        rm = run(width=w)
        check(f"mobile {w}px: visible, no page scroll, not clipped by the header", rm["visible"] and rm["noHScroll"] and rm["inside"], rm)

    # APP_DATE รูปแบบผิด (เช่น 2026-10-1) ต้องไม่ทำให้แอปล้ม และแสดงค่าดิบแทน
    bad_html = (REPO / "index.html").read_text(encoding="utf-8").replace(f"'{DATE}'", "'2026-10-1'", 1)
    tmp = pathlib.Path(os.environ.get("TEMP", ".")) / "tj_version_bad_date.html"
    tmp.write_text(bad_html, encoding="utf-8")
    ctx = b.new_context(); pg = ctx.new_page(); pg.on("pageerror", lambda e: errors.append("bad-date page: " + str(e)))
    pg.goto(tmp.as_uri()); pg.wait_for_timeout(200)
    check("malformed APP_DATE: shows the raw value and the app still loads",
          pg.inner_text("#appVersion").strip() == f"V{VERSION} 2026-10-1" and "กำลังโหลด" not in pg.inner_text("#statusStamp"),
          (pg.inner_text("#appVersion"), pg.inner_text("#statusStamp")))
    ctx.close()
    check("no page errors", not errors, str(errors))
    b.close()

print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
