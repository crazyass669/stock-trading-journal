"""
เทียบตัวคำนวณจริงของแอป (ดึงจาก index.html มารันใน Node) กับตัวคำนวณอ้างอิงที่เขียนแยกใน Python ด้วยเลขเศษส่วนแม่นยำ (Fraction)
+ ตรวจกฎที่ไม่ขึ้นกับสเปกลำดับ (invariants) เช่น ต้นทุนรวมต้องไม่หาย/ไม่งอก
"""
import json, random, subprocess, sys, pathlib, datetime, os
from fractions import Fraction as F

import sys as _sys, pathlib as _pl; _sys.path.insert(0, str(_pl.Path(__file__).resolve().parent))
from _paths import REPO, TESTS, TMP
ROOT = TMP   # ที่เขียนไฟล์ชั่วคราว
HTML = pathlib.Path(os.environ["HTML_OVERRIDE"]) if os.environ.get("HTML_OVERRIDE") else REPO / "index.html"   # HTML_OVERRIDE ใช้ทดสอบกับสำเนาที่ใส่บั๊ก
N = int(os.environ.get("N", "3000"))
SEED = int(os.environ.get("SEED", "20261013"))
EPS = F(1, 10**7)
PNL_EPS = F(5, 1000)

# ------------------------------------------------------------ ตัวคำนวณอ้างอิง (เขียนใหม่ ไม่ได้คัดลอกโครงสร้างจากแอป)
def day_of(s):
    return datetime.date.fromisoformat(s).toordinal()

def ref_ledger(trades, method):
    T = [dict(t, qty=F(str(t["qty"])), price=F(str(t["price"])), fee=F(str(t["fee"]))) for t in trades]
    order = sorted(range(len(T)), key=lambda i: (T[i]["date"], i))   # วันที่ แล้วตามลำดับที่บันทึก
    ordpos = {T[i]["id"]: k for k, i in enumerate(order)}
    lots = {}          # symbol -> list of [qty, unit_cost, day, tag]
    events, shorts = [], []

    def held(sym): return sum((l[0] for l in lots.get(sym, [])), F(0))

    def dominant(pairs):   # pairs: [(tag, qty)] -> แท็กที่มีจำนวนมากสุด (ไม่นับว่าง, ไม่สนตัวพิมพ์, เสมอ = ตัวที่เจอก่อน)
        acc = {}
        for tag, q in pairs:
            k = (tag or "").lower()
            if k not in acc: acc[k] = [tag or "", F(0)]
            acc[k][1] += q
        best, bq = "", F(0)
        for k, (label, q) in acc.items():
            if k and q > bq: best, bq = label, q
        return best

    def do(t):
        sym = t["symbol"]; L = lots.setdefault(sym, [])
        if t["side"] == "buy":
            L.append([t["qty"], t["price"] + t["fee"] / t["qty"], day_of(t["date"]), t.get("tag", "")])
            if method == "AVG" and len(L) > 1:
                q = sum((l[0] for l in L), F(0)); c = sum((l[0] * l[1] for l in L), F(0))
                dsum = sum((l[0] * l[2] for l in L), F(0))
                tag = dominant([(l[3], l[0]) for l in L])
                L[:] = [[q, c / q if q else F(0), dsum / q if q else None, tag]]
        else:
            proceeds = t["price"] * t["qty"] - t["fee"]
            rest, cost, hq, hd, tq = t["qty"], F(0), F(0), F(0), []
            sell_day = day_of(t["date"])
            while rest > EPS and L:
                lot = L[0]; take = min(lot[0], rest)
                cost += take * lot[1]; hq += take; hd += take * (sell_day - lot[2]); tq.append((lot[3], take))
                lot[0] -= take; rest -= take
                if lot[0] <= EPS: L.pop(0)
            short = rest > EPS
            if short: shorts.append((t["date"], sym, rest))
            events.append({"id": t["id"], "pnl": proceeds - cost, "days": (hd / hq) if hq > 0 else None,
                           "tag": t.get("tag") or dominant(tq), "short": short, "qty": t["qty"], "symbol": sym, "date": t["date"]})

    i = 0
    while i < len(order):
        j = i
        while j < len(order) and T[order[j]]["date"] == T[order[i]]["date"]: j += 1
        by_sym = {}
        for k in range(i, j): by_sym.setdefault(T[order[k]]["symbol"], []).append(T[order[k]])
        for sym, lst in by_sym.items():
            deferred = []
            def flush():
                k = 0
                while k < len(deferred):
                    if deferred[k]["qty"] <= held(sym) + EPS: do(deferred.pop(k))
                    else: k += 1
            for idx, t in enumerate(lst):
                if t["side"] == "buy":
                    do(t); flush()
                elif t["qty"] > held(sym) + EPS and any(x["side"] == "buy" for x in lst[idx + 1:]):
                    deferred.append(t)
                else:
                    do(t)
            for t in deferred: do(t)
        i = j
    events.sort(key=lambda e: ordpos[e["id"]])
    holdings = {}
    for sym, L in lots.items():
        q = sum((l[0] for l in L), F(0))
        if q > EPS:
            c = sum((l[0] * l[1] for l in L), F(0)); holdings[sym] = (q, c, c / q)
    return events, holdings, shorts

