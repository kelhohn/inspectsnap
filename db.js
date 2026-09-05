// IndexedDB wrapper: inspections + photos
const DB_NAME = 'inspectsnap', DB_VER = 1;
let dbp;
function openDB() {
  if (dbp) return dbp;
  dbp = new Promise((res, rej) => {
    const r = indexedDB.open(DB_NAME, DB_VER);
    r.onupgradeneeded = () => {
      const db = r.result;
      db.createObjectStore('inspections', { keyPath: 'id' });
      const p = db.createObjectStore('photos', { keyPath: 'id' });
      p.createIndex('byInsp', 'inspId');
      p.createIndex('byRoom', ['inspId', 'room']);
    };
    r.onsuccess = () => res(r.result);
    r.onerror = () => rej(r.error);
  });
  return dbp;
}
function tx(store, mode, fn) {
  return openDB().then(db => new Promise((res, rej) => {
    const t = db.transaction(store, mode);
    const out = fn(t.objectStore(store));
    t.oncomplete = () => res(out && out.result !== undefined ? out.result : out);
    t.onerror = () => rej(t.error);
    t.onabort = () => rej(t.error);
  }));
}
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);

export const DEFAULT_ROOMS = ['External', 'Hallway', 'Kitchen', 'Living Room', 'Bedroom 1', 'Bedroom 2', 'Bathroom'];

export const DB = {
  async listInspections() {
    const all = await tx('inspections', 'readonly', s => s.getAll());
    return all.sort((a, b) => b.created - a.created);
  },
  getInspection(id) { return tx('inspections', 'readonly', s => s.get(id)); },
  createInspection(name, rooms = DEFAULT_ROOMS) {
    const insp = { id: uid(), name: name.trim(), created: Date.now(), rooms: [...rooms], lastRoom: null };
    return tx('inspections', 'readwrite', s => s.put(insp)).then(() => insp);
  },
  saveInspection(insp) { return tx('inspections', 'readwrite', s => s.put(insp)); },
  async deleteInspection(id) {
    const photos = await this.photosFor(id);
    await tx('photos', 'readwrite', s => { photos.forEach(p => s.delete(p.id)); });
    await tx('inspections', 'readwrite', s => s.delete(id));
  },
  photosFor(inspId) {
    return tx('photos', 'readonly', s => s.index('byInsp').getAll(inspId));
  },
  async countsFor(inspId) {
    const photos = await this.photosFor(inspId);
    const c = {};
    photos.forEach(p => { c[p.room] = (c[p.room] || 0) + 1; });
    return c;
  },
  async nextSeq(inspId, room) {
    const ph = await tx('photos', 'readonly', s => s.index('byRoom').getAll([inspId, room]));
    return ph.reduce((m, p) => Math.max(m, p.seq), 0) + 1;
  },
  addPhoto(inspId, room, seq, blob) {
    const photo = { id: uid(), inspId, room, seq, blob, ts: Date.now() };
    return tx('photos', 'readwrite', s => s.put(photo)).then(() => photo);
  },
  deletePhoto(id) { return tx('photos', 'readwrite', s => s.delete(id)); },
  setPhotoDriveId(photo, driveId) { photo.driveId = driveId; return tx('photos', 'readwrite', s => s.put(photo)); },
};
