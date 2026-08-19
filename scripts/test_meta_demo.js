const sharp = require('sharp');
const https = require('https');
const fs = require('fs');
const path = require('path');

const OUTPUT_DIR = path.join(__dirname, 'test_meta_with_avatars');
fs.mkdirSync(OUTPUT_DIR, { recursive: true });

const AVATAR_SIZE = 40;
const BORDER = 3;
const TOTAL = AVATAR_SIZE + BORDER * 2;
const AVATAR_MARGIN = 8;

function fetchImage(url) {
  return new Promise((resolve, reject) => {
    const req = https.get(url, (res) => {
      if (res.statusCode === 301 || res.statusCode === 302) {
        fetchImage(res.headers.location).then(resolve).catch(reject);
        return;
      }
      const chunks = [];
      res.on('data', chunk => chunks.push(chunk));
      res.on('end', () => resolve(Buffer.concat(chunks)));
      res.on('error', reject);
    });
    req.on('error', reject);
  });
}

async function generateTestImage() {
  console.log('Downloading hero icon...');
  const heroIconBuffer = await fetchImage('https://cdn.cloudflare.steamstatic.com/apps/dota2/images/dota_react/heroes/naga_siren.png');

  console.log('Downloading avatar...');
  const avatarBuffer = await fetchImage('https://avatars.steamstatic.com/def8d426ec47c0c120bf6ea2506f0502ddf25e2e_full.jpg');

  console.log('Creating circular avatar with border...');
  
  // Create circular avatar
  const circularAvatar = await sharp(avatarBuffer)
    .resize(AVATAR_SIZE, AVATAR_SIZE, { fit: 'cover' })
    .composite([
      {
        input: Buffer.from(
          `<svg width="${AVATAR_SIZE}" height="${AVATAR_SIZE}">
            <circle cx="${AVATAR_SIZE/2}" cy="${AVATAR_SIZE/2}" r="${AVATAR_SIZE/2}" fill="white"/>
          </svg>`
        ),
        blend: 'dest-in'
      }
    ])
    .png()
    .toBuffer();

  // Create white border circle
  const borderCircle = Buffer.from(
    `<svg width="${TOTAL}" height="${TOTAL}">
      <circle cx="${TOTAL/2}" cy="${TOTAL/2}" r="${TOTAL/2 - 1}" fill="white"/>
    </svg>`
  );

  // Composite: border + avatar
  const avatarWithBorder = await sharp(borderCircle)
    .composite([
      {
        input: circularAvatar,
        top: BORDER,
        left: BORDER,
        blend: 'over'
      }
    ])
    .png()
    .toBuffer();

  console.log('Compositing final image...');
  const heroImage = sharp(heroIconBuffer);
  const meta = await heroImage.metadata();
  const x = meta.width - TOTAL - AVATAR_MARGIN;
  const y = AVATAR_MARGIN;

  const result = await heroImage
    .composite([
      {
        input: avatarWithBorder,
        top: y,
        left: x,
        blend: 'over'
      }
    ])
    .png()
    .toFile(path.join(OUTPUT_DIR, 'test_naga_siren_with_avatar.png'));

  console.log('Saved:', result.path);
  console.log('Size:', result.size, 'bytes');
}

generateTestImage().catch(console.error);
