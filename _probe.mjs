export default async function run(page, ui) {
  await page.evaluate(() => document.body.classList.add('no-ui'));
  const res = await page.evaluate(() => {
    const f = document.getElementById('frame');
    const r = f.getBoundingClientRect();
    // replicate dirAt logic with the constants in page
    const EDGE = 14, CORNER = 18;
    function dirAt(px, py) {
      const rr = f.getBoundingClientRect(), lx = px - rr.left, ly = py - rr.top;
      window.__rr = { w: rr.width, h: rr.height, l: rr.left, t: rr.top };
      const nearW = lx <= EDGE, lx2 = rr.width - lx <= EDGE, lyT = ly <= EDGE, lyB = rr.height - ly <= EDGE;
      const cnw = lx <= CORNER && ly <= CORNER, cne = lx2 <= CORNER && ly <= CORNER,
            csw = lx <= CORNER && lyB <= CORNER, cse = lx2 <= CORNER && lyB <= CORNER;
      if (cnw) return 'nw'; if (cne) return 'ne'; if (csw) return 'sw'; if (cse) return 'se';
      let d = '';
      if (lyT) d += 'n'; if (lyB) d += 's'; if (nearW) d += 'w'; if (lx2) d += 'e';
      return d || null;
    }
    return {
      rect: { l: r.left, t: r.top, w: r.width, h: r.height },
      at_body: dirAt(20, 162),
      at_body_dbg: (() => { const rr = f.getBoundingClientRect(); const lx = 20 - rr.left, ly = 162 - rr.top; const nearW = lx <= EDGE, lx2 = rr.width - lx <= EDGE, lyT = ly <= EDGE, lyB = rr.height - ly <= EDGE; return { lx, ly, nearW, lx2, lyT, lyB, cse: (rr.width - lx) <= 18 && (rr.height - ly) <= 18 }; })(),
      at_se: dirAt(r.left + r.width - 6, r.top + r.height - 6),
      at_nw: dirAt(r.left + 6, r.top + 6),
      rr: window.__rr
    };
  });
  return res;
}
