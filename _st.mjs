export default async function run(page, ui) {
  await page.evaluate(() => document.body.classList.add('no-ui'));
  const geom = () => page.evaluate(() => {
    const r = document.getElementById('frame').getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  });
  const g = await geom();
  await page.mouse.move(g.x + g.w - 6, g.y + g.h - 6);
  await page.mouse.down();
  const st1 = await page.evaluate(() => window.__rz ? window.__rz() : 'no hook');
  await page.mouse.move(g.x + g.w - 6 + 50, g.y + g.h - 6 + 30, { steps: 2 });
  const st2 = await page.evaluate(() => window.__rz ? window.__rz() : 'no hook');
  await page.mouse.up();
  const after = await geom();
  return { g, st1, st2, after };
}
