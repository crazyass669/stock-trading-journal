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
    state = {"accept": True, "msgs": []}
    def on_dialog(d):
        state["msgs"].append(d.message)
        d.accept() if state["accept"] else d.dismiss()
    pg.on("dialog", on_dialog)
    pg.goto(URL); pg.evaluate("localStorage.clear()"); pg.reload()
    txt = lambda sel: pg.inner_text(sel).strip()
    stored = lambda k: json.loads(pg.evaluate(f"localStorage.getItem('trading-journal:{k}')"))

    # ---------- 3) layout: textarea กว้างพอบนจอใหญ่
    w = pg.evaluate("document.getElementById('moodNote').getBoundingClientRect().width")
    check("3 mood textarea wide on desktop (>=250px)", w >= 250, w)
    pg.set_viewport_size({"width": 390, "height": 844})
    pg.wait_for_timeout(300)   # รอ resize handler วาดกราฟใหม่ (canvas ตั้งความกว้างเป็น px ตามจอเดิมจนกว่าจะวาดซ้ำ)
    w2 = pg.evaluate("document.getElementById('moodNote').getBoundingClientRect().width")
    sw = pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")
    check("3 mobile textarea ok + no horizontal scroll", w2 >= 200 and sw, (w2, sw))
    pg.set_viewport_size({"width": 1280, "height": 900})

    # ---------- 1) เพิ่ม/ลบ/แก้ไขอารมณ์
    pg.click("#moodPicker [data-v='2']"); pg.fill("#moodNote", "ตลาดแดง กังวล")
    pg.click("#addMoodBtn")
    m = stored("moods")
    check("1 mood added", len(m) == 1 and m[0]["mood"] == "2" and m[0]["note"] == "ตลาดแดง กังวล")
    orig_date, mid = m[0]["date"], m[0]["id"]

    # ลบ แล้วกดยกเลิกในกล่องยืนยัน -> ต้องยังอยู่
    state["accept"] = False; state["msgs"].clear()
    pg.click("[data-delmood]"); pg.wait_for_timeout(300)   # ตัวจัดการลบรอ 1 รอบ event loop หลัง confirm ก่อนซิงก์/เขียน
    check("1 delete asks confirmation", len(state["msgs"]) == 1 and "ลบบันทึกอารมณ์" in state["msgs"][0], state["msgs"])
    check("1 cancel keeps the entry", len(stored("moods")) == 1)

    # แก้ไข
    pg.click("[data-editmood]")
    check("1 edit loads note into form", pg.input_value("#moodNote") == "ตลาดแดง กังวล")
    check("1 edit preselects mood 2", pg.evaluate("document.querySelector('#moodPicker [data-v=\"2\"]').classList.contains('active')"))
    check("1 edit button label + cancel visible", "แก้ไข" in txt("#addMoodBtn") and pg.is_visible("#cancelMoodBtn"))
    pg.click("#moodPicker [data-v='5']"); pg.fill("#moodNote", "ตลาดเขียว คึกคัก")
    pg.click("#addMoodBtn")
    m = stored("moods")
    check("1 edit saved in place (1 entry, new mood/note, same date+id)",
          len(m) == 1 and m[0]["mood"] == "5" and m[0]["note"] == "ตลาดเขียว คึกคัก" and m[0]["date"] == orig_date and m[0]["id"] == mid, m)
    check("1 form reset after save", txt("#addMoodBtn") == "+ บันทึก" and not pg.is_visible("#cancelMoodBtn") and pg.input_value("#moodNote") == "")

    # ยกเลิกการแก้ไข
    pg.click("[data-editmood]"); pg.fill("#moodNote", "พิมพ์แล้วไม่เอา"); pg.click("#cancelMoodBtn")
    check("1 cancel edit leaves data unchanged", stored("moods")[0]["note"] == "ตลาดเขียว คึกคัก" and pg.input_value("#moodNote") == "")

    # ลบรายการที่กำลังแก้อยู่ แล้วยืนยัน -> ฟอร์มกลับโหมดเพิ่ม
    pg.click("[data-editmood]")
    state["accept"] = True
    pg.click("[data-delmood]"); pg.wait_for_timeout(300)   # ตัวจัดการลบรอ 1 รอบ event loop หลัง confirm ก่อนซิงก์/เขียน
    check("1 delete confirmed removes + resets edit mode", len(stored("moods")) == 0 and txt("#addMoodBtn") == "+ บันทึก")

    # ---------- 2) CSV
    pg.evaluate("""(()=>{
      localStorage.setItem('trading-journal:trades', JSON.stringify([
        {id:'c1',date:'2026-01-05',symbol:'PTT',side:'buy', qty:1000,price:34,fee:57,tag:'Break,out',emotion:'4',note:'เหตุผล "ดี", บรรทัด1\\nบรรทัด2'},
        {id:'c2',date:'2026-02-10',symbol:'PTT',side:'sell',qty:1000,price:37,fee:60,tag:'',emotion:'',note:'=HYPERLINK("http://x","y")'},
        {id:'c3',date:'2026-02-10',symbol:'@evil',side:'buy',qty:10,price:1.5,fee:0,tag:'-cmd',emotion:'',note:''}
      ]));
      localStorage.setItem('trading-journal:dividends', JSON.stringify([{id:'d1',date:'2026-02-01',symbol:'PTT',gross:1500,tax:150}]));
    })()""")
    pg.reload()
    with pg.expect_download() as dl:
        pg.click("#csvBtn")
    d = dl.value
    check("2 filename .csv", d.suggested_filename.startswith("trading-journal-") and d.suggested_filename.endswith(".csv"), d.suggested_filename)
    raw = open(d.path(), "rb").read()
    check("2 UTF-8 BOM", raw[:3] == b"\xef\xbb\xbf")
    text = raw.decode("utf-8-sig")
    import csv, io
    rows = list(csv.reader(io.StringIO(text, newline="")))
    check("2 CRLF line endings", "\r\n" in text and "\n" not in text.replace("\r\n", "").replace("บรรทัด1\nบรรทัด2", ""))
    check("2 header has 12 columns", len(rows[0]) == 12 and rows[0][0] == "วันที่" and rows[0][8].startswith("กำไร"), rows[0])
    check("2 all rows 12 columns", all(len(r) == 12 for r in rows), [len(r) for r in rows])
    by = {(r[0], r[1], r[2]): r for r in rows[1:]}
    buy = by[("2026-01-05", "ซื้อ", "PTT")]
    check("2 buy row values + tag with comma + note with quotes/newline",
          buy[3] == "1000" and buy[4] == "34" and buy[5] == "57" and buy[6] == "34000" and buy[8] == ""
          and buy[9] == "Break,out" and buy[10] == "มั่นใจ" and buy[11] == 'เหตุผล "ดี", บรรทัด1\nบรรทัด2', buy)
    sell = by[("2026-02-10", "ขาย", "PTT")]
    check("2 sell row pnl = 2883 (37000-60-34057)", sell[8] == "2883", sell)
    check("2 formula-looking note neutralised", sell[11].startswith("'=") , sell[11])
    evil = by[("2026-02-10", "ซื้อ", "'@EVIL")]   # สัญลักษณ์ถูกแปลงเป็นตัวพิมพ์ใหญ่ตอนโหลด (เหมือนตอนกรอกในฟอร์ม)
    check("2 symbol/tag formula guard", evil[9] == "'-cmd", evil)
    dv = by[("2026-02-01", "ปันผล", "PTT")]
    check("2 dividend row gross/tax/net", dv[6] == "1500" and dv[7] == "150" and dv[8] == "1350", dv)
    check("2 sorted by date asc", [r[0] for r in rows[1:]] == sorted(r[0] for r in rows[1:]))

    # ว่าง -> แจ้งเตือน ไม่ดาวน์โหลด
    pg.evaluate("localStorage.clear()"); pg.reload()
    state["msgs"].clear()
    pg.click("#csvBtn")
    check("2 empty data -> alert, no crash", state["msgs"] and "ไม่มีข้อมูล" in state["msgs"][0], state["msgs"])

    # backup json ยังทำงานหลัง refactor downloadBlob
    pg.evaluate("localStorage.setItem('trading-journal:trades', JSON.stringify([{id:'z',date:'2026-01-01',symbol:'A',side:'buy',qty:1,price:1,fee:0}]))"); pg.reload()
    with pg.expect_download() as dl2:
        pg.click("#exportBtn")
    check("json backup still downloads", dl2.value.suggested_filename.startswith("trading-journal-backup-"))
    check("backup meta recorded", stored("meta")["lastBackup"] is not None)

    check("no console/page errors", not errors, str(errors))
    b.close()

print("\nFAILED:" if fails else "\nALL PASS", fails)
sys.exit(1 if fails else 0)
