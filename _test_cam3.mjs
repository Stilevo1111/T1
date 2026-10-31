const url = 'file:///D:/%D0%92%D0%B8%D0%B4%D0%B6%D0%B5%D1%82%20OBS/dump_webcam.html';
const geom = () => { const r = document.getElementById('frame').getBoundingClientRect(); return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) }; };

export default async function run(page) {
  await page.goto(url);
  await page.evaluate(() => document.body.classList.add('no-ui'));

  // Переместить и увеличить камеру
  const b = await page.evaluate(geom);
  await page.mouse.move(b.x + b.w - 12, b.y + b.h - 12);
  await page.mouse.down();
  await page.mouse.move(b.x + b.w + 100, b.y + b.h + 60, { steps: 5 });
  await page.mouse.up();
  await page.mouse.move(b.x + 100, b.y + 150);
  await page.mouse.down();
  await page.mouse.move(b.x + 140, b.y + 120, { steps: 5 });
  await page.mouse.up();
  const after = await page.evaluate(geom);
  console.log('after:', JSON.stringify(after));

  // Изменить настройку (яркость) — save() не должен стереть geom
  await page.evaluate(() => { document.body.classList.remove('no-ui'); });
  await page.locator('#bright').fill('120');
  const ls = await page.evaluate(() => {
    try { return JSON.parse(localStorage.getItem('dota2obs.hookCam.settings') || '{}').geom || null; } catch { return null; }
  });
  console.log('geom in ls after settings change:', JSON.stringify(ls));

  // Перезагрузка — геометрия должна восстановиться
  await page.reload();
  const restored = await page.evaluate(geom);
  console.log('restored:', JSON.stringify(restored));
  return { after, ls, restored };
}
