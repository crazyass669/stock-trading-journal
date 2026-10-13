import json, sys, pathlib, os, re
from playwright.sync_api import sync_playwright

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
from _paths import REPO, TESTS, TMP
ROOT = TMP   # ที่เขียนไฟล์ชั่วคราว
URL = (REPO / "index.html").as_uri()
fails = []

def check(name, cond, extra=""):
    print(("PASS " if cond else "FAIL ") + name + (f"  [{extra}]" if (extra and not cond) else ""))
    if not cond:
        fails.append(name)

with sync_playwright() as p:
    b = getattr(p, os.environ.get("BROWSER", "chromium")).launch()
    ctx = b.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
    errors, msgs = [], []
    state = {"accept": True}
    def mk(clock_time=None):
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "fonts.g" not in m.text and "ERR_" not in m.text and "quota" not in m.text.lower() else None)
        pg.on("dialog", lambda d: (msgs.append(d.message), d.accept() if state["accept"] else d.dismiss()))
        if clock_time: pg.clock.install(time=clock_time)
        return pg
    stored = lambda pg_, k: json.loads(pg_.evaluate(f"localStorage.getItem('trading-journal:{k}')"))
    txt = lambda pg_, sel: pg_.inner_text(sel).strip()
    setls = lambda pg_, k, v: pg_.evaluate("([k,v])=>localStorage.setItem('trading-journal:'+k, JSON.stringify(v))", [k, v])
    T = lambda i, d, sym, side="buy", **kw: {"id": i, "date": d, "symbol": sym, "side": side, "qty": 100, "price": 10, "fee": 0, **kw}
    def fresh(pg_, **data):
        pg_.evaluate("localStorage.clear()")
        for k, v in data.items(): setls(pg_, k, v)
        pg_.reload()
    imp_file = ROOT / "imp6.json"
    imp_file.write_text(json.dumps({"trades": [T("z1", "2026-03-01", "ZZZ"), T("z2", "2026-03-02", "YYY")]}), encoding="utf-8")

    a = mk(); a.goto(URL)

    # ---- R3-1) อีกแท็บนำเข้าข้อมูลทั้งชุด → รายการเลิกทำเดิมใช้ไม่ได้
    fresh(a, trades=[T("a1", "2026-01-05", "AAA"), T("a2", "2026-01-05", "BBB")])
    bt = mk(); bt.goto(URL)
    a.click("#tradeBody tr:has-text('BBB') [data-del]"); a.wait_for_timeout(400)
    check("R3-1 delete shows undo bar in tab A", a.is_visible("#undoBar"))
    bt.set_input_files("#importFile", str(imp_file)); bt.wait_for_timeout(700)
    a.wait_for_timeout(500)
    # WebKit ไม่ส่งเหตุการณ์ storage ข้ามแท็บเมื่อเปิดผ่าน file:// (ผ่าน http ส่งปกติ) — ปลุกแท็บ A แบบเดียวกับที่ผู้ใช้สลับกลับมา
    # เพื่อทดสอบกลไกสำรองของแอป (ซิงก์ตอน focus/visibilitychange) ให้ใช้ได้ทุกเบราว์เซอร์
    a.evaluate("window.dispatchEvent(new Event('focus'))"); a.wait_for_timeout(300)
    check("R3-1 tab B's import invalidates tab A's pending undo (bar hidden)", a.is_hidden("#undoBar"))
    check("R3-1 tab A now shows the imported data", "ZZZ" in txt(a, "#tradeBody") and "BBB" not in txt(a, "#tradeBody"))
    syms = sorted(t["symbol"] for t in stored(a, "trades"))
    check("R3-1 imported dataset not polluted by the old deleted trade", syms == ["YYY", "ZZZ"], syms)
    bt.close()

    # ---- R3-2) เลิกทำนำเข้า: เปลี่ยนราคาตลาด/ตั้งค่าหลังนำเข้า ต้องถามยืนยัน
    fresh(a, trades=[T("o1", "2026-01-01", "OLD")], marketPrices={})
    a.set_input_files("#importFile", str(imp_file)); a.wait_for_timeout(700)
    a.fill(".mp-input[data-mp='ZZZ']", "12")       # พิมพ์ราคาตลาดหลังนำเข้า (ไม่แตะรายการซื้อขาย)
    msgs.clear()
    a.click("#undoBtn"); a.wait_for_timeout(500)
    check("R3-2 undo import asks first when market price changed since import", any("มีการเปลี่ยนแปลงหลังนำเข้า" in m for m in msgs), msgs)
    check("R3-2 confirmed: old data restored", [t["symbol"] for t in stored(a, "trades")] == ["OLD"])

    # ---- R3-3) คืนรายการตามลำดับในวันเดียวกัน แม้รายการก่อนหน้าถูกย้ายวันที่
    fresh(a, trades=[T("x1", "2026-01-05", "A1"), T("x2", "2026-01-05", "AAA"), T("x3", "2026-01-05", "A3")])
    a.click("#tradeBody tr:has-text('AAA') [data-del]"); a.wait_for_timeout(400)
    a.click("#tradeBody tr:has-text('A1') [data-edit]"); a.fill("#f-date", "2026-01-09"); a.click("#addTradeBtn")
    a.click("#undoBtn"); a.wait_for_timeout(400)
    order = [t["id"] for t in stored(a, "trades")]
    check("R3-3 undo puts AAA back before A3 on the same day (not after the moved A1)", order == ["x2", "x3", "x1"], order)

    # ---- R3-4) อายุแยกรายรายการ: ลบหลังนำเข้าไม่ตัดเวลา 60 วินาทีของการนำเข้า
    try:
        pc = mk("2026-10-13T10:00:00"); pc.goto(URL); fresh(pc, trades=[T("o1", "2026-01-01", "OLD")])
        pc.set_input_files("#importFile", str(imp_file)); pc.clock.run_for(800)
        pc.click("#tradeBody tr:has-text('ZZZ') [data-del]"); pc.clock.run_for(800)
        check("R3-4 two entries stacked (import + delete)", "(2)" in txt(pc, "#undoBtn"), txt(pc, "#undoBtn"))
        pc.clock.run_for(16000)
        check("R3-4 delete entry expired at 15s but import undo still offered", pc.is_visible("#undoBar") and "นำเข้า" in txt(pc, "#undoText") and "(" not in txt(pc, "#undoBtn"), (txt(pc, "#undoText"), txt(pc, "#undoBtn")))
        pc.clock.run_for(50000)
        check("R3-4 import undo expires after its own 60s", pc.is_hidden("#undoBar"))
        pc.close()
    except AttributeError:
        print("SKIP R3-4 (clock API)")

    # ---- R3-5) เลิกทำนำเข้าไม่ล้างสิ่งที่กำลังพิมพ์
    fresh(a, trades=[T("o1", "2026-01-01", "OLD")])
    a.set_input_files("#importFile", str(imp_file)); a.wait_for_timeout(700)
    a.fill("#f-symbol", "typing"); a.fill("#f-note", "ยังไม่ได้บันทึก"); a.fill("#moodNote", "อารมณ์ที่พิมพ์ค้าง")
    a.click("#undoBtn"); a.wait_for_timeout(500)
    check("R3-5 unsaved typing survives import undo", a.input_value("#f-symbol") == "typing" and a.input_value("#f-note") == "ยังไม่ได้บันทึก" and a.input_value("#moodNote") == "อารมณ์ที่พิมพ์ค้าง")
    check("R3-5 ...and the data was restored", [t["symbol"] for t in stored(a, "trades")] == ["OLD"])

    # ---- R3-6) แก้รายการเดียวกันสองแท็บ: ไม่ย้อนโน้ตของอีกแท็บ
    fresh(a, trades=[T("e1", "2026-01-01", "EDT", note="orig")])
    bt = mk(); bt.goto(URL)
    a.click("[data-edit]")
    bt.click("[data-edit]"); bt.fill("#f-note", "changed in B"); bt.click("#addTradeBtn")
    a.wait_for_timeout(500)
    a.fill("#f-qty", "250"); a.click("#addTradeBtn")
    tr = stored(a, "trades")[0]
    check("R3-6 qty edit from A kept AND note edit from B kept", tr["qty"] == 250 and tr["note"] == "changed in B", tr)
    bt.close()

    # ---- R3-7) ภาษีปันผลใช้ตั้งค่าล่าสุด
    fresh(a)
    a.evaluate("localStorage.setItem('trading-journal:settings', JSON.stringify({autoFee:false,commRate:0.157,minFee:0,vat:7,divTax:15}))")  # อีกแท็บเปลี่ยนเป็น 15% (แท็บนี้ไม่ได้รับเหตุการณ์)
    a.fill("#d-symbol", "ptt"); a.fill("#d-gross", "1000"); a.click("#addDivBtn")
    d = stored(a, "dividends")[0]
    check("R3-7 dividend tax = 15% of 1000 from the latest settings", d["tax"] == 150, d)

    # ---- R3-8) วันที่เริ่มต้นเลื่อนเมื่อโฟกัสกลับ / เมื่อเวลาผ่านไปตอนเปิดค้าง
    try:
        pd = mk("2026-10-13T23:50:00"); pd.goto(URL); fresh(pd)
        check("R3-8 starts on 2026-10-13", pd.input_value("#f-date") == "2026-10-13")
        pd.clock.set_system_time("2026-10-14T00:30:00")
        pd.evaluate("window.dispatchEvent(new Event('focus'))")
        check("R3-8 focus (without visibilitychange) rolls the dates", pd.input_value("#f-date") == "2026-10-14" and pd.input_value("#d-date") == "2026-10-14", pd.input_value("#f-date"))
        pd.clock.set_system_time("2026-10-15T00:10:00"); pd.clock.run_for(61000)
        check("R3-8 timer rolls the dates while the window stays focused", pd.input_value("#f-date") == "2026-10-15", pd.input_value("#f-date"))
        pd.close()
    except AttributeError:
        print("SKIP R3-8 (clock API)")

    # ---- R3-9) storageOK กลับเป็นปกติเมื่อเขียนได้อีก
    fresh(a)
    a.evaluate("""(()=>{ const o = Storage.prototype.setItem; window.__o = o; window.__fail = true;
      Storage.prototype.setItem = function(k,v){ if(window.__fail && k==='trading-journal:meta') throw new DOMException('q','QuotaExceededError'); return o.call(this,k,v); }; })()""")
    a.fill("#f-symbol", "okk"); a.fill("#f-qty", "1"); a.fill("#f-price", "1"); a.click("#addTradeBtn")
    check("R3-9 failed write shows the warning stamp", "บันทึกไม่ได้" in txt(a, "#statusStamp"), txt(a, "#statusStamp"))
    a.evaluate("window.__fail = false")
    a.fill("#f-symbol", "okk2"); a.fill("#f-qty", "1"); a.fill("#f-price", "1"); a.click("#addTradeBtn")
    check("R3-9 next successful write clears the warning", "บันทึกไม่ได้" not in txt(a, "#statusStamp"), txt(a, "#statusStamp"))

    # ---- R3-10) วันที่ของอารมณ์ที่ซ่อมต้องคงที่
    fresh(a, moods=[{"id": "m1", "mood": "4", "note": "ไม่มีวันที่"}, {"id": "m2", "date": 1760000000000, "mood": "3", "note": "timestamp"},
                    {"id": "mv5ug0aa" + "xyz12", "mood": "2", "note": "จาก id"}])
    t1 = txt(a, "#moodEntries"); a.reload(); t2 = txt(a, "#moodEntries")
    check("R3-10 repaired mood dates identical across reloads", t1 == t2, (t1, t2))
    check("R3-10 numeric timestamp kept (2025-10)", "2025" in t1, t1)
    check("R3-10 date derived from id (2026-10)", "2026" in t1, t1)

    check("no console/page errors", not errors, str(errors))
    b.close()

print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
