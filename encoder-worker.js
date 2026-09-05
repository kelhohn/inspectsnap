// JPEG encoder off the main thread. Receives an ImageBitmap (transferred), returns a Blob.
self.onmessage = async e => {
  const { id, bmp, quality } = e.data;
  try {
    const c = new OffscreenCanvas(bmp.width, bmp.height);
    c.getContext('2d').drawImage(bmp, 0, 0);
    bmp.close();
    const blob = await c.convertToBlob({ type: 'image/jpeg', quality });
    self.postMessage({ id, blob });
  } catch (err) {
    self.postMessage({ id, error: err.message || String(err) });
  }
};
