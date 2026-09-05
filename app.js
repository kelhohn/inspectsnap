import { DB } from './db.js';
import { Camera } from './camera.js';
import { buildZip, download, shareBatches, shareFiles, batchLabel, canShareFiles, folderName } from './export.js';
import { syncInspection, isConnected } from './drive.js';
import { roomIcon, PARROT_SVG, UI } from './icons.js';
import { loadProfiles, defaultProfile, addProfile, updateProfile, setDefault, deleteProfile } from './profiles.js';

const $ = id => document.getElementById(id);
const state = { insp: null, room: null, counts: {}, seq: {} };
const cam = new Camera($('video'));
let burstTimer = null, grabbing = false;
const pending = new Set(); // in-flight encode+save jobs
const MAX_PENDING = 8;

// ---------- navigation ----------
function show(id) {
  document.querySelectorAll('.screen').forEach(s => s.classList.toggle('active', s.id === id));
  if (id !== 'cam') cam.stop();
}
document.querySelectorAll('[data-nav]').forEach(b => b.addEventListener('click', () => {
  if (b.closest('#cam')) return; // camera back button has its own handler (waits for saves)
  const to = b.dataset.nav;
  if (to === 'home') renderHome();
  if (to === 'rooms') renderRooms();
  if (to === 'settings') renderSettings();
}));

function toast(msg, ms = 1600) {
  const t = $('toast'); t.textContent = msg; t.classList.add('on');
  clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove('on'), ms);
}
// Text prompt. The input sits in a <form method="dialog">, so the keyboard's Enter/Done key submits it
// natively on Android (a keydown handler alone misses IME "Enter" events and left the text lost).
function ask(title, placeholder, okLabel = 'Create', { profile = false } = {}) {
  return new Promise(res => {
    const d = $('dlgName'), inp = $('dlgInput'), form = $('dlgForm');
    $('dlgTitle').textContent = title; inp.value = ''; inp.placeholder = placeholder;
    $('dlgProfileWrap').hidden = !profile;
    d.querySelector('.ok').textContent = okLabel;
    d.returnValue = '';
    form.onsubmit = e => { e.preventDefault(); d.close(inp.value.trim() ? 'ok' : 'cancel'); };
    d.querySelector('[value="cancel"]').onclick = () => d.close('cancel');
    d.onclose = () => res(d.returnValue === 'ok' ? inp.value.trim() : null);
    d.showModal(); setTimeout(() => inp.focus(), 50);
  });
}

// ---------- home ----------
async function renderHome() {
  show('home');
  const list = await DB.listInspections();
  const box = $('inspList'); box.innerHTML = '';
  $('inspEmpty').hidden = list.length > 0;
  for (const insp of list) {
    const counts = await DB.countsFor(insp.id);
    const total = Object.values(counts).reduce((a, b) => a + b, 0);
    const b = document.createElement('button'); b.className = 'card';
    b.innerHTML = `${roomIcon('external')}<div class="grow"><b></b><small>${new Date(insp.created).toLocaleDateString()} · ${total} photos</small></div><span class="muted">&#8250;</span>`;
    b.querySelector('b').textContent = insp.name;
    b.onclick = () => openInsp(insp.id);
    box.appendChild(b);
  }
}
$('newInsp').onclick = async () => {
  const profiles = loadProfiles(), def = defaultProfile(profiles);
  const sel = $('dlgProfile'); sel.innerHTML = '';
  profiles.forEach(p => { const o = document.createElement('option'); o.value = p.id; o.textContent = `${p.name} (${p.rooms.length})`; o.selected = p.id === def.id; sel.appendChild(o); });
  const name = await ask('New inspection', '12 Baker Street', 'Create', { profile: profiles.length > 1 });
  if (!name) return;
  const prof = profiles.find(p => p.id === sel.value) || def;
  const insp = await DB.createInspection(name, prof.rooms.length ? prof.rooms : ['General']);
  openInsp(insp.id);
};