def ref_stats(events):
    pn = [e["pnl"] for e in events]
    wins = [p for p in pn if p > PNL_EPS]; losses = [p for p in pn if p < -PNL_EPS]
    streak = mx = 0
    for p in pn:
        if p < -PNL_EPS: streak += 1; mx = max(mx, streak)
        else: streak = 0
    peak = dd = F(0); run = F(0)
    for p in pn:
        run += p; peak = max(peak, run); dd = max(dd, peak - run)
    held = [(e["days"], e["qty"]) for e in events if e["days"] is not None]
    hq = sum((q for _, q in held), F(0))
    sw, sl = sum(wins, F(0)), sum(losses, F(0))
    return {"n": len(pn), "nWin": len(wins), "nLoss": len(losses),
            "avgWin": sw / len(wins) if wins else None, "avgLoss": sl / len(losses) if losses else None,
            "profitFactor": ("inf" if sw > 0 else None) if sl == 0 else sw / -sl,
            "maxStreak": mx, "maxDD": dd, "avgDays": (sum((d * q for d, q in held), F(0)) / hq) if hq > 0 else None}

# ------------------------------------------------------------ สร้างชุดข้อมูลสุ่ม
rnd = random.Random(SEED)
def dec(lo, hi, places):
    v = rnd.randint(int(lo * 10**places), int(hi * 10**places)); return v / 10**places
def gen_scenario(k):
    syms = rnd.sample(["AAA", "BBB", "CCC", "DDD"], rnd.randint(1, 3))
    base = datetime.date(2026, 1, 1)
    style = rnd.choice(["int", "dec2", "mixed"])
    n = rnd.randint(2, 28)
    trades = []
    for i in range(n):
        d = (base + datetime.timedelta(days=rnd.randint(0, 9))).isoformat()     # หน้าต่างแคบ → วันเดียวกันซ้ำบ่อย
        side = "buy" if rnd.random() < 0.55 else "sell"
        qty = rnd.randint(1, 300) if style == "int" else (dec(0.01, 50, 2) if style == "dec2" else rnd.choice([rnd.randint(1, 300), dec(0.01, 50, 2)]))
        price = dec(1, 200, rnd.choice([2, 2, 4]))
        fee = rnd.choice([0, 0, dec(0, 25, 2), round(qty * price * 0.001572, 2)])
        trades.append({"id": f"t{k}_{i:02d}", "date": d, "symbol": rnd.choice(syms), "side": side, "qty": qty, "price": price, "fee": fee,
                       "tag": rnd.choice(["", "", "A", "a", "B", "Breakout"])})
    return {"trades": trades}   # ลำดับในอาร์เรย์ = ลำดับที่บันทึก (สุ่ม รวมทั้งขายก่อนซื้อ ขายเกิน)

