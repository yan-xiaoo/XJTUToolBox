# Vendored Siyuan downloader

Source: https://github.com/XLJFZ/xjtu-siyuanxuetang-grab

Pinned commit: `6efee00247a6203a9056759dfab4da6b18e75b20` (MIT; see LICENSE).
Copied from `scripts/lms_fetch.py`, `scripts/lms_live.py`, and `scripts/lms_organize.py`.
The desktop adapter calls their collection, identity/path assignment, chapter
organization, upload download, replay resolution and stability verification
functions. It does not run the standalone CLI or read its login-state files.

Local modifications:

- Relative imports and a minimal `lms_common.py` configuration shim.
- Upload downloads accept small nonempty files and require exact known sizes.
- Upload partial files use a persisted ETag/Last-Modified validator with
  If-Range; unidentifiable partials restart rather than mix object versions.
- The adapter supplies cancellation, scoped in-memory session cookies,
  per-account/course destinations, path guards, serial execution, a preview
  dialog, manifests, and replay partial validators. Replay code is unchanged.

Keep this notice and LICENSE when updating or redistributing the vendored code.
Compare against the pinned commit before refreshing; do not overwrite the
desktop changes without rerunning `test.app.test_lms_archive`.