// ---------- settings: room profiles ----------
let editing = null;
function renderSettings() {
  show('settings');
  const box = $('profileList'); box.innerHTML = '';
  for (const p of loadProfiles()) {
    const b = document.createElement('button'); b.className = 'card';
    b.innerHTML = `${UI.gear}<div class="grow"><b></b><small>${p.rooms.length} room${p.rooms.length === 1 ? '' : 's'}${p.rooms.length ? ' · ' + p.rooms.slice(0, 4).join(', ') + (p.rooms.length > 4 ? '…' : '') : ''}</small></div>${p.isDefault ? '<span class="badge">default</span>' : ''}<span class="muted">&#8250;</span>`;
    b.querySelector('b').textContent = p.name;
    b.onclick = () => openProfile(p.id);
    box.appendChild(b);
  }
}
$('settingsBtn').onclick = renderSettings;
$('addProfile').onclick = async () => {
  const name = await ask('New profile', 'e.g. Flat handover', 'Create');
  if (!name) return;
  openProfile(addProfile(name).id);
};
function openProfile(id) {
  editing = loadProfiles().find(p => p.id === id); if (!editing) return renderSettings();
  show('profile');
  $('profileTitle').textContent = editing.name;
  $('profileName').value = editing.name;
  $('profileDefault').checked = !!editing.isDefault;
  $('profileDefault').disabled = !!editing.isDefault;
  $('newRoomName').value = '';
  renderProfileRooms();
}
function renderProfileRooms() {
  const box = $('profileRooms'); box.innerHTML = '';
  editing.rooms.forEach((r, i) => {
    const row = document.createElement('div'); row.className = 'roomrow';
    row.innerHTML = `${roomIcon(r)}<span></span><button class="mini up" aria-label="Move up">${UI.back}</button><button class="mini del" aria-label="Remove">${UI.close}</button>`;
    row.querySelector('span').textContent = r;
    const up = row.querySelector('.up'); up.style.transform = 'rotate(90deg)'; up.disabled = i === 0;
    up.onclick = () => { [editing.rooms[i - 1], editing.rooms[i]] = [editing.rooms[i], editing.rooms[i - 1]]; saveEditing(); };
    row.querySelector('.del').onclick = () => { editing.rooms.splice(i, 1); saveEditing(); };
    box.appendChild(row);
  });
  if (!editing.rooms.length) box.innerHTML = '<p class="muted">No rooms yet. Add the areas you photograph on this kind of job.</p>';
}
function saveEditing() { updateProfile(editing); renderProfileRooms(); }
$('profileName').addEventListener('change', () => { const v = $('profileName').value.trim(); if (!v) return; editing.name = v; $('profileTitle').textContent = v; updateProfile(editing); });
$('profileDefault').addEventListener('change', () => { if ($('profileDefault').checked) { setDefault(editing.id); editing.isDefault = true; $('profileDefault').disabled = true; toast('Now the default profile'); } });
$('addRoomForm').addEventListener('submit', e => {
  e.preventDefault();
  const v = $('newRoomName').value.trim(); if (!v) return;
  if (editing.rooms.some(r => r.toLowerCase() === v.toLowerCase())) { toast('Already in the list'); return; }
  editing.rooms.push(v); $('newRoomName').value = ''; saveEditing();
});
$('delProfile').onclick = () => {
  if (!confirm(`Delete profile "${editing.name}"? Existing inspections are not affected.`)) return;
  deleteProfile(editing.id); renderSettings();
};

