// Thin wrapper so callers don't each need their own feature-detection/try-catch
// around the Clipboard API (unavailable outside secure contexts - http:// on
// anything but localhost, older browsers, etc.).
export async function copyToClipboard(text) {
  if (!navigator.clipboard) {
    throw new Error('Clipboard access is unavailable in this browser/context');
  }
  await navigator.clipboard.writeText(text);
}
