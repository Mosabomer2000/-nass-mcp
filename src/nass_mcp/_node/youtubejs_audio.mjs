/* Optional, independent InnerTube audio extractor (YouTube.js).
 * Usage: node youtubejs_audio.mjs VIDEO_ID DEST_FILE MAX_BYTES
 * Install youtubei.js in this scripts directory or project root with npm.
 * Never pass arbitrary URLs or filesystem paths from an untrusted client.
 */
import { createWriteStream } from 'node:fs';
import { unlink } from 'node:fs/promises';
import { Readable, Transform } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { Innertube } from 'youtubei.js';

const [videoId, destination, maxBytesArg] = process.argv.slice(2);
const maxBytes = Number(maxBytesArg);
if (!/^[\w-]{11}$/.test(videoId || '') || !destination ||
    !Number.isSafeInteger(maxBytes) || maxBytes < 1024 || maxBytes > 5e9) {
  throw new Error('Invalid input');
}
let bytes = 0;
const limit = new Transform({
  transform(chunk, _encoding, callback) {
    bytes += chunk.length;
    if (bytes > maxBytes) callback(new Error('Audio stream exceeds size limit'));
    else callback(null, chunk);
  }
});
try {
  const client = await Innertube.create();
  const stream = await client.download(videoId, { type: 'audio', quality: 'best', format: 'mp4' });
  await pipeline(Readable.fromWeb(stream), limit, createWriteStream(destination, { flags: 'wx' }));
  if (bytes < 4096) throw new Error('Empty or implausibly short audio stream');
  console.log(JSON.stringify({ ok: true, bytes }));
} catch (error) {
  await unlink(destination).catch(() => {});
  console.error(String(error?.message || error).slice(0, 250));
  process.exitCode = 1;
}
