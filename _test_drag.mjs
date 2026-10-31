export default async function run(page, ui) {
  await page.evaluate(() => document.body.classList.add('no-ui'));

  const geom = () => page.evaluate(() => {
    const r = document.getElementById('frame').getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  });

  const before = await geom();

  // 1) Drag frame body (middle-left area, away from handles/panel)
  await page.mouse.move(before.x + 20, before.y + before.h / 2);
  await page.mouse.down();
  await page.mouse.move(before.x + 140, before.y + before.h / 2 + 80, { steps: 5 });
  await page.mouse.up();
  const afterDrag = await geom();

  // 2) Grow via SE corner
  const se = await page.evaluate(() => {
    const f = document.getElementById('frame');
    const hr = f.querySelector('.rz-handle[data-dir="se"]').getBoundingClientRect();
    return { hx: Math.round(hr.left + hr.width / 2), hy: Math.round(hr.top + hr.height / 2), w: hr.width };
  });
  await page.mouse.move(se.hx, se.hy);
  await page.mouse.down();
  await page.mouse.move(se.hx + 120, se.hy + 80, { steps: 5 });
  await page.mouse.up();
  const afterGrow = await geom();

  // 3) Shrink via NW corner (opposite edge moves, clamp to min)
  const nw = await page.evaluate(() => {
    const f = document.getElementById('frame');
    const hr = f.querySelector('.rz-handle[data-dir="nw"]').getBoundingClientRect();
    return { hx: Math.round(hr.left + hr.width / 2), hy: Math.round(hr.top + hr.height / 2) };
  });
  await page.mouse.move(nw.hx, nw.hy);
  await page.mouse.down();
  await page.mouse.move(nw.hx + 400, nw.hy + 400, { steps: 5 });
  await page.mouse.up();
  const afterShrink = await geom();

  const saved = await page.evaluate(() => {
    try { return JSON.parse(localStorage.getItem('dota2obs.hookCam.settings')).geom; } catch (e) { return null; }
  });

  return { before, afterDrag, afterGrow, afterShrink, saved };
}
