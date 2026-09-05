// Google Drive uploader: Inspections / <date_property> / <Room> / Room_001.jpg
// Auth via Google Identity Services token client (scope drive.file = only files this app created).
import { GOOGLE_CLIENT_ID, DRIVE_ROOT_FOLDER } from './config.js';
import { fileName, folderName } from './export.js';

const SCOPE = 'https://www.googleapis.com/auth/drive.file';
const API = 'https://www.googleapis.com/drive/v3';
const UPLOAD = 'https://www.googleapis.com/upload/drive/v3/files?uploadType=multipart&fields=id';

let token = null, tokenExp = 0, tokenClient = null;
const folderCache = new Map(); // key: parentId/name -> folderId

function loadGis() {
  if (window.google && google.accounts) return Promise.resolve();
  return new Promise((res, rej) => {
    const s = document.createElement('script');
    s.src = 'https://accounts.google.com/gsi/client'; s.async = true; s.defer = true;
    s.onload = res; s.onerror = () => rej(new Error('Google sign-in script failed to load (offline?)'));
    document.head.appendChild(s);
  });
}

// interactive=true may open the Google account popup; must be called from a user tap the first time.
export async function getToken(interactive = true) {
  if (token && Date.now() < tokenExp - 60000) return token;
  await loadGis();
  return new Promise((res, rej) => {
    tokenClient = tokenClient || google.accounts.oauth2.initTokenClient({
      client_id: GOOGLE_CLIENT_ID, scope: SCOPE, callback: () => {},
    });
    tokenClient.callback = r => {
      if (r.error) return rej(new Error(r.error_description || r.error));
      token = r.access_token; tokenExp = Date.now() + (r.expires_in || 3600) * 1000;
      localStorage.setItem('drive.connected', '1');
      res(token);
    };
    tokenClient.error_callback = e => rej(new Error(e.message || e.type || 'Sign-in cancelled'));
    tokenClient.requestAccessToken({ prompt: interactive ? '' : 'none' });
  });
}
export const isConnected = () => localStorage.getItem('drive.connected') === '1';
export function disconnect() {
  if (token && window.google) google.accounts.oauth2.revoke(token, () => {});
  token = null; tokenExp = 0; folderCache.clear(); localStorage.removeItem('drive.connected');
}

async function api(path, opts = {}) {
  const t = await getToken(false).catch(() => getToken(true));
  const r = await fetch(path, { ...opts, headers: { Authorization: `Bearer ${t}`, ...(opts.headers || {}) } });
  if (r.status === 401) { token = null; throw new Error('Google session expired, tap Upload again'); }
  if (!r.ok) throw new Error(`Drive ${r.status}: ${(await r.text()).slice(0, 200)}`);
  return r.json();
}
const q = s => encodeURIComponent(s);
const esc = s => s.replace(/\\/g, '\\\\').replace(/'/g, "\\'");

async function ensureFolder(name, parentId = 'root') {
  const key = `${parentId}/${name}`;
  if (folderCache.has(key)) return folderCache.get(key);
  const query = `name='${esc(name)}' and mimeType='application/vnd.google-apps.folder' and '${parentId}' in parents and trashed=false`;
  const found = await api(`${API}/files?q=${q(query)}&fields=files(id)&pageSize=1`);
  let id = found.files && found.files[0] && found.files[0].id;
  if (!id) {
    const made = await api(`${API}/files?fields=id`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, mimeType: 'application/vnd.google-apps.folder', parents: [parentId] }),
    });
    id = made.id;
  }
  folderCache.set(key, id);
  return id;
}

async function uploadFile(blob, name, parentId) {
  const meta = JSON.stringify({ name, parents: [parentId] });
  const form = new FormData();
  form.append('metadata', new Blob([meta], { type: 'application/json' }));
  form.append('file', blob, name);
  const r = await api(UPLOAD, { method: 'POST', body: form });
  return r.id;
}

// Uploads every photo of the inspection that has no driveId yet. onProgress(done, total).
// markDone(photo, driveId) persists the id so retries skip finished files.
export async function syncInspection(insp, photos, markDone, onProgress, concurrency = 3) {
  const todo = photos.filter(p => !p.driveId);
  const total = todo.length; let done = 0;
  if (!total) return { uploaded: 0, failed: 0 };
  await getToken(true); // ensure signed in inside the user's tap
  const root = await ensureFolder(DRIVE_ROOT_FOLDER);
  const inspFolder = await ensureFolder(folderName(insp), root);
  const roomFolders = {};
  for (const room of new Set(todo.map(p => p.room))) roomFolders[room] = await ensureFolder(room, inspFolder);
  let failed = 0; const queue = [...todo];
  const worker = async () => {
    while (queue.length) {
      const p = queue.shift();
      try {
        const id = await uploadFile(p.blob, fileName(p.room, p.seq), roomFolders[p.room]);
        await markDone(p, id);
      } catch (e) { failed++; console.error('upload failed', p.room, p.seq, e); }
      done++; onProgress && onProgress(done, total);
    }
  };
  await Promise.all(Array.from({ length: Math.min(concurrency, total) }, worker));
  return { uploaded: total - failed, failed };
}
