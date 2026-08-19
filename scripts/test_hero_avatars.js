const http = require('http');
const https = require('https');
const fs = require('fs');
const path = require('path');
const { Image, ImageDraw } = require('sharp');

// Simple HTTP request helper
function request(url) {
    return new Promise((resolve, reject) => {
        const mod = url.startsWith('https') ? https : http;
        mod.get(url, { timeout: 10000 }, (res) => {
            const chunks = [];
            res.on('data', chunk => chunks.push(chunk));
            res.on('end', () => resolve(Buffer.concat(chunks)));
            res.on('error', reject);
        }).on('error', reject);
    });
}

async function main() {
    console.log('Test generator: hero meta with avatar circles');
    console.log('Note: This is a standalone test script.');
    console.log('Run it on your local machine where Python/Pillow is available.');
    console.log('Or run the Python version: python test_hero_avatars.py');
}

main().catch(console.error);
