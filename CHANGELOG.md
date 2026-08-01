# Changelog

## 0.1.0 — 2026-08-01

Initial release.

- Temporary, revocable public share links with a live map page
  (token-authenticated, auto-expiring, view-counted)
- Approximate precision mode (~500 m offset) for coarse sharing
- Per-person distance home, ETA home, speed and heading sensors
- `on_my_way` service: announces ETA and attaches a link that expires
  shortly after arrival
- Arrival/departure blueprint with quiet hours, and a family dashboard
- No external dependencies; all maths and storage are local
