import json, sys, pathlib, os
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
    def mk():
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "fonts.g" not in m.text and "ERR_" not in m.text else None)
        pg.on("dialog", lambda d: (msgs.append(d.message), d.accept() if state["accept"] else d.dismiss()))
        return pg
    pg = mk(); pg.goto(URL); pg.evaluate("localStorage.clear()"); pg.reload()
    stored = lambda pg_, k: json.loads(pg_.evaluate(f"localStorage.getItem('trading-journal:{k}')"))
    txt = lambda pg_, sel: pg_.inner_text(sel).strip()
    setls = lambda pg_, k, v: pg_.evaluate("([k,v])=>localStorage.setItem('trading-journal:'+k, JSON.stringify(v))", [k, v])
    wait = lambda pg_=None: (pg_ or pg).wait_for_timeout(350)   # ตัวจัดการลบรอ 1 รอบ event loop หลัง confirm

    T = lambda i, d, sym, side="buy": {"id": i, "date": d, "symbol": sym, "side": side, "qty": 100, "price": 10, "fee": 0}
    seed = [T("t1", "2026-01-05", "AAA"), T("t2", "2026-01-05", "BBB"), T("t3", "2026-01-05", "CCC"), T("t4", "2026-01-06", "DDD")]
    setls(pg, "trades", seed); pg.reload()

    # ---- ลบ → แถบเลิกทำ
    check("undo bar hidden at start", pg.is_hidden("#undoBar"))
    pg.click("#tradeBody tr:has-text('BBB') [data-del]"); wait()
    check("delete shows the undo bar naming the trade", pg.is_visible("#undoBar") and "BBB" in txt(pg, "#undoText"), txt(pg, "#undoText"))
    check("delete removed BBB", [t["symbol"] for t in stored(pg, "trades")] == ["AAA", "CCC", "DDD"])
    pg.click("#undoBtn"); wait()
    order = [t["id"] for t in stored(pg, "trades")]
    check("undo restores BBB at its original position (same-day order kept)", order == ["t1", "t2", "t3", "t4"], order)
    check("undo bar hides when nothing left to undo", pg.is_hidden("#undoBar"))
    check("table shows BBB again", "BBB" in txt(pg, "#tradeBody"))

    # ---- ยกเลิกกล่องยืนยัน = ไม่ลบ ไม่มีแถบ
    state["accept"] = False
    pg.click("#tradeBody tr:has-text('CCC') [data-del]"); wait()
    state["accept"] = True
    check("cancelled confirm: nothing deleted, no undo bar", len(stored(pg, "trades")) == 4 and pg.is_hidden("#undoBar"))

    # ---- ลบหลายรายการ (ซื้อขาย + ปันผล + อารมณ์) เลิกทำย้อนทีละรายการ
    setls(pg, "dividends", [{"id": "d1", "date": "2026-02-01", "symbol": "AAA", "gross": 100, "tax": 10}]); setls(pg, "moods", [{"id": "m1", "date": "2026-02-01T10:00:00.000Z", "mood": "4", "note": "เดิม"}]); pg.reload()
    pg.click("#tradeBody tr:has-text('AAA') [data-del]"); wait()
    pg.click("#divBody [data-deldiv]"); wait()
    pg.click("#moodEntries [data-delmood]"); wait()
    check("three deletes stack: button shows (3)", "(3)" in txt(pg, "#undoBtn") and "อีก 2 รายการ" in txt(pg, "#undoText"), (txt(pg, "#undoBtn"), txt(pg, "#undoText")))
    check("all three removed", len(stored(pg, "trades")) == 3 and stored(pg, "dividends") == [] and stored(pg, "moods") == [])
    pg.click("#undoBtn"); wait()
    check("1st undo restores the mood (latest delete first)", len(stored(pg, "moods")) == 1 and stored(pg, "dividends") == [] and "(2)" in txt(pg, "#undoBtn"), txt(pg, "#undoBtn"))
    pg.click("#undoBtn"); wait()
    check("2nd undo restores the dividend", len(stored(pg, "dividends")) == 1)
    pg.click("#undoBtn"); wait()
    check("3rd undo restores the trade first in array (afterId null)", [t["id"] for t in stored(pg, "trades")][0] == "t1" and pg.is_hidden("#undoBar"), [t["id"] for t in stored(pg, "trades")])

    # ---- กดซ้ำเร็วๆ ไม่คืนซ้ำ
    pg.click("#tradeBody tr:has-text('DDD') [data-del]"); wait()
    pg.evaluate("document.getElementById('undoBtn').click(); document.getElementById('undoBtn').click();"); wait()
    ids = [t["id"] for t in stored(pg, "trades")]
    check("double-click on undo restores once", ids.count("t4") == 1 and len(ids) == 4, ids)

    # ---- ลบรายการที่กำลังแก้ไข แล้วเลิกทำ
    pg.click("#tradeBody tr:has-text('CCC') [data-edit]")
    check("in edit mode", "แก้ไข" in txt(pg, "#addTradeBtn"))
    pg.click("#tradeBody tr:has-text('CCC') [data-del]"); wait()
    check("deleting the edited trade leaves edit mode", txt(pg, "#addTradeBtn") == "+ บันทึก")
    pg.click("#undoBtn"); wait()
    check("undo brings it back", "CCC" in txt(pg, "#tradeBody") and len(stored(pg, "trades")) == 4)

    # ---- แท็บอื่นเพิ่มรายการระหว่างที่แถบเลิกทำเปิดอยู่ → เลิกทำต้องไม่ทำให้รายการนั้นหาย
    pg2 = mk(); pg2.goto(URL)
    pg.click("#tradeBody tr:has-text('BBB') [data-del]"); wait()
    pg2.evaluate("""(()=>{ const k='trading-journal:trades'; const a=JSON.parse(localStorage.getItem(k));
      a.push({id:'other-tab',date:'2026-01-09',symbol:'ZZZ',side:'buy',qty:1,price:1,fee:0}); localStorage.setItem(k, JSON.stringify(a)); })()""")
    pg.wait_for_timeout(400)
    pg.click("#undoBtn"); wait()
    syms = [t["symbol"] for t in stored(pg, "trades")]
    check("undo after another tab's write keeps both (BBB back, ZZZ kept)", "BBB" in syms and "ZZZ" in syms, syms)
    pg2.close()

    # ---- หมดเวลา (15 วินาที) แถบหายและเลิกทำไม่ได้อีก
    try:
        pc = mk()
        pc.clock.install(time="2026-10-13T10:00:00")
        pc.goto(URL); pc.evaluate("localStorage.clear()"); pc.reload()
        setls(pc, "trades", seed); pc.reload()
        pc.click("#tradeBody tr:has-text('BBB') [data-del]"); pc.clock.run_for(400)
        check("TTL: bar visible right after delete", pc.is_visible("#undoBar"))
        pc.clock.run_for(14000)
        check("TTL: still visible at ~14.4s", pc.is_visible("#undoBar"))
        pc.clock.run_for(2000)
        check("TTL: hidden after 15s", pc.is_hidden("#undoBar"))
        pc.close()
    except AttributeError:
        print("SKIP TTL (playwright clock API unavailable)")

    # ---- เลิกทำการนำเข้า
    pg.evaluate("localStorage.clear()"); pg.reload()
    setls(pg, "trades", [T("o1", "2026-01-01", "OLD")]); setls(pg, "settings", {"autoFee": True, "commRate": 0.2, "minFee": 0, "vat": 7, "divTax": 10}); pg.reload()
    imp = ROOT / "imp_undo.json"
    imp.write_text(json.dumps({"trades": [T("n1", "2026-03-01", "NEW"), T("n2", "2026-03-02", "NEW2")], "settings": {"autoFee": False, "commRate": 0.5, "minFee": 0, "vat": 7, "divTax": 10}}), encoding="utf-8")
    msgs.clear()
    pg.set_input_files("#importFile", str(imp)); pg.wait_for_timeout(600)
    check("import done + undo bar offers to undo the import", [t["symbol"] for t in stored(pg, "trades")] == ["NEW", "NEW2"] and pg.is_visible("#undoBar") and "นำเข้า" in txt(pg, "#undoText"), txt(pg, "#undoText"))
    check("import cleared older delete-undo entries (button has no count)", "(" not in txt(pg, "#undoBtn"), txt(pg, "#undoBtn"))
    msgs.clear()
    pg.click("#undoBtn"); pg.wait_for_timeout(500)
    check("undo import restores old trades/settings in storage", [t["symbol"] for t in stored(pg, "trades")] == ["OLD"] and stored(pg, "settings")["commRate"] == 0.2 and stored(pg, "settings")["autoFee"] is True, (stored(pg, "trades"), stored(pg, "settings")))
    check("undo import restores screen + settings form", "OLD" in txt(pg, "#tradeBody") and "NEW" not in txt(pg, "#tradeBody") and pg.input_value("#s-rate") == "0.2")
    check("no confirm needed when nothing changed after import", not any("มีการเปลี่ยนแปลงหลังนำเข้า" in m for m in msgs), msgs)

    # นำเข้า → แก้ไขเพิ่ม → เลิกทำนำเข้า ต้องถามยืนยัน
    pg.set_input_files("#importFile", str(imp)); pg.wait_for_timeout(600)
    pg.fill("#f-symbol", "late"); pg.fill("#f-qty", "1"); pg.fill("#f-price", "1"); pg.click("#addTradeBtn")
    msgs.clear(); state["accept"] = False
    pg.click("#undoBtn"); pg.wait_for_timeout(500)
    check("undo import after later edits asks first; cancel keeps current data", any("มีการเปลี่ยนแปลงหลังนำเข้า" in m for m in msgs) and "LATE" in [t["symbol"] for t in stored(pg, "trades")], msgs)
    check("cancelled import-undo stays available", pg.is_visible("#undoBar"))
    state["accept"] = True
    pg.click("#undoBtn"); pg.wait_for_timeout(600)
    check("confirmed import-undo restores pre-import data", [t["symbol"] for t in stored(pg, "trades")] == ["OLD"], [t["symbol"] for t in stored(pg, "trades")])

    # ---- แถบไม่บังปุ่มสำคัญบนมือถือ + ไม่ล้นจอ
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.click("#tradeBody tr:has-text('OLD') [data-del]"); wait()
    box = pg.evaluate("(()=>{const r=document.getElementById('undoBar').getBoundingClientRect(); return [r.left, r.right, window.innerWidth, r.bottom, window.innerHeight];})()")
    check("undo bar fits inside a 390px screen", box[0] >= 0 and box[1] <= box[2] and box[3] <= box[4], box)
    pg.screenshot(path=str(ROOT / "tj_undo_mobile.png"))

    check("no console/page errors", not errors, str(errors))
    b.close()

print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
