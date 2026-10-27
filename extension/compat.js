// Firefox exposes extension APIs as `browser` (promises); Chromium browsers as `chrome`.
// Everything here uses the promise forms, which both support in Manifest V3.
var api = globalThis.browser || globalThis.chrome;
