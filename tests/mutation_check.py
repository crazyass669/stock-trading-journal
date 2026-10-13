"""
พิสูจน์ว่าตัวเทียบตัวคำนวณ (test_diff.py) "จับบั๊กได้จริง": ใส่บั๊กลงสำเนาของ index.html ทีละแบบ แล้วต้องเจอความคลาดเคลื่อน
ถ้าแบบไหนไม่ถูกจับ = ตัวเทียบหลวมเกินไป (หรือโค้ดเปลี่ยนจน anchor หาไม่เจอ → ต้องอัปเดตรายการด้านล่างให้ตรงโค้ดปัจจุบัน)
รัน: python mutation_check.py     (ต้องมี node + python; ไม่ต้องใช้เบราว์เซอร์)
"""
import os, re, subprocess, sys
from _paths import REPO, TESTS, TMP

MUTATIONS = [
    ("AVG weighted price off by 0.01%", "price: q>0 ? c/q : 0, day:", "price: q>0 ? (c/q)*1.0001 : 0, day:"),
    ("buy fee not folded into cost", "lots.push({qty:t.qty, price:t.price + feePerShare,", "lots.push({qty:t.qty, price:t.price,"),
    ("sell fee not deducted", "const proceeds = (t.price * t.qty) - fee;", "const proceeds = (t.price * t.qty);"),
    ("defer every sell when a buy follows (ignores holdings)", "else if(buyAfter[idx] && t.qty > held() + EPS) deferred.push(t);", "else if(buyAfter[idx]) deferred.push(t);"),
    ("same-day order by id instead of recorded position", ".sort((a,b)=> a.t.date.localeCompare(b.t.date) || a.i - b.i)",
     ".sort((a,b)=> a.t.date.localeCompare(b.t.date) || String(b.t.id).localeCompare(String(a.t.id)))"),
    ("break-even counted as loss (isLoss < 0)", "const isLoss = e => e.pnl < -PNL_EPS;", "const isLoss = e => e.pnl < 0;"),
    ("FIFO takes from the newest lot (LIFO)", "const lot = lots[0];\n          const take", "const lot = lots[lots.length-1];\n          const take"),
]

def run_diff(html, n="500", seed="5"):
    env = dict(os.environ, N=n, SEED=seed, PYTHONUTF8="1")
    if html: env["HTML_OVERRIDE"] = str(html)
    out = subprocess.run([sys.executable, str(TESTS / "test_diff.py")], env=env, capture_output=True, text=True, encoding="utf-8").stdout
    m = re.search(r"mismatches=(\d+)", out)
    return int(m.group(1)) if m else None

src = (REPO / "index.html").read_text(encoding="utf-8")
bad = 0
base = run_diff(None)
print(f"baseline (unmodified app): mismatches={base}")
if base != 0:
    print("FAIL baseline must be 0"); bad += 1
for name, old, new in MUTATIONS:
    if old not in src:
        print(f"FAIL anchor missing (update mutation list): {name}"); bad += 1; continue
    tmp = TMP / "mut_index.html"; tmp.write_text(src.replace(old, new), encoding="utf-8")
    n = run_diff(tmp)
    ok = n is not None and n > 0
    print(f"{'PASS' if ok else 'FAIL'} caught: {name}  (mismatches={n})")
    bad += 0 if ok else 1
sys.exit(1 if bad else 0)
