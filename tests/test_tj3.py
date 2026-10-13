import json, sys, pathlib
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
    b = p.chromium.launch()
    ctx = b.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "fonts.g" not in m.text and "ERR_" not in m.text else None)
    msgs = []
    pg.on("dialog", lambda d: (msgs.append(d.message), d.accept()))
    pg.goto(URL); pg.evaluate("localStorage.clear()"); pg.reload()
    txt = lambda sel: pg.inner_text(sel).strip()
    stored = lambda k: json.loads(pg.evaluate(f"localStorage.getItem('trading-journal:{k}')"))
    setls = lambda k, v: pg.evaluate("([k,v])=>localStorage.setItem('trading-journal:'+k, JSON.stringify(v))", [k, v])

    # ---- A) ขายแล้วซื้อกลับวันเดียวกัน ขณะถืออยู่แล้ว ต้องคงลำดับตามที่บันทึก (ไม่ปนต้นทุนไม้ที่ซื้อทีหลัง)
    setls("trades", [
        {"id": "a1", "date": "2026-01-01", "symbol": "AAA", "side": "buy",  "qty": 100, "price": 50, "fee": 0},
        {"id": "a2", "date": "2026-01-05", "symbol": "AAA", "side": "sell", "qty": 100, "price": 60, "fee": 0},
        {"id": "a3", "date": "2026-01-05", "symbol": "AAA", "side": "buy",  "qty": 100, "price": 70, "fee": 0},
    ])
    for m in ("FIFO", "AVG"):
        pg.reload()
        pg.click(f"#methodToggle button[data-m={m}]")
        check(f"A {m}: sell-then-rebuy pnl = +1,000", "1,000.00" in txt("#statRealized") and pg.is_hidden("#warnBox"), txt("#statRealized"))
        check(f"A {m}: remaining cost = 7,000 (rebuy lot 70)", "7,000.00" in txt("#statCost"), txt("#statCost"))

    # ---- B) ลงขายก่อนซื้อ (ไม่มีของในมือ) ยังสลับเป็นซื้อก่อนขาย
    setls("trades", [
        {"id": "b1", "date": "2026-01-05", "symbol": "BBB", "side": "sell", "qty": 100, "price": 12, "fee": 0},
        {"id": "b2", "date": "2026-01-05", "symbol": "BBB", "side": "buy",  "qty": 100, "price": 10, "fee": 0},
    ])
    pg.reload()
    check("B reversed entry order still fixed (no warning, pnl 200)", pg.is_hidden("#warnBox") and "200.00" in txt("#statRealized"), txt("#statRealized"))

    # ---- C) แท็กชื่อพิเศษ + ตัวพิมพ์
    setls("trades", [
        {"id": "c0", "date": "2026-01-01", "symbol": "CCC", "side": "buy", "qty": 1000, "price": 10, "fee": 0, "tag": "constructor"},
        {"id": "c1", "date": "2026-01-02", "symbol": "CCC", "side": "sell", "qty": 100, "price": 11, "fee": 0, "tag": "constructor"},
        {"id": "c2", "date": "2026-01-03", "symbol": "CCC", "side": "sell", "qty": 100, "price": 12, "fee": 0, "tag": "toString"},
        {"id": "c3", "date": "2026-01-04", "symbol": "CCC", "side": "sell", "qty": 100, "price": 13, "fee": 0, "tag": "Breakout"},
        {"id": "c4", "date": "2026-01-05", "symbol": "CCC", "side": "sell", "qty": 100, "price": 14, "fee": 0, "tag": "breakout"},
        {"id": "c5", "date": "2026-01-06", "symbol": "CCC", "side": "sell", "qty": 100, "price": 15, "fee": 0, "tag": "__proto__"},
    ])
    pg.reload()
    pg.select_option("#groupMode", "tag")
    body = txt("#groupBody")
    check("C no NaN in group table", "NaN" not in body, body)
    rows = pg.evaluate("[...document.querySelectorAll('#groupBody tr')].map(r=>[...r.children].map(c=>c.innerText.trim()))")
    keys = [r[0] for r in rows]
    check("C special tag names shown as own groups", "constructor" in keys and "toString" in keys and "__proto__" in keys, keys)
    br = [r for r in rows if r[0].lower() == "breakout"]
    check("C Breakout/breakout merged into one row of 2 trades", len(br) == 1 and br[0][1].startswith("2 "), br)

    # ---- D) ค่าติดลบ
    pg.evaluate("localStorage.clear()"); pg.reload(); msgs.clear()
    pg.fill("#d-symbol", "ptt"); pg.fill("#d-gross", "1000"); pg.fill("#d-tax", "-500"); pg.click("#addDivBtn")
    check("D negative dividend tax rejected", len(msgs) == 1 and "ไม่ติดลบ" in msgs[0] and not pg.evaluate("localStorage.getItem('trading-journal:dividends')"), msgs)
    msgs.clear()
    pg.fill("#f-symbol", "ptt"); pg.fill("#f-qty", "10"); pg.fill("#f-price", "10"); pg.fill("#f-fee", "-5"); pg.click("#addTradeBtn")
    check("D negative fee rejected", len(msgs) == 1 and "ไม่ติดลบ" in msgs[0] and not pg.evaluate("localStorage.getItem('trading-journal:trades')"), msgs)

    # ---- E) auto fee hint ตอนโหลดหน้า / หลังนำเข้า
    setls("settings", {"autoFee": True, "commRate": 0.157, "minFee": 0, "vat": 7, "divTax": 10})
    pg.reload()
    ph = pg.get_attribute("#f-fee", "placeholder")
    check("E placeholder reflects auto-fee on load", "อัตโนมัติ" in ph, ph)
    check("E hint visible on load", pg.is_visible("#feeHint"))

    # ---- F) ช่องตั้งค่าว่าง -> เขียนค่าที่ถูกใช้จริงกลับลงฟอร์ม
    pg.evaluate("document.getElementById('settingsPanel').open = true")
    pg.fill("#s-rate", ""); pg.dispatch_event("#s-rate", "change")
    check("F blank commission snaps back to stored default in the form", pg.input_value("#s-rate") == "0.157", pg.input_value("#s-rate"))
    pg.fill("#s-rate", "0.2"); pg.dispatch_event("#s-rate", "change")
    check("F custom commission stored", stored("settings")["commRate"] == 0.2)

    # ---- G) นำเข้าไฟล์ v1 ไม่รีเซ็ตตั้งค่า + H) ข้ามแถวเสีย
    v1 = {"version": 1, "exportedAt": "2026-01-01T00:00:00.000Z",
          "trades": [
              {"id": "x1", "date": "2026-01-02", "symbol": "ok", "side": "buy", "qty": 10, "price": 5, "fee": 1},
              {"id": "x2", "date": "=HYPERLINK(\"http://evil\")", "symbol": "bad", "side": "buy", "qty": 10, "price": 5, "fee": 0},
              {"id": "x3", "date": "2026-02-30", "symbol": "bad2", "side": "buy", "qty": 10, "price": 5, "fee": 0},
              {"id": "x4", "date": "2026-01-03", "symbol": "neg", "side": "buy", "qty": 10, "price": 5, "fee": -9},
              {"symbol": "nodate", "side": "buy", "qty": 1, "price": 1},
          ],
          "moods": [], "method": "FIFO", "marketPrices": {}}
    f = ROOT / "v1b.json"; f.write_text(json.dumps(v1), encoding="utf-8")
    msgs.clear()
    pg.set_input_files("#importFile", str(f)); pg.wait_for_timeout(300)
    t = stored("trades")
    check("G import v1 keeps current settings (rate 0.2, autoFee on)", stored("settings")["commRate"] == 0.2 and stored("settings")["autoFee"] is True, stored("settings"))
    check("G form still shows kept settings", pg.input_value("#s-rate") == "0.2")
    check("H invalid rows skipped (only 'OK' kept)", [x["symbol"] for x in t] == ["OK"], t)
    check("H alert mentions skipped count 4", any("ข้าม 4" in m for m in msgs), msgs)

    # ---- I) แก้ไขรายการที่ค่าธรรมเนียมระบบคิดให้ -> คิดใหม่ตามจำนวนที่แก้
    pg.evaluate("localStorage.clear()"); pg.reload()
    setls("settings", {"autoFee": True, "commRate": 0.157, "minFee": 0, "vat": 7, "divTax": 10}); pg.reload()
    pg.fill("#f-symbol", "ptt"); pg.fill("#f-qty", "1000"); pg.fill("#f-price", "10"); pg.fill("#f-fee", ""); pg.click("#addTradeBtn")
    tr = stored("trades")[0]
    check("I auto fee saved with feeAuto flag", abs(tr["fee"] - 16.80) < 0.005 and tr["feeAuto"] is True, tr)
    # K) แก้แค่แท็กหลังเปลี่ยนอัตราค่าคอม -> ค่าธรรมเนียมในอดีตต้องไม่ถูกเขียนทับ
    pg.evaluate("document.getElementById('settingsPanel').open = true")
    pg.fill("#s-rate", "0.3"); pg.dispatch_event("#s-rate", "change")
    pg.click("[data-edit]")
    check("K edit shows the stored fee (16.8), not recalculated", abs(float(pg.input_value("#f-fee")) - 16.8) < 0.005, pg.input_value("#f-fee"))
    pg.fill("#f-tag", "newtag"); pg.click("#addTradeBtn")
    tr = stored("trades")[0]
    check("K tag-only edit keeps historical fee 16.80 and feeAuto", abs(tr["fee"] - 16.80) < 0.005 and tr["feeAuto"] is True and tr["tag"] == "newtag", tr)
    pg.fill("#s-rate", "0.157"); pg.dispatch_event("#s-rate", "change")

    # I) เปลี่ยนจำนวนระหว่างแก้ไข -> ช่องค่าธรรมเนียมคิดใหม่ให้
    pg.click("[data-edit]")
    pg.fill("#f-qty", "2000")
    check("I fee box recalculated while editing qty (33.60)", pg.input_value("#f-fee") == "33.60", pg.input_value("#f-fee"))
    pg.click("#addTradeBtn")
    tr = stored("trades")[0]
    check("I saved fee 33.60 and still feeAuto", abs(tr["fee"] - 33.60) < 0.005 and tr["feeAuto"] is True, tr)
    # พิมพ์ค่าเอง -> ไม่ใช่ auto อีกต่อไป และเปลี่ยนจำนวนต่อไม่คิดใหม่ทับ
    pg.click("[data-edit]"); pg.fill("#f-fee", "50"); pg.fill("#f-qty", "3000")
    check("I manual fee not overwritten by qty change", pg.input_value("#f-fee") == "50", pg.input_value("#f-fee"))
    pg.click("#addTradeBtn")
    tr = stored("trades")[0]
    check("I manual fee overrides (feeAuto false)", tr["fee"] == 50 and tr["feeAuto"] is False, tr)
    # ปิด auto แล้วแก้รายการที่เคยเป็น auto -> เห็นค่าเดิม และเปลี่ยนจำนวนไม่คิดใหม่
    pg.click("[data-edit]"); pg.fill("#f-fee", ""); pg.click("#addTradeBtn")   # เว้นว่าง+เปิด auto → คิดใหม่ (qty 3000) เป็น auto อีกครั้ง
    stored_fee = stored("trades")[0]["fee"]
    pg.uncheck("#s-auto")
    pg.click("[data-edit]")
    check("I auto disabled later: edit shows the stored fee", abs(float(pg.input_value("#f-fee")) - stored_fee) < 0.005, (pg.input_value("#f-fee"), stored_fee))
    pg.fill("#f-qty", "100")
    check("I auto disabled: qty change does not touch fee", abs(float(pg.input_value("#f-fee")) - stored_fee) < 0.005, pg.input_value("#f-fee"))
    pg.click("#cancelEditBtn")

    # ---- J) sticky เฉพาะคอลัมน์ปุ่ม ไม่ใช่แถวโน้ต
    pg.evaluate("localStorage.clear()"); pg.reload()
    setls("trades", [{"id": "j1", "date": "2026-01-01", "symbol": "JJJ", "side": "buy", "qty": 1, "price": 1, "fee": 0, "tag": "X", "note": "ยาวมาก " * 30}])
    pg.reload()
    pos_action = pg.evaluate("getComputedStyle(document.querySelector('#tradeBody tr:not(.note-row) td:last-child')).position")
    pos_note = pg.evaluate("getComputedStyle(document.querySelector('#tradeBody tr.note-row td')).position")
    check("J action column sticky, note row not", pos_action == "sticky" and pos_note == "static", (pos_action, pos_note))

    # ---- L) นำเข้าไฟล์เสีย: ห้ามเขียนทับข้อมูลเดิม / ไม่ครึ่งๆ กลางๆ
    pg.evaluate("localStorage.clear()"); pg.reload()
    setls("trades", [{"id": "keep1", "date": "2026-01-01", "symbol": "KEEP", "side": "buy", "qty": 5, "price": 5, "fee": 0}])
    pg.reload()
    allbad = ROOT / "allbad.json"
    allbad.write_text(json.dumps({"trades": [{"date": "x", "symbol": "A", "qty": 1, "price": 1}, {"date": "y", "symbol": "B", "qty": 1, "price": 1}]}), encoding="utf-8")
    msgs.clear()
    pg.set_input_files("#importFile", str(allbad)); pg.wait_for_timeout(300)
    check("L all-invalid file: error shown, no confirm to replace", any("ไม่พบรายการซื้อขายที่ถูกต้อง" in m for m in msgs) and not any("แทนที่ข้อมูลปัจจุบัน" in m for m in msgs), msgs)
    check("L all-invalid file: existing data untouched", [t["symbol"] for t in stored("trades")] == ["KEEP"])

    badmood = ROOT / "badmood.json"
    badmood.write_text(json.dumps({"trades": [{"id": "n1", "date": "2026-03-01", "symbol": "NEW", "side": "buy", "qty": 1, "price": 1}], "moods": [None, 5, {"id": "m1", "mood": "4", "note": "ok"}]}), encoding="utf-8")
    pg.set_input_files("#importFile", str(badmood)); pg.wait_for_timeout(300)
    check("L null mood entries ignored, import completes consistently",
          [t["symbol"] for t in stored("trades")] == ["NEW"] and len(stored("moods")) == 1 and "NEW" in txt("#tradeBody"), (stored("trades"), stored("moods")))

    dup = ROOT / "dup.json"
    dup.write_text(json.dumps({"trades": [
        {"id": "same", "date": "2026-03-05", "symbol": "DUP", "side": "buy", "qty": 10, "price": 1},
        {"id": "same", "date": "2026-03-01", "symbol": "DUP", "side": "buy", "qty": 20, "price": 1},
        {"id": "o3", "date": "2026-03-01", "symbol": "DUP", "side": "buy", "qty": 30, "price": 1}]}), encoding="utf-8")
    pg.set_input_files("#importFile", str(dup)); pg.wait_for_timeout(300)
    t = stored("trades")
    check("L duplicate ids made unique", len({x["id"] for x in t}) == 3, [x["id"] for x in t])
    check("L imported trades sorted by date, same-day keeps file order", [x["qty"] for x in t] == [20, 30, 10], [x["qty"] for x in t])

    # ---- M) ขาย→ซื้อกลับ→ขายเกิน (พิมพ์ผิด): ขายครั้งแรกต้องไม่ถูกกระทบ
    setls("trades", [
        {"id": "m1", "date": "2026-01-01", "symbol": "MMM", "side": "buy",  "qty": 100, "price": 10, "fee": 0},
        {"id": "m2", "date": "2026-01-05", "symbol": "MMM", "side": "sell", "qty": 100, "price": 12, "fee": 0},
        {"id": "m3", "date": "2026-01-05", "symbol": "MMM", "side": "buy",  "qty": 100, "price": 20, "fee": 0},
        {"id": "m4", "date": "2026-01-05", "symbol": "MMM", "side": "sell", "qty": 150, "price": 21, "fee": 0},
    ])
    pg.reload()
    rows = pg.evaluate("[...document.querySelectorAll('#tradeBody tr:not(.note-row)')].map(r=>[...r.children].map(c=>c.innerText.trim()))")
    sell12 = [r for r in rows if r[2] == "ขาย" and r[4].startswith("฿12")][0]
    sell21 = [r for r in rows if r[2] == "ขาย" and r[4].startswith("฿21")][0]
    check("M first sell keeps pnl +200 (cost = old 10 lot)", "200.00" in sell12[7] and "⚠" not in sell12[7], sell12)
    check("M the oversold sell (not the first) carries the warning", "⚠" in sell21[7], sell21)
    check("M shortfall warning shown", pg.is_visible("#warnBox"))

    # ---- N) id จากไฟล์เก่า/แก้มือไม่เรียงตามเวลา: ลำดับต้องมาจากตำแหน่งในไฟล์ ไม่ใช่ id
    setls("trades", [
        {"id": "m1", "date": "2026-01-01", "symbol": "NNN", "side": "buy",  "qty": 100, "price": 50, "fee": 0},
        {"id": "z9", "date": "2026-01-05", "symbol": "NNN", "side": "sell", "qty": 100, "price": 60, "fee": 0},
        {"id": "a1", "date": "2026-01-05", "symbol": "NNN", "side": "buy",  "qty": 100, "price": 70, "fee": 0},
    ])
    pg.reload()
    pg.click("#methodToggle button[data-m=AVG]")
    check("N AVG order by array position (pnl +1,000 even though id 'a1' < 'z9')", "1,000.00" in txt("#statRealized"), txt("#statRealized"))

    # ---- O) แท็กสะกดต่างตัวพิมพ์ใช้ตัวสะกดเดิม + 'ไม่ระบุ' ไม่ชนกับรายการไม่มีแท็ก
    pg.evaluate("localStorage.clear()"); pg.reload()
    setls("trades", [{"id": "o1", "date": "2026-01-01", "symbol": "OOO", "side": "buy", "qty": 1000, "price": 10, "fee": 0, "tag": "Breakout"}])
    pg.reload()
    pg.fill("#f-symbol", "ooo"); pg.fill("#f-qty", "10"); pg.fill("#f-price", "11"); pg.fill("#f-tag", "breakout"); pg.select_option("#f-side", "sell"); pg.click("#addTradeBtn")
    check("O typed 'breakout' stored as existing spelling 'Breakout'", [t["tag"] for t in stored("trades")] == ["Breakout", "Breakout"], stored("trades"))
    pg.fill("#f-symbol", "ooo"); pg.fill("#f-qty", "10"); pg.fill("#f-price", "12"); pg.fill("#f-tag", "ไม่ระบุ"); pg.select_option("#f-side", "sell"); pg.click("#addTradeBtn")
    pg.fill("#f-symbol", "ooo"); pg.fill("#f-qty", "10"); pg.fill("#f-price", "13"); pg.fill("#f-tag", ""); pg.select_option("#f-side", "sell"); pg.click("#addTradeBtn")
    # แท็กว่างของรายการขายสืบจากไม้ซื้อ (Breakout) จึงไม่ว่าง → ใส่ไม้ซื้อไม่มีแท็กแยกต่างหากเพื่อทดสอบ
    setls("trades", [
        {"id": "p1", "date": "2026-01-01", "symbol": "PPP", "side": "buy", "qty": 100, "price": 10, "fee": 0},
        {"id": "p2", "date": "2026-01-02", "symbol": "PPP", "side": "sell", "qty": 10, "price": 11, "fee": 0},
        {"id": "p3", "date": "2026-01-03", "symbol": "PPP", "side": "sell", "qty": 10, "price": 12, "fee": 0, "tag": "ไม่ระบุ"},
    ])
    pg.reload(); pg.select_option("#groupMode", "tag")
    rows = pg.evaluate("[...document.querySelectorAll('#groupBody tr')].map(r=>r.children[0].innerText.trim())")
    check("O untagged shows as '(ไม่มีแท็ก)' and user tag 'ไม่ระบุ' is its own row", "(ไม่มีแท็ก)" in rows and "ไม่ระบุ" in rows, rows)

    check("no console/page errors", not errors, str(errors))
    b.close()

print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)