// ---------- rooms ----------
async function openInsp(id) {
  state.insp = await DB.getInspection(id);
  state.seq = {};
  renderRooms();
}
async function renderRooms() {
  show('rooms');
  const insp = state.insp;
  state.counts = await DB.countsFor(insp.id);
  const total = Object.values(state.counts).reduce((a, b) => a + b, 0);
  $('inspTitle').textContent = insp.name;
  $('inspMeta').textContent = `${total} photos · tap a room to shoot`;
  $('exportBtn').disabled = total === 0;
  $('driveBtn').disabled = total === 0;
  updateDriveStatus();
  const grid = $('roomGrid'); grid.innerHTML = '';
  for (const room of insp.rooms) {
    const n = state.counts[room] || 0;
    const b = document.createElement('button');
    b.className = 'room' + (room === insp.lastRoom ? ' last' : '');
    b.innerHTML = `${roomIcon(room)}<div><span></span><br><em>${n ? 'tap to add more' : 'no photos yet'}</em></div>${n ? `<div class="n">${n}</div>` : ''}`;
    b.querySelector('span').textContent = room;
    b.onclick = () => openCamera(room);
    grid.appendChild(b);
  }
  const add = document.createElement('button'); add.className = 'room add'; add.textContent = '+ Add room';
  add.onclick = async () => {
    const name = await ask('New room', 'Bedroom 3', 'Add');
    if (!name || insp.rooms.includes(name)) return;
    insp.rooms.push(name); await DB.saveInspection(insp); renderRooms();
  };
  grid.appendChild(add);
}
$('delInsp').onclick = async () => {
  if (!confirm(`Delete "${state.insp.name}" and all its photos from this phone?`)) return;
  await DB.deleteInspection(state.insp.id); state.insp = null; renderHome();
};

// ---------- Google Drive ----------
async function updateDriveStatus() {
  const photos = await DB.photosFor(state.insp.id);
  const left = photos.filter(p => !p.driveId).length;
  $('driveStatus').textContent = !photos.length ? '' : left === 0 ? 'All photos are in Google Drive'
    : `${left} photo${left === 1 ? '' : 's'} not uploaded yet` + (isConnected() ? '' : ' · tap to sign in');
  $('driveBtn').textContent = left === 0 && photos.length ? 'Google Drive is up to date' : 'Upload to Google Drive';
}
$('driveBtn').onclick = async () => {
  const d = $('dlgDrive'), bar = $('driveBar'), txt = $('driveText');
  bar.value = 0; txt.textContent = 'Signing in...'; d.showModal();
  try {
    const photos = await DB.photosFor(state.insp.id);
    const res = await syncInspection(state.insp, photos,
      (p, id) => DB.setPhotoDriveId(p, id),
      (done, total) => { bar.value = done / total * 100; txt.textContent = `Uploading ${done} / ${total}`; });
    d.close();
    toast(res.failed ? `Uploaded ${res.uploaded}, failed ${res.failed}. Tap again to retry.` : res.uploaded ? `Uploaded ${res.uploaded} photos to Drive` : 'Nothing new to upload', 3500);
  } catch (e) { d.close(); toast('Drive: ' + e.message, 5000); console.error(e); }
  updateDriveStatus();
};

// ---------- export ----------
const dlgExp = $('dlgExport');
function expBusy(on, text) {
  $('expChoice').hidden = on; $('expBusy').hidden = !on;
  if (text) $('expText').textContent = text; $('expBar').value = 0;
}
let share = { batches: [], i: 0 };
function updateShareBtn() {
  const b = $('expShare'), n = share.batches.length;
  if (!canShareFiles()) { b.disabled = true; b.textContent = 'Share photos (not supported here)'; return; }
  b.disabled = false;
  if (n <= 1) { b.textContent = 'Share photos'; return; }
  b.innerHTML = `Share batch ${share.i + 1} of ${n}<br><small style="font-weight:500">${batchLabel(share.batches[share.i])}</small>`;
  $('expShareNote').textContent = `Android lets a page share up to 10 photos at a time, so ${share.batches.length} batches. Pick the same Drive folder each time.`;
}
$('exportBtn').onclick = async () => {
  expBusy(true, 'Preparing photos...');
  dlgExp.showModal();
  const photos = await DB.photosFor(state.insp.id);   // load before the share tap so the tap itself stays a user gesture
  share = { batches: shareBatches(state.insp, photos), i: 0 };
  $('expShareNote').textContent = 'Send JPEGs to Google Drive or any app. Room name is in each filename, e.g. Kitchen_003.jpg.';
  updateShareBtn();
  expBusy(false);
};
$('expCancel').onclick = () => dlgExp.close();
$('expShare').onclick = () => {
  const files = share.batches[share.i]; if (!files) return;
  shareFiles(files, folderName(state.insp)).then(how => {
    if (how !== 'shared') return;
    share.i++;
    if (share.i >= share.batches.length) { dlgExp.close(); toast('All photos sent'); }
    else { updateShareBtn(); toast(`Sent ${share.i} of ${share.batches.length}`); }
  }).catch(e => { toast('Share failed: ' + e.message, 4000); console.error(e); });
};
$('expZip').onclick = async () => {
  expBusy(true, 'Packing photos into folders...');
  try {
    const photos = await DB.photosFor(state.insp.id);
    const file = await buildZip(state.insp, photos, p => { $('expBar').value = p; });
    dlgExp.close();
    download(file);
    toast(`Saved to Downloads (${(file.size / 1048576).toFixed(1)} MB)`, 3000);
  } catch (e) { dlgExp.close(); toast('Export failed: ' + e.message, 4000); console.error(e); }
};

