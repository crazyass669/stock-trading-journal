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

def add_trade(pg, date, sym, side, qty, price, fee="0", tag="", note=""):
    pg.fill("#f-date", date); pg.fill("#f-symbol", sym); pg.select_option("#f-side", side)
    pg.fill("#f-qty", str(qty)); pg.fill("#f-price", str(price)); pg.fill("#f-fee", fee)
    pg.fill("#f-tag", tag); pg.fill("#f-note", note)
    pg.click("#addTradeBtn")

with sync_playwright() as p:
    b = p.chromium.launch()
    ctx = b.new_context(accept_downloads=True, viewport={"width": 1280, "height": 900})
    errors = []
    msgs = []
    def mk(dialog_handler=None):
        pg = ctx.new_page()
        pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "fonts.g" not in m.text and "ERR_" not in m.text and "storage" not in m.text.lower() else None)
        pg.on("dialog", dialog_handler or (lambda d: (msgs.append(d.message), d.accept())))
        return pg
    p1 = mk(); p1.goto(URL); p1.evaluate("localStorage.clear()"); p1.reload()
    stored = lambda pg, k: json.loads(pg.evaluate(f"localStorage.getItem('trading-journal:{k}')"))
    txt = lambda pg, sel: pg.inner_text(sel).strip()

    # ================= A) หลายแท็บ =================
    p2 = mk(); p2.goto(URL)
    add_trade(p1, "2026-01-05", "aaa", "buy", 10, 10)
    p2.wait_for_function("document.getElementById('tradeBody').innerText.includes('AAA')", timeout=5000)
    check("A tab2 shows trade added in tab1 (storage event)", "AAA" in txt(p2, "#tradeBody"))
    add_trade(p2, "2026-01-06", "bbb", "buy", 20, 5)
    syms = [t["symbol"] for t in stored(p1, "trades")]
    check("A tab2's add does not erase tab1's trade (both kept)", syms == ["AAA", "BBB"], syms)
    p1.wait_for_function("document.getElementById('tradeBody').innerText.includes('BBB')", timeout=5000)
    check("A tab1 sees tab2's trade", "BBB" in txt(p1, "#tradeBody"))

    # เหตุการณ์ storage ไม่มาถึง (เขียนจากเอกสารเดียวกันไม่ยิงเหตุการณ์ในตัวเอง) → ปุ่มต้องซิงก์ก่อนเขียนเอง
    p1.evaluate("""(()=>{ const k='trading-journal:trades'; const a=JSON.parse(localStorage.getItem(k));
      a.push({id:'zzz1',date:'2026-01-07',symbol:'ZZZ',side:'buy',qty:1,price:1,fee:0}); localStorage.setItem(k, JSON.stringify(a)); })()""")
    add_trade(p1, "2026-01-08", "ccc", "buy", 1, 1)
    syms = [t["symbol"] for t in stored(p1, "trades")]
    check("A add syncs first: externally-written ZZZ survives tab1's save", syms == ["AAA", "BBB", "ZZZ", "CCC"], syms)

    # รายการที่กำลังแก้ถูกลบจากแท็บอื่น
    p1.click("#tradeBody tr:has-text('CCC') [data-edit]")
    check("A tab1 in edit mode", "แก้ไข" in txt(p1, "#addTradeBtn"))
    p2.wait_for_function("document.getElementById('tradeBody').innerText.includes('CCC')", timeout=5000)
    p2.click("#tradeBody tr:has-text('CCC') [data-del]"); p2.wait_for_timeout(300)
    p1.wait_for_function("!document.getElementById('tradeBody').innerText.includes('CCC')", timeout=5000)
    check("A tab1 leaves edit mode when edited trade deleted elsewhere", txt(p1, "#addTradeBtn") == "+ บันทึก" and not p1.is_visible("#cancelEditBtn"), txt(p1, "#addTradeBtn"))
    check("A tab1 keeps form values (can re-save as new)", p1.input_value("#f-symbol") == "CCC")
    msgs.clear()
    p1.click("#addTradeBtn")
    syms = [t["symbol"] for t in stored(p1, "trades")]
    check("A re-save after remote delete adds as new (no loss)", syms.count("CCC") == 1, syms)

    # ปันผล/อารมณ์/ตั้งค่า ข้ามแท็บ
    p2.fill("#d-symbol", "aaa"); p2.fill("#d-gross", "100"); p2.click("#addDivBtn")
    p1.wait_for_function("document.getElementById('divBody').innerText.includes('AAA')", timeout=5000)
    check("A dividend from tab2 appears in tab1", "AAA" in txt(p1, "#divBody"))
    p1.click("#moodPicker [data-v='4']"); p1.fill("#moodNote", "จากแท็บ 1"); p1.click("#addMoodBtn")
    p2.wait_for_function("document.getElementById('moodEntries').innerText.includes('จากแท็บ 1')", timeout=5000)
    check("A mood from tab1 appears in tab2", True)

    # ================= B) นำเข้าแบบทั้งหมดหรือไม่เลย =================
    p1.close(); p2.close()
    pg = mk(); pg.goto(URL); pg.evaluate("localStorage.clear()"); pg.reload()
    pg.evaluate("""localStorage.setItem('trading-journal:trades', JSON.stringify([{id:'old1',date:'2026-01-01',symbol:'OLD',side:'buy',qty:5,price:5,fee:0}]));
                   localStorage.setItem('trading-journal:meta', JSON.stringify({lastBackup:null,changes:3}));""")
    pg.reload()
    good = ROOT / "imp_good.json"
    good.write_text(json.dumps({"exportedAt": "2026-01-01T00:00:00.000Z",
        "trades": [{"id": "n1", "date": "2026-03-01", "symbol": "NEW", "side": "buy", "qty": 1, "price": 1}],
        "dividends": [{"id": "d1", "date": "2026-03-02", "symbol": "NEW", "gross": 10, "tax": 1}],
        "moods": [{"id": "m1", "mood": "4", "note": "x"}]}), encoding="utf-8")
    pg.evaluate("""(()=>{ const orig = Storage.prototype.setItem; window.__origSet = orig; window.__failKey = 'trading-journal:dividends';
      Storage.prototype.setItem = function(k,v){ if(window.__failKey && k === window.__failKey) throw new DOMException('quota','QuotaExceededError'); return orig.call(this,k,v); }; })()""")
    msgs.clear()
    pg.set_input_files("#importFile", str(good)); pg.wait_for_timeout(400)
    check("B quota failure mid-import: failure message, no success alert",
          any("ไม่สามารถนำเข้า" in m and "ไม่ได้เปลี่ยนแปลงข้อมูลเดิม" in m for m in msgs) and not any("นำเข้าข้อมูลสำเร็จ" in m for m in msgs), msgs)
    check("B storage rolled back to old trades", [t["symbol"] for t in stored(pg, "trades")] == ["OLD"], stored(pg, "trades"))
    check("B meta/moods/dividends untouched", stored(pg, "meta")["changes"] == 3 and pg.evaluate("localStorage.getItem('trading-journal:moods')") is None
          and pg.evaluate("localStorage.getItem('trading-journal:dividends')") is None)
    check("B screen still shows old data", "OLD" in txt(pg, "#tradeBody") and "NEW" not in txt(pg, "#tradeBody"))
    pg.evaluate("window.__failKey = null")
    msgs.clear()
    pg.set_input_files("#importFile", str(good)); pg.wait_for_timeout(400)
    check("B same file imports fine once storage works", [t["symbol"] for t in stored(pg, "trades")] == ["NEW"] and len(stored(pg, "dividends")) == 1 and stored(pg, "meta")["changes"] == 0)

    # ================= C) นำเข้า: ตรวจเข้ม =================
    bad = ROOT / "imp_strict.json"
    bad.write_text('{"trades":[' + ",".join([
        '{"id":"s1","date":"2026-01-01","symbol":"OK","side":"buy","qty":10,"price":0,"fee":0}',          # ราคา 0 ผ่าน
        '{"id":"s2","date":"2026-01-02","symbol":"UP","side":"SELL","qty":1,"price":5}',                    # SELL ตัวพิมพ์ใหญ่ ผ่านและเป็น sell
        '{"id":"s3","date":"2026-01-03","symbol":"NOPRICE","side":"buy","qty":1}',                          # ไม่มีราคา
        '{"id":"s4","date":"2026-01-03","symbol":"NULLP","side":"buy","qty":1,"price":null}',
        '{"id":"s5","date":"2026-01-03","symbol":"COMMA","side":"buy","qty":1,"price":"12,50"}',
        '{"id":"s6","date":"2026-01-03","symbol":"THAI","side":"ขาย","qty":1,"price":5}',
        '{"id":"s7","date":"2026-01-03","symbol":"INF","side":"buy","qty":1e999,"price":5}',
        '{"id":"s8","date":"2026-01-03","symbol":"FEE","side":"buy","qty":1,"price":5,"fee":"1,234.50"}',
        '{"id":"s9","date":"2026-01-04","symbol":"STR","side":"buy","qty":"5","price":"2.5"}'                # สตริงตัวเลขล้วน ผ่าน
    ]) + ']}', encoding="utf-8")
    msgs.clear()
    pg.set_input_files("#importFile", str(bad)); pg.wait_for_timeout(400)
    t = stored(pg, "trades")
    check("C strict import keeps only valid rows (OK, UP, STR)", sorted(x["symbol"] for x in t) == ["OK", "STR", "UP"], [x["symbol"] for x in t])
    up = [x for x in t if x["symbol"] == "UP"][0]
    check("C 'SELL' normalised to sell; price 0 kept; numeric strings parsed", up["side"] == "sell" and [x for x in t if x["symbol"] == "OK"][0]["price"] == 0
          and [x for x in t if x["symbol"] == "STR"][0]["qty"] == 5)
    check("C skipped count 6 reported", any("ข้าม 6" in m for m in msgs), msgs)

    keep = [x["symbol"] for x in t]
    allbad_div = ROOT / "imp_baddiv.json"
    allbad_div.write_text(json.dumps({"trades": [{"id": "g", "date": "2026-02-01", "symbol": "GOOD", "side": "buy", "qty": 1, "price": 1}],
                                      "dividends": [{"date": "01/02/2026", "symbol": "X", "gross": 5}]}), encoding="utf-8")
    msgs.clear()
    pg.set_input_files("#importFile", str(allbad_div)); pg.wait_for_timeout(400)
    check("C all-invalid dividends reject the import; existing data untouched",
          any("ไม่พบปันผลที่ถูกต้อง" in m for m in msgs) and [x["symbol"] for x in stored(pg, "trades")] == keep, msgs)

    # ================= D) แก้วันที่ → เป็นรายการล่าสุดของวันใหม่ =================
    pg.evaluate("localStorage.clear()"); pg.reload()
    pg.click("#methodToggle button[data-m=AVG]")
    add_trade(pg, "2026-01-01", "ddd", "buy", 100, 10)
    add_trade(pg, "2026-01-01", "ddd", "sell", 100, 25)      # วันที่ผิด (ควรเป็น 01-02)
    add_trade(pg, "2026-01-02", "ddd", "buy", 100, 20)
    pg.click("#tradeBody tr:has-text('ขาย') [data-edit]")
    pg.fill("#f-date", "2026-01-02"); pg.click("#addTradeBtn")
    order = [(t["date"], t["side"]) for t in stored(pg, "trades")]
    check("D edited-date sell moves behind the day's existing buy", order == [("2026-01-01", "buy"), ("2026-01-02", "buy"), ("2026-01-02", "sell")], order)
    check("D AVG pnl +1,000 (blended cost 15)", "1,000.00" in txt(pg, "#statRealized"), txt(pg, "#statRealized"))

    # ================= E) ราคา 0 + F) ปัดเศษกำไร =================
    pg.evaluate("localStorage.clear()"); pg.reload(); msgs.clear()
    add_trade(pg, "2026-02-01", "bonus", "buy", 50, 0)
    check("E price 0 accepted in the form", len(stored(pg, "trades")) == 1 and stored(pg, "trades")[0]["price"] == 0 and not msgs, msgs)
    pg.evaluate("localStorage.clear()"); pg.reload()
    add_trade(pg, "2026-03-01", "ffff", "buy", 3, 10.07, fee="0.07")
    add_trade(pg, "2026-03-02", "ffff", "sell", 3, 10.45, fee="1.07")
    check("F exact break-even is not counted as a loss/win (0 / 0)", txt(pg, "#stWL").replace(" ", "") == "0/0", txt(pg, "#stWL"))
    check("F realized shows ฿0.00", txt(pg, "#statRealized") == "฿0.00", txt(pg, "#statRealized"))

    # ================= G) Unrealized ตามตัวกรอง =================
    pg.evaluate("localStorage.clear()"); pg.reload()
    pg.evaluate("""localStorage.setItem('trading-journal:trades', JSON.stringify([
      {id:'u1',date:'2026-01-01',symbol:'PTT',side:'buy',qty:100,price:10,fee:0},
      {id:'u2',date:'2026-01-01',symbol:'AOT',side:'buy',qty:100,price:50,fee:0}]));
      localStorage.setItem('trading-journal:marketPrices', JSON.stringify({PTT:12,AOT:40}));""")
    pg.reload()
    check("G all symbols: -800", "800.00" in txt(pg, "#statUnrealized") and txt(pg, "#statUnrealized").startswith("-"), txt(pg, "#statUnrealized"))
    pg.select_option("#filterSymbol", "PTT")
    check("G filtered to PTT: +200", txt(pg, "#statUnrealized") == "฿200.00", txt(pg, "#statUnrealized"))
    pg.select_option("#filterSymbol", "")
    pg.evaluate("""localStorage.setItem('trading-journal:marketPrices', JSON.stringify({PTT:12}))"""); pg.reload()
    check("G partial pricing is flagged (1 of 2)", pg.is_visible("#unrealNote") and "1 จาก 2" in txt(pg, "#unrealNote"), txt(pg, "#unrealNote"))

    # ================= H) ข้อมูลในที่เก็บเสีย =================
    pg.evaluate("localStorage.clear()"); pg.reload()
    pg.evaluate("localStorage.setItem('trading-journal:trades', '{bad json')"); pg.reload()
    check("H unreadable JSON: page loads, warning stamp shown", "ไม่ได้" in txt(pg, "#statusStamp") and "⚠" in txt(pg, "#statusStamp"), txt(pg, "#statusStamp"))
    qcopies = lambda pg: pg.evaluate("Object.keys(localStorage).filter(k=>k.startsWith('trading-journal:trades.unreadable')).map(k=>localStorage.getItem(k))")
    check("H raw copy quarantined", qcopies(pg) == ["{bad json"], qcopies(pg))
    check("H stamp names the copy key", "trades.unreadable." in txt(pg, "#statusStamp"), txt(pg, "#statusStamp"))
    pg.reload()
    check("H reloading the same corruption does not duplicate the copy", qcopies(pg) == ["{bad json"], qcopies(pg))
    add_trade(pg, "2026-01-01", "okk", "buy", 1, 1)
    check("H adding after corruption keeps the quarantined copy", qcopies(pg) == ["{bad json"] and len(stored(pg, "trades")) == 1)
    pg.evaluate("localStorage.setItem('trading-journal:trades', '{another bad one')"); pg.reload()
    check("H a different corruption later is stored as a separate copy (nothing overwritten)", sorted(qcopies(pg)) == sorted(["{bad json", "{another bad one"]), qcopies(pg))
    pg.evaluate("localStorage.clear()"); pg.reload()
    pg.evaluate("""localStorage.setItem('trading-journal:trades', JSON.stringify([null, 5, {id:'q1',date:'2026-01-01',symbol:'GOOD',side:'buy',qty:1,price:1,fee:0}, {id:'q2',date:'bad',symbol:'X',side:'buy',qty:1,price:1}]));
                   localStorage.setItem('trading-journal:moods', JSON.stringify([null, {id:'m',mood:'4',note:'ok'}]));
                   localStorage.setItem('trading-journal:dividends', JSON.stringify({a:1}));""")
    pg.reload()
    check("H bad rows skipped, good row shown, no crash", "GOOD" in txt(pg, "#tradeBody") and "⚠" in txt(pg, "#statusStamp"), txt(pg, "#statusStamp"))
    check("H non-array dividends handled", "ยังไม่มีบันทึกปันผล" in txt(pg, "#divBody"))

    # ================= K) CSV order = ลำดับที่บันทึก =================
    pg.evaluate("localStorage.clear()"); pg.reload()
    pg.evaluate("""localStorage.setItem('trading-journal:trades', JSON.stringify([
      {id:'m1',date:'2026-01-01',symbol:'KKK',side:'buy', qty:100,price:50,fee:0},
      {id:'z9',date:'2026-01-05',symbol:'KKK',side:'sell',qty:100,price:60,fee:0},
      {id:'a1',date:'2026-01-05',symbol:'KKK',side:'buy', qty:100,price:70,fee:0}]))""")
    pg.reload()
    with pg.expect_download() as dl:
        pg.click("#csvBtn")
    lines = open(dl.value.path(), encoding="utf-8-sig", newline="").read().strip().split("\r\n")[1:]   # newline="" ไม่งั้น Python แปลง CRLF เป็น LF ก่อนแยก
    check("K CSV rows in recorded order (sell before the same-day re-buy)", [l.split(",")[1] for l in lines] == ["ซื้อ", "ขาย", "ซื้อ"], lines)

    # ================= O) วันที่ของอารมณ์เป็นปฏิทินสากล =================
    pg.evaluate("localStorage.clear()"); pg.reload()
    pg.evaluate("localStorage.setItem('trading-journal:moods', JSON.stringify([{id:'m1',date:'2026-10-13T10:00:00.000Z',mood:'4',note:'x'}]))"); pg.reload()
    mt = txt(pg, "#moodEntries")
    check("O mood date shows 2026 not พ.ศ. 2569", "2026" in mt and "2569" not in mt, mt)

    # ================= M) วันที่เริ่มต้นเลื่อนเมื่อกลับมาหลังข้ามวัน =================
    try:
        pg2 = mk()
        pg2.clock.install(time="2026-10-13T10:00:00")
        pg2.goto(URL); pg2.evaluate("localStorage.clear()"); pg2.reload()
        d0 = pg2.input_value("#f-date")
        pg2.clock.set_system_time("2026-10-15T09:00:00")
        pg2.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        check("M default dates roll forward after resume", d0 == "2026-10-13" and pg2.input_value("#f-date") == "2026-10-15" and pg2.input_value("#d-date") == "2026-10-15",
              (d0, pg2.input_value("#f-date"), pg2.input_value("#d-date")))
        pg2.fill("#f-date", "2026-10-01")
        pg2.clock.set_system_time("2026-10-16T09:00:00")
        pg2.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
        check("M date typed by the user is not overwritten", pg2.input_value("#f-date") == "2026-10-01", pg2.input_value("#f-date"))
    except AttributeError:
        print("SKIP M (playwright clock API unavailable)")

    # ================= R2-1) กล่องยืนยันบล็อกซิงก์: แท็บอื่นเขียนระหว่างรอ ต้องไม่ถูกทับ =================
    pg.close()
    remote = {"on": False}
    def a_dialog(d):
        msgs.append(d.message)
        if remote["on"]:
            # ระหว่างที่กล่องยืนยันของแท็บ a เปิดอยู่ แท็บ bt บันทึกรายการใหม่ลงที่เก็บ
            bt.evaluate("""(()=>{ const k='trading-journal:trades'; const arr=JSON.parse(localStorage.getItem(k));
              arr.push({id:'remote1',date:'2026-01-02',symbol:'BBB',side:'buy',qty:1,price:1,fee:0}); localStorage.setItem(k, JSON.stringify(arr)); })()""")
        d.accept()
    a = mk(a_dialog); a.goto(URL); a.evaluate("localStorage.clear()"); a.reload()
    bt = mk(); bt.goto(URL)
    add_trade(a, "2026-01-01", "xxx", "buy", 1, 1)
    bt.wait_for_function("document.getElementById('tradeBody').innerText.includes('XXX')", timeout=5000)
    remote["on"] = True
    a.click("#tradeBody tr:has-text('XXX') [data-del]"); a.wait_for_timeout(400)
    remote["on"] = False
    syms = [t["symbol"] for t in stored(a, "trades")]
    check("R2-1 delete: remote write made during the confirm dialog survives", syms == ["BBB"], syms)

    # ================= R2-2) ปีของวันที่ 5 หลักต้องถูกปฏิเสธ (ไม่งั้นรายการหายตอนโหลด) =================
    a.reload(); msgs.clear()
    a.evaluate("document.getElementById('f-date').value='20261-10-13'")
    a.fill("#f-symbol", "yyy"); a.fill("#f-qty", "1"); a.fill("#f-price", "1"); a.click("#addTradeBtn")
    check("R2-2 trade with 5-digit year rejected", any("วันที่ไม่ถูกต้อง" in m for m in msgs) and "YYY" not in json.dumps(stored(a, "trades")), msgs)
    msgs.clear()
    a.evaluate("document.getElementById('d-date').value='20261-10-13'")
    a.fill("#d-symbol", "yyy"); a.fill("#d-gross", "10"); a.click("#addDivBtn")
    check("R2-2 dividend with 5-digit year rejected", any("วันที่ไม่ถูกต้อง" in m for m in msgs) and a.evaluate("localStorage.getItem('trading-journal:dividends')") is None, msgs)

    # ================= R2-3) ตั้งค่า: เขียนเฉพาะช่องที่แก้ ไม่ย้อนค่าที่อีกแท็บแก้ =================
    a.reload()
    a.evaluate("document.getElementById('settingsPanel').open = true")
    a.evaluate("localStorage.setItem('trading-journal:settings', JSON.stringify({autoFee:true,commRate:0.157,minFee:0,vat:10,divTax:10}))")   # เหมือนอีกแท็บแก้ (แท็บนี้ไม่ได้รับเหตุการณ์)
    a.fill("#s-min", "25"); a.dispatch_event("#s-min", "change")
    s = stored(a, "settings")
    check("R2-3 stale form does not revert the other tab's autoFee/vat", s["autoFee"] is True and s["vat"] == 10 and s["minFee"] == 25, s)

    # ================= R2-4) feeAuto: ค่าที่พิมพ์เองแต่บังเอิญเท่าสูตร ต้องไม่ถูกคิดใหม่ตอนแก้ =================
    a.evaluate("localStorage.clear()"); a.reload()
    a.evaluate("document.getElementById('settingsPanel').open = true")
    a.check("#s-auto"); a.fill("#s-rate", "0.157"); a.dispatch_event("#s-rate", "change")
    add_trade(a, "2026-01-01", "mmm", "buy", 100, 10, fee="1.68")        # พิมพ์เองให้เท่าสูตร (1000×0.157%×1.07 = 1.68)
    tr = stored(a, "trades")[0]
    check("R2-4 manual fee stored with feeAuto=false", tr["fee"] == 1.68 and tr["feeAuto"] is False, tr)
    a.click("[data-edit]"); a.fill("#f-qty", "200")
    check("R2-4 manual fee equal to formula is NOT recalculated on qty edit", a.input_value("#f-fee") == "1.68", a.input_value("#f-fee"))
    a.click("#cancelEditBtn")
    # รายการเก่าที่ไม่มีธง และตรงสูตร → ถือเป็นอัตโนมัติ
    a.evaluate("""localStorage.setItem('trading-journal:trades', JSON.stringify([{id:'old',date:'2026-01-01',symbol:'OLD',side:'buy',qty:100,price:10,fee:1.68}]))"""); a.reload()
    a.click("[data-edit]"); a.fill("#f-qty", "200")
    check("R2-4 legacy flag-less trade matching the formula is recalculated (3.36)", a.input_value("#f-fee") == "3.36", a.input_value("#f-fee"))
    a.click("#cancelEditBtn")

    # ================= R2-5) ชนะ/แพ้: เศษจิ๋วไม่นับ แต่ผลรวมต้องไม่คลาดเคลื่อน =================
    sells = [{"id": f"s{i:03d}", "date": "2026-02-01", "symbol": "TINY", "side": "sell", "qty": 1, "price": 10.004, "fee": 0} for i in range(100)]
    a.evaluate("localStorage.clear()"); a.reload()
    a.evaluate("(t)=>localStorage.setItem('trading-journal:trades', JSON.stringify(t))", [{"id": "b0", "date": "2026-01-01", "symbol": "TINY", "side": "buy", "qty": 1000, "price": 10, "fee": 0}] + sells)
    a.reload()
    check("R2-5 100 sells at +0.004 each: total realized ฿0.40 (not rounded away)", txt(a, "#statRealized") == "฿0.40", txt(a, "#statRealized"))
    check("R2-5 sub-half-satang sells counted as neither win nor loss", txt(a, "#stWL").replace(" ", "") == "0/0", txt(a, "#stWL"))

    # ================= R2-6) id ที่ซ่อมต้องคงที่ข้ามการโหลด/ซิงก์ =================
    a.evaluate("localStorage.clear()"); a.reload()
    a.evaluate("""localStorage.setItem('trading-journal:trades', JSON.stringify([
      {date:'2026-01-01',symbol:'NOID',side:'buy',qty:1,price:1,fee:0},
      {id:'dup',date:'2026-01-02',symbol:'D1',side:'buy',qty:1,price:1,fee:0},
      {id:'dup',date:'2026-01-03',symbol:'D2',side:'buy',qty:1,price:1,fee:0}]))""")
    a.reload()
    ids = lambda: a.evaluate("[...document.querySelectorAll('#tradeBody [data-edit]')].map(b=>b.dataset.edit).sort()")
    first = ids(); a.reload(); second = ids()
    check("R2-6 repaired ids are unique and identical across reloads", len(set(first)) == 3 and first == second, (first, second))
    a.click("#tradeBody tr:has-text('NOID') [data-edit]")
    a.evaluate("""(()=>{ const k='trading-journal:trades'; const arr=JSON.parse(localStorage.getItem(k)); arr.push({id:'other1',date:'2026-01-04',symbol:'OTH',side:'buy',qty:1,price:1,fee:0}); localStorage.setItem(k, JSON.stringify(arr)); window.dispatchEvent(new Event('focus')); })()""")
    check("R2-6 sync does not drop the trade being edited (still in edit mode)", "แก้ไข" in txt(a, "#addTradeBtn") and "OTH" in txt(a, "#tradeBody"), txt(a, "#addTradeBtn"))
    a.click("#cancelEditBtn")

    check("no console/page errors", not errors, str(errors))
    b.close()

print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
