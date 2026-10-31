import fs from 'fs';
const url = 'file:///D:/%D0%92%D0%B8%D0%B4%D0%B6%D0%B5%D1%82%20OBS/dump_webcam.html';
const geom = () => { const r = document.getElementById('frame').getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }; };
await page.goto(url);
await page.addStyleTag({ content: '*{caret-color:transparent}' });
await page.evaluate(() => document.body.classList.add('no-ui'));
const before = await page.evaluate(geom);
console.log('before:', JSON.stringify(before));

// --- Тест 1: перетаскивание за середину ---
const cx = before.x + 100, cy = before.y + Math.round(before.h / 2);
await page.mouse.move(cx, cy);
await page.mouse.down();
await page.mouse.move(cx + 60, cy - 30, { steps: 5 });
const mid = await page.evaluate(() => window.__rz());
await page.mouse.up();
const afterDrag = await page.evaluate(geom);
console.log('mid(drag):', JSON.stringify(mid));
console.log('afterDrag:', JSON.stringify(afterDrag));

// --- Тест 2: ресайз за SE-угол (внутри радиуса скругления) ---
const r2 = await page.evaluate(geom);
const sx = r2.x + r2.w - 12, sy = r2.y + r2.h - 12;
await page.mouse.move(sx, sy);
await page.mouse.down();
await page.mouse.move(sx + 70, sy + 50, { steps: 5 });
const mid2 = await page.evaluate(() => window.__rz());
await page.mouse.up();
const afterRz = await page.evaluate(geom);
console.log('mid(resize):', JSON.stringify(mid2));
console.log('afterResize:', JSON.stringify(afterRz));

// --- Тест 3: ресайз за правый край ---
const r3 = await page.evaluate(geom);
const ex = r3.x + r3.w - 8, ey = r3.y + Math.round(r3.h / 2);
await page.mouse.move(ex, ey);
await page.mouse.down();
await page.mouse.move(ex - 50, ey, { steps: 5 });
const mid3 = await page.evaluate(() => window.__rz());
await page.mouse.up();
const afterRz2 = await page.evaluate(geom);
console.log('mid(edge):', JSON.stringify(mid3));
console.log('afterEdgeResize:', JSON.stringify(afterRz2));

// --- Проверка сохранения в localStorage ---
const saved = await page.evaluate(() => { const s = JSON.parse(localStorage.getItem('dota2obs.hookCam.settings') || '{}'); return s.geom || null; });
console.log('savedGeom:', JSON.stringify(saved));
console.log('console errors were printed above if any');
