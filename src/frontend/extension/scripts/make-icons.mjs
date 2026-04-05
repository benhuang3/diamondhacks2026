// Generates 16/48/128 solid brand-color PNG icons with no external deps.
// Run with: node scripts/make-icons.mjs
import { writeFileSync, mkdirSync } from "node:fs";
import { deflateSync } from "node:zlib";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const outDir = join(__dirname, "..", "public", "icons");
mkdirSync(outDir, { recursive: true });

function crc32(buf) {
  let c;
  const table = (crc32.table ??= (() => {
    const t = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
      t[n] = c >>> 0;
    }
    return t;
  })());
  c = 0xffffffff;
  for (let i = 0; i < buf.length; i++)
    c = table[(c ^ buf[i]) & 0xff] ^ (c >>> 8);
  return (c ^ 0xffffffff) >>> 0;
}

function chunk(tag, data) {
  const len = Buffer.alloc(4);
  len.writeUInt32BE(data.length, 0);
  const tagBuf = Buffer.from(tag, "ascii");
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(crc32(Buffer.concat([tagBuf, data])), 0);
  return Buffer.concat([len, tagBuf, data, crc]);
}

function makePng(size) {
  const [br, bg, bb, ba] = [79, 70, 229, 255]; // brand indigo
  const w = size, h = size;
  const margin = size <= 16 ? 0 : Math.max(1, Math.floor(size / 16));
  const rows = [];
  for (let y = 0; y < h; y++) {
    const row = Buffer.alloc(1 + w * 4);
    row[0] = 0;
    for (let x = 0; x < w; x++) {
      const o = 1 + x * 4;
      const inside =
        x >= margin && x < w - margin && y >= margin && y < h - margin;
      if (inside) {
        row[o] = br;
        row[o + 1] = bg;
        row[o + 2] = bb;
        row[o + 3] = ba;
      } else {
        row[o] = 0;
        row[o + 1] = 0;
        row[o + 2] = 0;
        row[o + 3] = 0;
      }
    }
    rows.push(row);
  }
  const raw = Buffer.concat(rows);
  const idat = deflateSync(raw);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(w, 0);
  ihdr.writeUInt32BE(h, 4);
  ihdr[8] = 8; // bit depth
  ihdr[9] = 6; // RGBA
  ihdr[10] = 0;
  ihdr[11] = 0;
  ihdr[12] = 0;
  const sig = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  return Buffer.concat([
    sig,
    chunk("IHDR", ihdr),
    chunk("IDAT", idat),
    chunk("IEND", Buffer.alloc(0)),
  ]);
}

for (const s of [16, 48, 128]) {
  const out = join(outDir, `icon${s}.png`);
  writeFileSync(out, makePng(s));
  console.log("wrote", out);
}