// ---------- camera ----------
async function openCamera(room) {
  state.room = room;
  state.insp.lastRoom = room; DB.saveInspection(state.insp);
  show('cam');
  updateCamUI();
  $('camHint').hidden = true; $('camInfo').textContent = '';
  try {
    await cam.start(localStorage.getItem('lens') || null);
    $('camInfo').textContent = cam.info();
    const devs = await cam.devices();
    $('lensBtn').hidden = devs.length < 2;
    await setupZoom();
  } catch (e) { $('camHint').hidden = false; $('camHint').textContent = 'Camera unavailable: ' + e.message; }
}
// ---------- zoom presets ----------
async function setupZoom() {
  const row = $('zoomRow'); row.innerHTML = '';
  const r = cam.zoomRange();
  if (!r) { row.hidden = true; return; }
  const presets = [];
  if (r.min < 1) presets.push(+r.min.toFixed(1));
  presets.push(1);
  [2, 3, 5].forEach(v => { if (v <= r.max && v > 1) presets.push(v); });
  if (presets.length < 2) { row.hidden = true; return; }
  const saved = parseFloat(localStorage.getItem('zoom'));
  if (saved && saved >= r.min && saved <= r.max) { try { await cam.setZoom(saved); } catch (_) {} }
  const paint = () => { const z = cam.zoom(); row.querySelectorAll('button').forEach(b => b.classList.toggle('on', Math.abs(+b.dataset.z - z) < 0.05)); };
  presets.forEach(v => {
    const b = document.createElement('button'); b.textContent = `${v}×`; b.dataset.z = v;
    b.onclick = async () => { try { await cam.setZoom(v); localStorage.setItem('zoom', v); $('camInfo').textContent = cam.info(); } catch (e) { toast('Zoom failed: ' + e.message, 2000); } paint(); };
    row.appendChild(b);
  });
  row.hidden = false; paint();
}
// ---------- lens picker ----------
function lensLabel(d, i) {
  const l = (d.label || '').toLowerCase();
  const side = /front|user/.test(l) ? 'Front' : /back|rear|environment/.test(l) ? 'Back' : '';
  return `Camera ${i + 1}${side ? ' · ' + side : ''}`;
}
$('lensBtn').onclick = async () => {
  const devs = await cam.devices(), cur = cam.currentId();
  const box = $('lensList'); box.innerHTML = '';
  devs.forEach((d, i) => {
    const b = document.createElement('button'); b.className = 'card';
    b.innerHTML = `${UI.lens}<div class="grow"><b></b><small></small></div>${d.deviceId === cur ? UI.check : ''}`;
    b.querySelector('b').textContent = lensLabel(d, i);
    b.querySelector('small').textContent = d.deviceId === cur ? cam.info() : (d.label || '');
    b.onclick = async () => {
      $('dlgLens').close();
      if (d.deviceId === cur) return;
      stopBurst(); cam.stop();
      try { await cam.start(d.deviceId); localStorage.setItem('lens', d.deviceId); $('camInfo').textContent = cam.info(); toast(lensLabel(d, i), 1200); await setupZoom(); }
      catch (e) { toast('Cannot open this camera: ' + e.message, 3000); localStorage.removeItem('lens'); await cam.start().catch(() => {}); }
    };
    box.appendChild(b);
  });
  $('dlgLens').showModal();
};
$('lensCancel').onclick = () => $('dlgLens').close();
async function nextSeq(room) {
  if (state.seq[room] == null) state.seq[room] = await DB.nextSeq(state.insp.id, room);
  return state.seq[room]++;
}
function updateCamUI() {
  $('camRoom').textContent = state.room;
  $('camCount').textContent = state.counts[state.room] || 0;
  const strip = $('roomStrip'); strip.innerHTML = '';
  for (const r of state.insp.rooms) {
    const b = document.createElement('button'); b.innerHTML = roomIcon(r) + '<span></span>'; b.querySelector('span').textContent = r + (state.counts[r] ? ` · ${state.counts[r]}` : '');
    b.className = r === state.room ? 'on' : '';
    b.onclick = () => switchRoom(r);
    strip.appendChild(b);
    if (r === state.room) requestAnimationFrame(() => b.scrollIntoView({ inline: 'center', block: 'nearest' }));
  }
}
function switchRoom(r) {
  state.room = r; state.insp.lastRoom = r; DB.saveInspection(state.insp);
  updateCamUI(); toast(r, 900);
}
// Shutter: grab the frame now (fast), encode + save in the background.
async function shoot() {
  if (grabbing || !cam.stream || !cam.video.videoWidth) return;
  if (pending.size >= MAX_PENDING) { toast('Saving... hold on', 800); return; }
  grabbing = true;
  const insp = state.insp, room = state.room;
  try {
    const [bmp, seq] = await Promise.all([cam.grab(), nextSeq(room)]);
    grabbing = false;
    state.counts[room] = (state.counts[room] || 0) + 1;
    $('camCount').textContent = state.counts[room];
    $('thumb').src = cam.thumb(bmp);
    const f = $('flash'); f.classList.add('on'); requestAnimationFrame(() => setTimeout(() => f.classList.remove('on'), 40));
    if (navigator.vibrate) navigator.vibrate(15);
    const job = cam.encode(bmp).then(blob => DB.addPhoto(insp.id, room, seq, blob))
      .catch(e => { toast('Save failed: ' + e.message, 3000); console.error(e); })
      .finally(() => { pending.delete(job); $('camCount').classList.toggle('busy', pending.size > 0); });
    pending.add(job); $('camCount').classList.add('busy');
  } catch (e) { grabbing = false; toast('Shot failed: ' + e.message, 3000); console.error(e); }
}
// tap = one shot; hold = burst
const sh = $('shutter');
const BURST_MS = 250;
sh.addEventListener('pointerdown', e => {
  e.preventDefault(); sh.classList.add('firing');
  shoot();
  burstTimer = setInterval(shoot, BURST_MS);
});
const stopBurst = () => { sh.classList.remove('firing'); clearInterval(burstTimer); burstTimer = null; };
['pointerup', 'pointercancel', 'pointerleave'].forEach(ev => sh.addEventListener(ev, stopBurst));
sh.addEventListener('contextmenu', e => e.preventDefault());

// leaving camera: wait for background saves so the rooms screen shows true counts
document.querySelector('#cam [data-nav]').addEventListener('click', async () => {
  stopBurst();
  if (pending.size) { toast('Saving photos...', 1500); await Promise.all([...pending]); }
  renderRooms();
}, { capture: true });
document.addEventListener('visibilitychange', () => { if (document.hidden) { stopBurst(); cam.stop(); } else if ($('cam').classList.contains('active')) cam.start(localStorage.getItem('lens') || null).catch(() => {}); });
window.addEventListener('beforeunload', e => { if (pending.size) { e.preventDefault(); e.returnValue = ''; } });

// ---------- boot ----------
if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});
$('brandMark').innerHTML = PARROT_SVG;
document.querySelectorAll('[data-nav]').forEach(b => { b.innerHTML = UI.back; });
$('delInsp').innerHTML = UI.trash; $('delProfile').innerHTML = UI.trash;
$('settingsBtn').innerHTML = UI.gear; $('lensBtn').innerHTML = UI.lens; $('addRoomForm').querySelector('button').innerHTML = UI.plus;
renderHome();
