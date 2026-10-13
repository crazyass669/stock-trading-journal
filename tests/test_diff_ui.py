"""
เทียบตัวเลขที่ "แสดงบนหน้าจอ" (การ์ดสรุป ตารางรายการ ตารางพอร์ต) กับตัวคำนวณอ้างอิงแบบเศษส่วนแม่นยำ — ครอบคลุมชั้นจัดรูปแบบ/การดึงค่า
"""
import json, random, sys, pathlib, os, re, datetime
from fractions import Fraction as F
from playwright.sync_api import sync_playwright

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
from _paths import REPO, TESTS, TMP
ROOT = TMP   # ที่เขียนไฟล์ชั่วคราว
URL = (pathlib.Path(os.environ["HTML_OVERRIDE"]) if os.environ.get("HTML_OVERRIDE") else REPO / "index.html").as_uri()
N = int(os.environ.get("N", "40"))

# นำตัวอ้างอิงจาก test_diff.py มาใช้ (ส่วนก่อนการสุ่ม) — แหล่งเดียว ไม่เขียนซ้ำ
src = (TESTS / "test_diff.py").read_text(encoding="utf-8")
head = src[: src.index("# ------------------------------------------------------------ สร้างชุดข้อมูลสุ่ม")]
ns = {"__name__": "ref", "__file__": str(TESTS / "test_diff.py")}   # ส่วนหัวของ test_diff.py ใช้ __file__ หาพาธ
exec(head, ns)   # noqa: S102 (ไฟล์ของเราเอง) — ใช้ namespace เดียว ไม่งั้นฟังก์ชันมองไม่เห็น import ของมัน
ref_ledger = ns["ref_ledger"]; ref_stats = ns["ref_stats"]

rnd = random.Random(int(os.environ.get("SEED", "99")))
def dec(lo, hi, places): return rnd.randint(int(lo * 10**places), int(hi * 10**places)) / 10**places
def scenario(k):
    syms = rnd.sample(["AAA", "BBB", "CCC"], rnd.randint(1, 3)); base = datetime.date(2026, 2, 1); out = []
    for i in range(rnd.randint(3, 14)):
        qty = rnd.choice([rnd.randint(1, 300), dec(0.01, 40, 2)]); price = dec(1, 150, rnd.choice([2, 4]))
        out.append({"id": f"u{k}_{i:02d}", "date": (base + datetime.timedelta(days=rnd.randint(0, 6))).isoformat(),
                    "symbol": rnd.choice(syms), "side": "buy" if rnd.random() < 0.55 else "sell", "qty": qty, "price": price,
                    "fee": rnd.choice([0, dec(0, 20, 2)]), "tag": ""})
    return out

num = lambda s: float(re.sub(r"[฿,\s]", "", s.replace("−", "-"))) if s.strip() not in ("", "—") else None
fails, checks = [], 0
def check(k, m, what, got, want, tol=0.0061):
    global checks; checks += 1
    ok = (got is None and want is None) or (got is not None and want is not None and abs(got - want) <= tol)
    if not ok: fails.append((k, m, what, got, want))

with sync_playwright() as p:
    b = getattr(p, os.environ.get("BROWSER", "chromium")).launch()
    pg = b.new_page(viewport={"width": 1280, "height": 900}); pg.on("dialog", lambda d: d.accept())
    pg.goto(URL)
    for k in range(N):
        tr = scenario(k)
        pg.evaluate("localStorage.clear()")
        pg.evaluate("(t)=>localStorage.setItem('trading-journal:trades', JSON.stringify(t))", tr)
        for m in ("FIFO", "AVG"):
            pg.evaluate("(m)=>localStorage.setItem('trading-journal:method', JSON.stringify(m))", m)
            pg.reload()
            ev, hd, sh = ref_ledger(tr, m)
            tot = sum((e["pnl"] for e in ev), F(0))
            check(k, m, "realized card", num(pg.inner_text("#statRealized")), float(tot))
            check(k, m, "cost basis card", num(pg.inner_text("#statCost")), float(sum((c for _, c, _ in hd.values()), F(0))))
            check(k, m, "fees card", num(pg.inner_text("#statFees")), float(sum((F(str(t["fee"])) for t in tr), F(0))))
            check(k, m, "trade count", num(pg.inner_text("#statTrades")), len(tr), 0)
            check(k, m, "holdings count", num(pg.inner_text("#statSymbols").replace("ตัว", "")), len(hd), 0)
            # รายการขายแต่ละแถว: กำไร/ขาดทุนในตาราง
            rows = pg.evaluate("""[...document.querySelectorAll('#tradeBody tr')].filter(r=>r.querySelector('[data-del]')).map(r=>({id:r.querySelector('[data-del]').dataset.del, pnl:r.children[7].innerText}))""")
            shown = {r["id"]: r["pnl"] for r in rows}
            for e in ev:
                check(k, m, f"row pnl {e['id']}", num(shown.get(e["id"], "").replace("⚠", "")), float(e["pnl"]))
            # อัตราชนะ
            if ev:
                wr = pg.inner_text("#statWinRate").strip()
                st = ref_stats(ev)
                check(k, m, "win rate %", num(wr.replace("%", "")), round(st["nWin"] / len(ev) * 100, 1), 0.051)
            # พอร์ต: ต้นทุนรวมแต่ละตัว
            hrows = pg.evaluate("""[...document.querySelectorAll('#holdingsBody tr')].filter(r=>r.children.length>3).map(r=>[r.children[0].innerText.trim(), r.children[3].innerText])""")
            for sym, text in hrows:
                check(k, m, f"holding cost {sym}", num(text), float(hd[sym][1]))
    b.close()

print(f"scenarios={N} (x2 methods) UI comparisons={checks} mismatches={len(fails)}")
for f in fails[:20]: print("MISMATCH", f)
sys.exit(1 if fails else 0)