scenarios = [gen_scenario(k) for k in range(N)]
# กรณีเจาะจง: ขายก่อนซื้อวันเดียวกัน, ขายแล้วซื้อกลับ, ขายเกิน, เศษทศนิยมของจำนวน (0.1+0.2), ขายเท่าทุนพอดี
fixed = [
    [("buy", "2026-01-01", 100, 10, 0), ("sell", "2026-01-05", 100, 12, 0), ("buy", "2026-01-05", 100, 14, 0)],
    [("sell", "2026-01-05", 100, 12, 0), ("buy", "2026-01-05", 100, 10, 0)],
    [("buy", "2026-01-01", 10, 10, 0), ("sell", "2026-01-02", 15, 11, 0)],
    [("buy", "2026-01-01", 0.1, 10, 0), ("buy", "2026-01-01", 0.2, 10, 0), ("sell", "2026-01-02", 0.3, 11, 0)],
    [("buy", "2026-01-01", 3, 10.07, 0.07), ("sell", "2026-01-02", 3, 10.45, 1.07)],
]
for k, spec in enumerate(fixed):
    scenarios.append({"trades": [{"id": f"f{k}_{i}", "date": d, "symbol": "AAA", "side": s, "qty": q, "price": p, "fee": f, "tag": ""} for i, (s, d, q, p, f) in enumerate(spec)]})

(ROOT / "diff_in.json").write_text(json.dumps(scenarios), encoding="utf-8")
subprocess.run(["node", str(TESTS / "diff_node.js"), str(HTML), str(ROOT / "diff_in.json"), str(ROOT / "diff_out.json")], check=True)
app = json.loads((ROOT / "diff_out.json").read_text(encoding="utf-8"))

# ------------------------------------------------------------ เทียบ
def close(a, b, rel=1e-9, ab=1e-6):
    if a is None or b is None: return a is None and b is None
    a, b = float(a), float(b)
    return abs(a - b) <= ab + rel * max(abs(a), abs(b))

bad = []; checks = 0
def fail(k, m, what, extra=""):
    bad.append((k, m, what, str(extra)[:300]))

