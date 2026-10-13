"""พาธกลางของชุดทดสอบ — อิงตำแหน่งไฟล์นี้ ไม่ฝังพาธของเครื่องใด"""
import pathlib, tempfile
TESTS = pathlib.Path(__file__).resolve().parent            # โฟลเดอร์ tests/
REPO = TESTS.parent                                        # รากของ repo (มี index.html, sw.js)
TMP = pathlib.Path(tempfile.gettempdir()) / "tj-tests"     # ที่เขียนไฟล์ชั่วคราว (ไฟล์นำเข้าทดสอบ ภาพหน้าจอ ผลระหว่างทาง)
TMP.mkdir(parents=True, exist_ok=True)
