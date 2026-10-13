"""
รันชุดทดสอบทั้งหมด:  python run_all.py [--browser chromium|webkit] [--quick]
  --quick  ลดจำนวนชุดข้อมูลสุ่ม (เร็วขึ้น ใช้ระหว่างพัฒนา) · ไม่ใส่ = เต็ม (ใช้ก่อน push เมื่อแก้สูตรคำนวณ)
"""
import argparse, os, re, subprocess, sys
from _paths import TESTS

ap = argparse.ArgumentParser()
ap.add_argument("--browser", default="chromium", choices=["chromium", "webkit"])
ap.add_argument("--quick", action="store_true")
args = ap.parse_args()

env = dict(os.environ, BROWSER=args.browser, PYTHONUTF8="1")
rows = []

def run(name, extra_env=None):
    e = dict(env, **(extra_env or {}))
    p = subprocess.run([sys.executable, str(TESTS / name)], env=e, capture_output=True, text=True, encoding="utf-8")
    out = p.stdout + p.stderr
    passed = len(re.findall(r"^PASS", out, re.M)); failed = len(re.findall(r"^FAIL", out, re.M))
    extra = re.search(r"(scenarios=.*mismatches=\d+)", out)
    ok = p.returncode == 0
    rows.append((name, ok, passed, failed, extra.group(1) if extra else ""))
    if not ok: print(f"--- {name} output (tail) ---\n" + "\n".join(out.strip().splitlines()[-15:]))

for n in ["test_tj.py", "test_tj2.py", "test_tj3.py", "test_tj4.py", "test_tj5.py", "test_tj6.py", "test_version.py", "test_sw.py"]:
    run(n)
run("test_diff.py", {"N": "800" if args.quick else "6000"})
run("test_diff_ui.py", {"N": "15" if args.quick else "60"})
run("mutation_check.py")

width = max(len(r[0]) for r in rows)
for name, ok, p, f, extra in rows:
    print(f"{'OK  ' if ok else 'FAIL'} {name:<{width}}  pass={p:<3} fail={f:<2} {extra}")
print(f"\nbrowser={args.browser} quick={args.quick}  =>  {'ALL OK' if all(r[1] for r in rows) else 'FAILURES'}")
sys.exit(0 if all(r[1] for r in rows) else 1)
