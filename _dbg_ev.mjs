export default async function run(page, ui) {
  await page.evaluate(() => document.body.classList.add('no-ui'));

  const geom = () => page.evaluate(() => {
    const f = document.getElementById('frame');
    const r = f.getBoundingClientRect();
    return { x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height) };
  });

  const before = await geom();

  // trace events
  await page.evaluate(() => {
    window.__ev = [];
    const f = document.getElementById('frame');
    const rec = (tag) => (e) => window.__ev.push({
      tag, x: e.clientX, y: e.clientY,
      target: e.target ? (e.target.id || e.target.className || e.target.tagName) : null
    });
    ['pointerdown', 'pointermove', 'pointerup'].forEach(t => {
      f.addEventListener(t, rec('frame:' + t));
      window.addEventListener(t, rec('win:' + t));
    });
  });

  // drag body — check 'dragging' class mid-drag
  await page.mouse.move(before.x + 20, before.y + before.h / 2);
  await page.mouse.down();
  await page.mouse.move(before.x + 30, before.y + before.h / 2 + 10, { steps: 2 });
  const midState = await page.evaluate(() => ({
    cls: document.getElementById('frame').className,
    cur: document.getElementById('frame').style.cursor,
    rz: document.getElementById('frame').dataset.rz || ''
  }));
  await page.mouse.move(before.x + 140, before.y + before.h / 2 + 80, { steps: 5 });
  await page.mouse.up();
  const afterDrag = await geom();
  const ev1 = await page.evaluate(() => window.__ev.splice(0, 100));

  // grow via SE corner
  const cur = await geom();
  await page.mouse.move(cur.x + cur.w - 6, cur.y + cur.h - 6);
  await page.mouse.down();
  await page.mouse.move(cur.x + cur.w - 6 + 120, cur.y + cur.h - 6 + 80, { steps: 5 });
  await page.mouse.up();
  const afterGrow = await geom();
  const ev2 = await page.evaluate(() => window.__ev.splice(0, 100));

  return { before, midState, afterDrag, ev1, afterGrow, ev2 };
}
