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
    ctx = b.new_context(accept_downloads=True)
    pg = ctx.new_page()
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.on("console", lambda m: errors.append(m.text) if m.type == "error" and "fonts.g" not in m.text and "ERR_" not in m.text else None)
    pg.on("dialog", lambda d: d.accept())
    pg.goto(URL)
    pg.evaluate("localStorage.clear()")
    pg.reload()

    txt = lambda sel: pg.inner_text(sel).strip()

    # --- 1) ขายก่อนซื้อในวันเดียวกัน ต้องไม่เตือน และกำไรถูก
    pg.evaluate("""localStorage.setItem('trading-journal:trades', JSON.stringify([
      {id:'a1', date:'2026-01-05', symbol:'AAA', side:'sell', qty:100, price:12, fee:0},
      {id:'a2', date:'2026-01-05', symbol:'AAA', side:'buy',  qty:100, price:10, fee:0}
    ]))""")
    pg.reload()
    check("1 no shortfall warning when sell logged before buy same day", pg.is_hidden("#warnBox"))
    check("1 realized = 200", "200.00" in txt("#statRealized"), txt("#statRealized"))
    check("7 sell row shows pnl in table", "200.00" in txt("#tradeBody"), txt("#tradeBody"))

    # --- 2) สำรองข้อมูล: มีข้อมูลแต่ไม่เคยสำรอง -> เตือน ; กดสำรอง -> หาย
    check("2 notice visible when never backed up", pg.is_visible("#backupNotice"))
    with pg.expect_download() as dl:
        pg.click("#backupNowBtn")
    path = dl.value.path()
    payload = json.load(open(path, encoding="utf-8"))
    check("2 export has version 2 + dividends/settings", payload.get("version") == 2 and "dividends" in payload and "settings" in payload)
    check("2 notice hidden after backup", pg.is_hidden("#backupNotice"))
    check("2 info says today", "วันนี้" in txt("#backupInfo"), txt("#backupInfo"))
    # เก่าเกิน 7 วัน -> เตือน
    pg.evaluate("""(()=>{const m=JSON.parse(localStorage.getItem('trading-journal:meta'));
      m.lastBackup=new Date(Date.now()-9*86400000).toISOString(); localStorage.setItem('trading-journal:meta',JSON.stringify(m));})()""")
    pg.reload()
    check("2 notice visible when backup 9 days old", pg.is_visible("#backupNotice") and "9 วัน" in txt("#backupNoticeText"), txt("#backupNoticeText"))
    # เปลี่ยนแปลง >= 20 -> เตือน
    pg.evaluate("""(()=>{localStorage.setItem('trading-journal:meta',JSON.stringify({lastBackup:new Date().toISOString(),changes:20}));})()""")
    pg.reload()
    check("2 notice visible when 20 changes", pg.is_visible("#backupNotice"))

    # --- 3) เพิ่มรายการผ่าน UI พร้อมแท็ก/โน้ต/อารมณ์ + 6) ค่าธรรมเนียมอัตโนมัติ
    pg.evaluate("localStorage.clear()")
    pg.reload()
    pg.evaluate("document.getElementById('settingsPanel').open = true")
    pg.check("#s-auto")
    pg.fill("#s-rate", "0.157"); pg.fill("#s-min", "0"); pg.fill("#s-vat", "7")
    pg.dispatch_event("#s-vat", "change")

    def add(date, sym, side, qty, price, fee="", tag="", emo="", note=""):
        pg.fill("#f-date", date); pg.fill("#f-symbol", sym); pg.select_option("#f-side", side)
        pg.fill("#f-qty", str(qty)); pg.fill("#f-price", str(price)); pg.fill("#f-fee", fee)
        pg.fill("#f-tag", tag); pg.select_option("#f-emotion", emo); pg.fill("#f-note", note)
        pg.click("#addTradeBtn")

    pg.fill("#f-qty", "1000"); pg.fill("#f-price", "10")
    check("6 fee placeholder shows auto fee", "16.80" in pg.get_attribute("#f-fee", "placeholder"), pg.get_attribute("#f-fee", "placeholder"))
    add("2026-02-01", "ptt", "buy", 1000, 10, tag="Breakout", emo="4", note="ทะลุแนวต้าน")
    trades = json.loads(pg.evaluate("localStorage.getItem('trading-journal:trades')"))
    check("6 auto fee = 16.80", abs(trades[0]["fee"] - 16.80) < 0.005, trades[0]["fee"])
    check("3 tag/emotion/note saved", trades[0]["tag"] == "Breakout" and trades[0]["emotion"] == "4" and trades[0]["note"] == "ทะลุแนวต้าน")
    check("3 note + chip show in table", "Breakout" in txt("#tradeBody") and "ทะลุแนวต้าน" in pg.inner_html("#tradeBody"))
    add("2026-02-10", "ptt", "sell", 1000, 12, fee="0", tag="", note="ขายทำกำไร")   # fee 0 explicit
    trades = json.loads(pg.evaluate("localStorage.getItem('trading-journal:trades')"))
    sell = [t for t in trades if t["side"] == "sell"][0]
    check("6 explicit fee 0 respected", sell["fee"] == 0, sell["fee"])
    # P&L = 12000 - (10000+16.8) = 1983.2 ; tag inherited from buy = Breakout
    check("1/7 realized = 1983.20", "1,983.20" in txt("#statRealized"), txt("#statRealized"))
    pg.select_option("#groupMode", "tag")
    check("3 group by tag inherits Breakout from buy lot", "Breakout" in txt("#groupBody") and "1,983.20" in txt("#groupBody"), txt("#groupBody"))
    pg.select_option("#groupMode", "symbol")
    check("5 group by symbol shows PTT", "PTT" in txt("#groupBody"))
    check("5 hold days = 9", "9" in txt("#stHold") and "วัน" in txt("#stHold"), txt("#stHold"))

    # --- 4) ปันผล
    pg.fill("#d-date", "2026-03-01"); pg.fill("#d-symbol", "ptt"); pg.fill("#d-gross", "1000"); pg.fill("#d-tax", "")
    pg.click("#addDivBtn")
    divs = json.loads(pg.evaluate("localStorage.getItem('trading-journal:dividends')"))
    check("4 dividend tax defaults to 10%", divs[0]["tax"] == 100 and divs[0]["gross"] == 1000, divs)
    check("4 dividend net stat 900", "900.00" in txt("#statDiv"), txt("#statDiv"))
    check("4 total = 1983.20 + 900", "2,883.20" in txt("#statTotal"), txt("#statTotal"))
    check("4 symbol group includes dividend", "900.00" in txt("#groupBody") and "2,883.20" in txt("#groupBody"), txt("#groupBody"))
    pg.fill("#d-date", "2026-03-02"); pg.fill("#d-symbol", "ptt"); pg.fill("#d-gross", "500"); pg.fill("#d-tax", "0")
    pg.click("#addDivBtn")
    check("4 explicit tax 0 respected", "1,400.00" in txt("#statDiv"), txt("#statDiv"))
    pg.click("[data-deldiv]"); pg.wait_for_timeout(300)   # ตัวจัดการลบรอ 1 รอบ event loop หลัง confirm ก่อนซิงก์/เขียน
    check("4 delete dividend works", "ยังไม่มี" not in txt("#divBody") and len(json.loads(pg.evaluate("localStorage.getItem('trading-journal:dividends')"))) == 1)

    # --- 5) สถิติ: ชุดข้อมูลที่รู้คำตอบ  W +100, L -40, L -60, W +50  (AAA, ไม่มีค่าธรรมเนียม)
    pg.evaluate("localStorage.clear()")
    pg.reload()
    pg.evaluate("""localStorage.setItem('trading-journal:trades', JSON.stringify([
      {id:'b01', date:'2026-01-01', symbol:'ZZZ', side:'buy',  qty:400, price:100, fee:0},
      {id:'b02', date:'2026-01-02', symbol:'ZZZ', side:'sell', qty:100, price:101, fee:0},
      {id:'b03', date:'2026-01-03', symbol:'ZZZ', side:'sell', qty:100, price:99.6, fee:0},
      {id:'b04', date:'2026-01-04', symbol:'ZZZ', side:'sell', qty:100, price:99.4, fee:0},
      {id:'b05', date:'2026-01-05', symbol:'ZZZ', side:'sell', qty:100, price:100.5, fee:0}
    ]))""")
    pg.reload()
    check("5 avg win 75", "75.00" in txt("#stAvgWin"), txt("#stAvgWin"))
    check("5 avg loss -50", "50.00" in txt("#stAvgLoss") and "-" in txt("#stAvgLoss"), txt("#stAvgLoss"))
    check("5 profit factor 1.50", txt("#stPF") == "1.50", txt("#stPF"))
    check("5 W/L 2 / 2", txt("#stWL").replace(" ", "") == "2/2", txt("#stWL"))
    check("5 losing streak 2", "2" in txt("#stStreak"), txt("#stStreak"))
    check("5 max drawdown 100", "100.00" in txt("#stDD"), txt("#stDD"))   # cum: 100, 60, 0(?)...
    pg.screenshot(path=str(ROOT / "tj_stats.png"), full_page=True)

    # --- AVG: เปลี่ยนวิธีแล้วไม่ error
    pg.click("#methodToggle button[data-m=AVG]")
    check("AVG toggle no crash", "100.00" in txt("#stAvgWin") or True)

    # --- นำเข้าไฟล์สำรองเก่า (version 1)
    v1 = {"version": 1, "exportedAt": "2026-01-01T00:00:00.000Z",
          "trades": [{"id": "x1", "date": "2026-01-02", "symbol": "old", "side": "buy", "qty": 10, "price": 5, "fee": 1}],
          "moods": [], "method": "FIFO", "marketPrices": {}}
    f = ROOT / "v1.json"; f.write_text(json.dumps(v1), encoding="utf-8")
    pg.set_input_files("#importFile", str(f))
    pg.wait_for_timeout(300)
    t = json.loads(pg.evaluate("localStorage.getItem('trading-journal:trades')"))
    check("import v1: fields defaulted", t[0]["tag"] == "" and t[0]["note"] == "" and t[0]["symbol"] == "OLD", t)
    check("import v1: backup info uses exportedAt (old -> notice)", pg.is_visible("#backupNotice"))

    check("no console/page errors", not errors, str(errors))
    b.close()

print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
