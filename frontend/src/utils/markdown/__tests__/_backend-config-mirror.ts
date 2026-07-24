// Mirror of backend/app/services/markdown_config.py — exposes the JSON shape
// of `MARKDOWN_IT_OPTIONS` for cross-package regression tests. Any change to
// `frontend/src/utils/markdown/config.ts` MUST be reflected here so the
// backend drift test fails on CI.
export const BACKEND_MARKDOWN_IT_OPTIONS = {
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
}
