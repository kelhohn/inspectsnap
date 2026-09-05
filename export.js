// Export: ZIP with folders (download only: Android Chrome refuses to share .zip via Web Share),
// or share the JPEGs themselves (room name baked into the filename) to Google Drive / any app.
const pad3 = n => String(n).padStart(3, '0');
const pad2 = n => String(n).padStart(2, '0');
const safe = s => s.replace(/[\\/:*?"<>|]+/g, '-').trim();
export function fileName(room, seq) { return `${safe(room).replace(/\s+/g, '_')}_${pad3(seq)}.jpg`; }
export function folderName(insp) {
  const d = new Date(insp.created);
  const iso = `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  return `${iso}_${safe(insp.name)}`;
}
const sortPhotos = (insp, photos) => [...photos].sort((a, b) =>
  (insp.rooms.indexOf(a.room) - insp.rooms.indexOf(b.room)) || (a.seq - b.seq));

export async function buildZip(insp, photos, onProgress) {
  const zip = new JSZip();
  const root = zip.folder(folderName(insp));
  const byRoom = {};
  photos.forEach(p => { (byRoom[p.room] = byRoom[p.room] || []).push(p); });
  for (const room of Object.keys(byRoom)) {
    const f = root.folder(safe(room));
    byRoom[room].sort((a, b) => a.seq - b.seq).forEach(p => f.file(fileName(room, p.seq), p.blob));
  }
  const blob = await zip.generateAsync({ type: 'blob', compression: 'STORE' }, m => onProgress && onProgress(m.percent));
  return new File([blob], `${folderName(insp)}.zip`, { type: 'application/zip' });
}
export function download(file) {
  const a = document.createElement('a');
  a.href = URL.createObjectURL(file); a.download = file.name; a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 10000);
}
export function canShareFiles() {
  const probe = new File([new Uint8Array(4)], 'x.jpg', { type: 'image/jpeg' });
  return !!(navigator.canShare && navigator.canShare({ files: [probe] }));
}
// Android Chrome caps Web Share at 10 files / 50 MB per call, so photos go out in batches.
const MAX_FILES = 10, MAX_BYTES = 45 * 1024 * 1024;
export function shareBatches(insp, photos) {
  const files = sortPhotos(insp, photos).map(p => new File([p.blob], fileName(p.room, p.seq), { type: 'image/jpeg', lastModified: p.ts }));
  const batches = []; let cur = [], bytes = 0;
  for (const f of files) {
    if (cur.length && (cur.length >= MAX_FILES || bytes + f.size > MAX_BYTES)) { batches.push(cur); cur = []; bytes = 0; }
    cur.push(f); bytes += f.size;
  }
  if (cur.length) batches.push(cur);
  return batches;
}
export function batchLabel(files) {
  const first = files[0].name.replace(/\.jpg$/, ''), last = files[files.length - 1].name.replace(/\.jpg$/, '');
  return files.length === 1 ? first : `${first} … ${last}`;
}
// Must be called synchronously inside a user tap (no await before it). Returns 'shared' | 'cancelled'.
export function shareFiles(files, title) {
  if (!(navigator.canShare && navigator.canShare({ files }))) return Promise.reject(new Error('This browser cannot share these files'));
  return navigator.share({ files, title }).then(() => 'shared', e => e.name === 'AbortError' ? 'cancelled' : Promise.reject(e));
}