for k, (sc, res) in enumerate(zip(scenarios, app)):
    tr = sc["trades"]
    inv_total = {}
    for m in ("FIFO", "AVG"):
        a = res[m]
        ev, hd, sh = ref_ledger(tr, m)

        # 1) ลำดับและรายละเอียดของเหตุการณ์ขาย
        checks += 1
        if [e["id"] for e in a["events"]] != [e["id"] for e in ev]:
            fail(k, m, "event order/ids", ([e["id"] for e in a["events"]], [e["id"] for e in ev])); continue
        for ae, re in zip(a["events"], ev):
            checks += 1
            if not close(ae["pnl"], re["pnl"]): fail(k, m, f"pnl {re['id']}", (ae["pnl"], float(re["pnl"])))
            if not close(ae["days"], re["days"], 1e-9, 1e-7): fail(k, m, f"days {re['id']}", (ae["days"], re["days"] and float(re["days"])))
            if ae["tag"] != re["tag"]: fail(k, m, f"tag {re['id']}", (ae["tag"], re["tag"]))
            if ae["short"] != re["short"]: fail(k, m, f"short flag {re['id']}", (ae["short"], re["short"]))
        # 2) คงเหลือ
        checks += 1
        if set(a["holdings"]) != set(hd): fail(k, m, "holdings symbols", (sorted(a["holdings"]), sorted(hd)))
        else:
            for sym, (q, c, avg) in hd.items():
                h = a["holdings"][sym]
                if not (close(h["qty"], q) and close(h["cost"], c) and close(h["avg"], avg)): fail(k, m, f"holding {sym}", (h, [float(q), float(c), float(avg)]))
        # 3) ขายเกิน
        checks += 1
        if sorted((s["date"], s["symbol"], round(s["qty"], 6)) for s in a["shortfalls"]) != sorted((d, s_, round(float(q), 6)) for d, s_, q in sh):
            fail(k, m, "shortfalls", (a["shortfalls"], sh))
        # 4) สถิติ
        checks += 1
        near = any(abs(abs(float(e["pnl"])) - 0.005) < 1e-9 for e in ev)
        if not near:
            rs = ref_stats(ev); S = a["stats"]
            for key in ("n", "nWin", "nLoss", "maxStreak"):
                if S[key] != rs[key]: fail(k, m, f"stats.{key}", (S[key], rs[key]))
            for key in ("avgWin", "avgLoss", "maxDD", "avgDays"):
                if not close(S[key], rs[key], 1e-9, 1e-6): fail(k, m, f"stats.{key}", (S[key], rs[key] and float(rs[key])))
            pfa, pfr = S["profitFactor"], rs["profitFactor"]
            if (pfa == "inf") != (pfr == "inf") or (pfa not in ("inf", None) and not close(pfa, pfr, 1e-9, 1e-6)) or ((pfa is None) != (pfr is None)):
                fail(k, m, "stats.profitFactor", (pfa, pfr if pfr in ("inf", None) else float(pfr)))
        # 5) กฎที่ไม่ขึ้นกับสเปกลำดับ — ต้นทุนรวม/จำนวนรวมต้องคงที่ (ใช้ผลของแอปล้วนๆ)
        checks += 2
        buys = sum(F(str(t["qty"])) * F(str(t["price"])) + F(str(t["fee"])) for t in tr if t["side"] == "buy")
        removed = F(0)
        for ae in a["events"]:
            t = next(x for x in tr if x["id"] == ae["id"])
            removed += (F(str(t["price"])) * F(str(t["qty"])) - F(str(t["fee"]))) - F(ae["pnl"])
        rem_cost = sum(F(h["cost"]) for h in a["holdings"].values())
        if not close(float(buys), float(removed + rem_cost), 1e-9, 1e-5): fail(k, m, "cost conservation", (float(buys), float(removed + rem_cost)))
        qb = sum(F(str(t["qty"])) for t in tr if t["side"] == "buy"); qs = sum(F(str(t["qty"])) for t in tr if t["side"] == "sell")
        rem_q = sum(F(h["qty"]) for h in a["holdings"].values()); sf = sum(F(s["qty"]) for s in a["shortfalls"])
        if not close(float(qb - qs + sf), float(rem_q), 1e-9, 1e-6): fail(k, m, "qty conservation", (float(qb - qs + sf), float(rem_q)))
        inv_total[m] = sum(F(e["pnl"]) for e in a["events"]) - rem_cost   # Σกำไร = Σรายรับ − Σต้นทุนซื้อ + ต้นทุนคงเหลือ → (Σกำไร − ต้นทุนคงเหลือ) เท่ากันทั้งสองวิธี
    if len(inv_total) < 2:
        continue   # ลำดับเหตุการณ์ไม่ตรง (บันทึก mismatch ไปแล้ว) — ข้ามการตรวจ invariance ของชุดนี้
    checks += 1
    if not close(float(inv_total["FIFO"]), float(inv_total["AVG"]), 1e-9, 1e-5):
        fail(k, "both", "method invariance: realized - remaining cost must not depend on FIFO/AVG", (float(inv_total["FIFO"]), float(inv_total["AVG"])))

print(f"scenarios={len(scenarios)} (x2 methods)  comparisons={checks}  mismatches={len(bad)}")
for b in bad[:25]: print("MISMATCH", b)
sys.exit(1 if bad else 0)
