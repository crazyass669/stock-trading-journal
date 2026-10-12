// Service worker : ใช้งานออฟไลน์ + เปิดเร็ว (แอปไม่มี backend — ข้อมูลอยู่ใน localStorage ไม่ผ่านที่นี่)
//
// กลยุทธ์
//  - ไฟล์ของแอปเอง (same-origin): ตอบจากแคชทันที แล้วโหลดตัวใหม่เก็บไว้เบื้องหลัง (stale-while-revalidate)
//    แคชเฉพาะคำตอบที่ ok (2xx) และเป็น basic — กัน 404/5xx ชั่วคราวระหว่าง deploy ไปทับไฟล์ดีที่เก็บไว้
//  - คีย์แคชตัด query string ทิ้ง (?utm=… ?fbclid=… ใช้ลิงก์เดียวกัน) และ navigation ที่หาไม่เจอ/ออฟไลน์ถอยไป index.html
//  - ข้ามโดเมนอื่น (เช่น Google Fonts): network-first แล้ว fallback เป็นแคชเมื่อออฟไลน์
//    (คำขอ stylesheet ข้ามโดเมนเป็น opaque อ่านสถานะไม่ได้ จึงยอมเก็บ — ไฟล์ฟอนต์ไม่ได้ทำให้แอปเสีย แค่ตกไปใช้ฟอนต์ระบบ)
const CACHE_PREFIX = 'trading-journal-';
const CACHE_NAME = CACHE_PREFIX + 'v6';
const CORE_ASSETS = [
  './',
  './index.html',
  './manifest.json',
  './icon-192.png',
  './icon-512.png'
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE_NAME)
      .then(cache => Promise.all(CORE_ASSETS.map(u =>
        // cache:'reload' ข้าม HTTP cache — GitHub Pages ส่ง max-age=600 ไม่งั้นอาจ precache ไฟล์เก่าจนเวอร์ชันใหม่ไม่เข้า
        fetch(new Request(u, {cache: 'reload'})).then(res => {
          if(!res.ok) throw new Error('precache failed: ' + u + ' ' + res.status);
          return cache.put(u, res);
        })
      )))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    // ลบเฉพาะแคชของแอปนี้ที่เป็นเวอร์ชันเก่า — origin แบบ user.github.io ใช้ร่วมกับโปรเจกต์อื่น ห้ามแตะแคชของเขา
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k.startsWith(CACHE_PREFIX) && k !== CACHE_NAME).map(k => caches.delete(k)))
    ).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if(req.method !== 'GET') return;
  const url = new URL(req.url);
  if(url.origin === self.location.origin){
    e.respondWith(sameOrigin(e, url));
  } else {
    e.respondWith(crossOrigin(e));
  }
});

async function sameOrigin(e, url){
  const req = e.request;
  const cache = await caches.open(CACHE_NAME);
  const key = new Request(url.origin + url.pathname);   // ตัด query string
  const isNav = req.mode === 'navigate';
  const cached = await cache.match(key);   // ตรงคีย์เท่านั้น — index.html เป็นทางถอยเฉพาะตอนเครือข่ายล้ม (ด้านล่าง) ไม่ใช่ตอบแทนทุกหน้าที่ยังไม่เคยแคช

  let putDone = Promise.resolve();
  // ตรวจกับเซิร์ฟเวอร์เสมอ (cache:'no-cache' = ถามว่ามีของใหม่ไหม) — ไม่งั้นคำตอบจาก HTTP cache (GitHub Pages max-age=600)
  // จะถูกเก็บทับแคชของ worker ซ้ำด้วยไฟล์เก่า แล้วเวอร์ชันใหม่ช้าไปอีกหลายรอบการเปิด
  const network = fetch(new Request(req, {cache: 'no-cache'})).then(res => {
    if(res.ok && res.type === 'basic'){
      const copy = res.clone();   // ต้อง clone ก่อนคืน res ให้หน้าเว็บ (body อ่านได้ครั้งเดียว)
      putDone = cache.put(key, copy).catch(() => {});
    }
    return res;
  });
  // ให้ worker อยู่จนโหลดตัวใหม่เก็บแคชเสร็จ (เรียกตอนนี้ขณะ event ยังทำงาน) · ข้อผิดพลาดเครือข่ายไม่ใช่ข้อผิดพลาดของ worker
  e.waitUntil(network.then(() => putDone, () => {}));

  if(cached) return cached;
  try{
    return await network;
  }catch(err){
    if(isNav){
      const fallback = await cache.match('./index.html');
      if(fallback) return fallback;
    }
    return Response.error();
  }
}

async function crossOrigin(e){
  const cache = await caches.open(CACHE_NAME);
  try{
    const res = await fetch(e.request);
    if(res.ok || res.type === 'opaque'){
      const copy = res.clone();
      e.waitUntil(cache.put(e.request, copy).catch(() => {}));
    }
    return res;
  }catch(err){
    const cached = await cache.match(e.request);
    return cached || Response.error();
  }
}
