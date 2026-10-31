export default async function run(page, ui) {
  await page.evaluate(() => document.body.classList.add('no-ui'));
  const geom = () => page.evaluate(() => {
    const f = document.getElementById('frame');
    if (!f) return { error: 'no frame' };
    const r = f.getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  });
  const before = await geom();
  // drag body
  await page.mouse.move(before.x + 20, before.y + before.h / 2);
  await page.mouse.down();
  await page.mouse.move(before.x + 140, before.y + before.h / 2 + 80, { steps: 5 });
  await page.mouse.up();
  const afterDrag = await geom();
  // grow via SE corner
  const cur = await geom();
  const sx = cur.x + cur.w - 6, sy = cur.y + cur.h - 6;
  const dirProbe = await page.evaluate(() => {
    const f = document.getElementById('frame');
    const r = f.getBoundingClientRect();
    const EDGE = 14, CORNER = 18;
    const lx = (r.left + r.width - 6) - r.left, ly = (r.top + r.height - 6) - r.top;
    const nearW = lx <= EDGE, nearE = (r.width - lx) <= EDGE, nearT = ly <= EDGE, nearB = (r.height - ly) <= EDGE;
    return { lx, ly, nearW, nearE, nearT, nearB, se: nearE && nearB };
  });
  await page.mouse.move(sx, sy);
  await page.mouse.down();
  await page.mouse.move(cur.x + cur.w - 6 + 120, cur.y + cur.h - 6 + 80, { steps: 5 });
  await page.mouse.up();
  const afterGrow = await geom();
  // shrink via NW corner (clamps at min)
  const cur2 = await geom();
  await page.mouse.move(cur2.x + 6, cur2.y + 6);
  await page.mouse.down();
  await page.mouse.move(cur2.x + 6 + 400, cur2.y + 6 + 400, { steps: 5 });
  await page.mouse.up();
  const afterShrink = await geom();
  const saved = await page.evaluate(() => {
    try { return JSON.parse(localStorage.getItem('dota2obs.hookCam.settings')).geom; } catch (e) { return null; }
  });
  return { before, afterDrag, dirProbe, afterGrow, afterShrink, saved };
}
