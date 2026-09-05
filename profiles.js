// Room profiles: named room lists, chosen when a new inspection is created. Stored in localStorage.
import { DEFAULT_ROOMS } from './db.js';
const KEY = 'inspectsnap.profiles';
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 6);

function seed() {
  return [{ id: 'default', name: 'Property inspection', rooms: [...DEFAULT_ROOMS], isDefault: true }];
}
export function loadProfiles() {
  try { const p = JSON.parse(localStorage.getItem(KEY)); if (Array.isArray(p) && p.length) return p; } catch (_) {}
  const s = seed(); saveProfiles(s); return s;
}
export function saveProfiles(list) { localStorage.setItem(KEY, JSON.stringify(list)); }
export function defaultProfile(list = loadProfiles()) { return list.find(p => p.isDefault) || list[0]; }
export function addProfile(name) {
  const list = loadProfiles();
  const p = { id: uid(), name: name.trim(), rooms: [], isDefault: false };
  list.push(p); saveProfiles(list); return p;
}
export function updateProfile(p) {
  const list = loadProfiles().map(x => x.id === p.id ? p : x);
  saveProfiles(list);
}
export function setDefault(id) {
  saveProfiles(loadProfiles().map(x => ({ ...x, isDefault: x.id === id })));
}
export function deleteProfile(id) {
  let list = loadProfiles().filter(x => x.id !== id);
  if (!list.length) list = seed();
  if (!list.some(x => x.isDefault)) list[0].isDefault = true;
  saveProfiles(list);
}
