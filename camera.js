// Camera: rear camera stream. Capture = instant frame grab from the preview stream,
// JPEG encoding happens afterwards off the critical path (see encode()).
// ImageCapture.takePhoto() was tried first: it reconfigures the pipeline per shot (~0.7 s on Xiaomi 14 Ultra), too slow for burst.
export class Camera {
  constructor(video) { this.video = video; this.stream = null; this.track = null; }
  // deviceId: a specific camera (from devices()); null = default rear camera.
  async start(deviceId = null) {
    if (this.stream) return;
    const hi = { width: { ideal: 4096 }, height: { ideal: 3072 } };
    const tries = [
      ...(deviceId ? [{ deviceId: { exact: deviceId }, ...hi }, { deviceId: { exact: deviceId } }] : []),
      { facingMode: { ideal: 'environment' }, ...hi },
      { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
      true,
    ];
    let err;
    for (const video of tries) {
      try { this.stream = await navigator.mediaDevices.getUserMedia({ audio: false, video }); break; }
      catch (e) { err = e; }
    }
    if (!this.stream) throw err;
    this.video.srcObject = this.stream;
    await this.video.play();
    this.track = this.stream.getVideoTracks()[0];
  }
  stop() {
    if (this.stream) this.stream.getTracks().forEach(t => t.stop());
    this.stream = this.track = null;
    this.video.srcObject = null;
  }
  // Video inputs. Labels are only available after camera permission was granted once.
  async devices() {
    const all = await navigator.mediaDevices.enumerateDevices();
    return all.filter(d => d.kind === 'videoinput');
  }
  currentId() { return this.track ? this.track.getSettings().deviceId : null; }
  info() {
    if (!this.track) return '';
    const s = this.track.getSettings();
    return `${s.width}x${s.height} · ${this.track.label || 'camera'}`;
  }
  // Fast: copies the current preview frame (tens of ms).
  grab() { return createImageBitmap(this.video); }
  // Slow part, run after the shutter feedback: JPEG-encode a grabbed frame.
  // Uses a Web Worker when possible so bursts are not blocked by encoding.
  encode(bmp, quality = 0.9) {
    if ('OffscreenCanvas' in window && typeof Worker === 'function') {
      if (!this.worker) {
        this.worker = new Worker('encoder-worker.js');
        this.jobs = new Map(); this.jobId = 0;
        this.worker.onmessage = e => {
          const j = this.jobs.get(e.data.id); if (!j) return;
          this.jobs.delete(e.data.id);
          e.data.error ? j.reject(new Error(e.data.error)) : j.resolve(e.data.blob);
        };
        this.worker.onerror = () => { this.worker = null; }; // next call falls back to main thread
      }
      if (this.worker) return new Promise((resolve, reject) => {
        const id = ++this.jobId; this.jobs.set(id, { resolve, reject });
        this.worker.postMessage({ id, bmp, quality }, [bmp]);
      });
    }
    return this.encodeMain(bmp, quality);
  }
  async encodeMain(bmp, quality) {
    try {
      if ('OffscreenCanvas' in window) {
        const c = new OffscreenCanvas(bmp.width, bmp.height);
        c.getContext('2d').drawImage(bmp, 0, 0);
        return await c.convertToBlob({ type: 'image/jpeg', quality });
      }
      const c = document.createElement('canvas');
      c.width = bmp.width; c.height = bmp.height;
      c.getContext('2d').drawImage(bmp, 0, 0);
      return await new Promise(res => c.toBlob(res, 'image/jpeg', quality));
    } finally { bmp.close && bmp.close(); }
  }
  // Small preview for the thumbnail, synchronous and cheap.
  thumb(bmp, size = 112) {
    const c = document.createElement('canvas'); c.width = c.height = size;
    const s = Math.min(bmp.width, bmp.height), sx = (bmp.width - s) / 2, sy = (bmp.height - s) / 2;
    c.getContext('2d').drawImage(bmp, sx, sy, s, s, 0, 0, size, size);
    return c.toDataURL('image/jpeg', 0.7);
  }
}
