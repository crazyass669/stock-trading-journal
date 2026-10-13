// รันตัวคำนวณจริง (computeLedger / computeStats) ที่ดึงออกมาจาก index.html ตรงๆ — ไม่ใช่สำเนา — กับชุดข้อมูลทดสอบจำนวนมาก
// ใช้: node diff_node.js <index.html> <scenarios.json> <out.json>
const fs = require('fs');
const vm = require('vm');
const [,, htmlPath, inPath, outPath] = process.argv;
const html = fs.readFileSync(htmlPath, 'utf8');

const start = html.indexOf('const EPS = 0.0000001;');
const csIdx = html.indexOf('function computeStats(events, cumPoints){');
if (start < 0 || csIdx < 0) throw new Error('anchors not found');
// หาปีกกาปิดของ computeStats
let depth = 0, i = html.indexOf('{', csIdx), end = -1;
for (; i < html.length; i++) {
  const ch = html[i];
  if (ch === '{') depth++;
  else if (ch === '}') { depth--; if (depth === 0) { end = i + 1; break; } }
}
if (end < 0) throw new Error('computeStats end not found');
const segment = html.slice(start, end);

const ctx = vm.createContext({});
const api = vm.runInContext(
  `let trades = [], method = 'FIFO'; const round2 = n => Math.round(n*100)/100;\n${segment}\n;({computeLedger, computeStats, set(t, m){ trades = t; method = m; }})`,
  ctx
);

const scenarios = JSON.parse(fs.readFileSync(inPath, 'utf8'));
const out = scenarios.map(sc => {
  const res = {};
  for (const m of ['FIFO', 'AVG']) {
    api.set(sc.trades.map(t => ({...t})), m);
    const L = api.computeLedger();
    let run = 0;
    const cum = L.realizedEvents.map(e => ({cum: (run += e.pnl)}));
    const S = api.computeStats(L.realizedEvents, cum);
    res[m] = {
      events: L.realizedEvents.map(e => ({id: e.id, pnl: e.pnl, days: e.days, tag: e.tag, short: e.short, qty: e.qty, symbol: e.symbol, date: e.date})),
      holdings: L.holdings,
      shortfalls: L.shortfalls,
      stats: {...S, profitFactor: S.profitFactor === Infinity ? 'inf' : S.profitFactor}
    };
  }
  return res;
});
fs.writeFileSync(outPath, JSON.stringify(out));
console.log('scenarios:', scenarios.length);
