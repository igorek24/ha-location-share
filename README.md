# Location Share

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=igorek24&repository=ha-location-share&category=integration)
[![Open your Home Assistant instance and start setting up a new integration.](https://my.home-assistant.io/badges/config_flow_start.svg)](https://my.home-assistant.io/redirect/config_flow_start/?domain=location_share)

[![GitHub release](https://img.shields.io/github/v/release/igorek24/ha-location-share?style=flat-square)](https://github.com/igorek24/ha-location-share/releases)
[![License](https://img.shields.io/github/license/igorek24/ha-location-share?style=flat-square)](LICENSE)
[![hacs](https://img.shields.io/badge/HACS-custom-41BDF5.svg?style=flat-square)](https://hacs.xyz)

**Find My style location sharing for Home Assistant.** See where everyone
is, get arrival and departure alerts, know when someone will be home — and
send a *temporary, revocable link* so people without Home Assistant can
follow your live location, exactly like Apple's "Share My Location".

Everything runs on your own Home Assistant. Locations are never sent to a
third-party service, and the only thing that leaves your network is a link
you deliberately create.

## Features

- **Live family map** — the companion app already reports position; this
  adds distance home, ETA home, speed and heading per person
- **Temporary share links** — a tokenised, auto-expiring public page with a
  live map, ETA and battery. Revocable at any moment
- **Approximate mode** — share a neighbourhood (~500 m fuzz) instead of an
  exact address
- **"On my way"** — one service call announces the ETA to the family and
  attaches a link that expires shortly after you arrive
- **Arrival & departure alerts** — blueprint with quiet hours
- No cloud, no external dependencies, no `requirements`

## How the ETA works

There is no routing service involved. The integration watches successive
GPS fixes, derives a smoothed speed and heading (discarding jitter and
implausible jumps), and divides the remaining straight-line distance by
that speed. That makes it self-contained and instant, but it is a
*straight-line* estimate — fine for "about 10 minutes away", not for
turn-by-turn accuracy. If you want road-accurate numbers, add a
`waze_travel_time` or `google_travel_time` sensor and use that instead;
this integration's `distance_home` and share links work happily alongside.

When someone is stationary, the ETA is `unknown` rather than a made-up
number.

## Installation

### HACS

**Easiest:** click the blue *My Home Assistant* badge at the top of this page — it opens your own Home Assistant and pre-fills this repository as a HACS custom repository. Then Download and restart.

Manually: HACS → ⋮ → **Custom repositories** → `https://github.com/igorek24/ha-location-share`,
type **Integration** → Download → restart Home Assistant.

### Manual

Copy `custom_components/location_share` into `config/custom_components/`
and restart.

## Configuration

Settings → Devices & Services → **Add Integration** → **Location Share**.

| Setting | Meaning |
|---|---|
| People / device trackers | Who gets distance and ETA sensors |
| Public base URL | Used to build share links — must be reachable by whoever you send them to (e.g. `https://ha.example.com`) |
| Home zone | Where "home" is for distance and ETA |
| Default share duration | How long new links last |
| Fallback speed | Used for ETA before enough movement data exists |

## Entities

Per tracked person:

| Entity | Notes |
|---|---|
| `sensor.<person>_distance_home` | km, with `zone`, `speed_kmh`, `heading` attributes |
| `sensor.<person>_eta_home` | minutes, with `eta_text`, `distance_km`, `moving` |

Plus `sensor.location_share_active_shares` — the number of live links, with
every share listed in attributes (label, expiry, views, precision).

## Services

### `location_share.create_share`

Returns the URL in the service response.

```yaml
action: location_share.create_share
data:
  entity_id: person.igor
  minutes: 60
  label: "Igor"
  precision: exact          # or: approximate (~500 m fuzz)
  notify_target: mobile_app_igor   # optional: send yourself the link
response_variable: share
```

### `location_share.on_my_way`

```yaml
action: location_share.on_my_way
data:
  entity_id: person.igor
  notify_target: family
  include_link: true        # link expires at ETA + 15 min
```

Sends something like *"Igor is on the way home, about 12 min away.
https://ha.example.com/api/location_share/…"*

### `location_share.revoke_share` / `revoke_all_shares`

Revoke by `token`, by `entity_id`, or everything at once. A revoked link
returns 404 immediately.

## Arrival & departure alerts

Import `blueprints/arrival_departure.yaml` (Settings → Automations →
Blueprints → Import Blueprint), then create one automation per person:
pick the person, the zone, a notify service, and optionally quiet hours.

## Dashboard

A ready-made family view is in [docs/dashboard.yaml](docs/dashboard.yaml):
a live map, per-person distance/ETA rows, active share links with a
one-tap "revoke all", and an "on my way home" button.

## Security and privacy

This is location data, so the design is deliberately conservative:

- Share links carry a **256-bit random token** (`secrets.token_urlsafe(32)`).
  The token *is* the credential — anyone with the link sees the location,
  so treat it like a password.
- **Every share expires.** Expiry is enforced on every request, and expired
  shares are purged from storage.
- **Revocation is immediate** — no cached pages, `Cache-Control: no-store`.
- Unknown and expired tokens return an **identical 404**, so links cannot be
  probed for validity.
- The page sets `noindex, nofollow` and `Referrer-Policy: no-referrer`.
- Views are counted; `sensor.location_share_active_shares` shows how many
  times each link was opened and when it was last viewed.
- **Approximate mode** offsets the position by a stable ~500 m so the same
  link doesn't jitter around while still hiding the exact address.

The share endpoints are intentionally unauthenticated — that is what makes
them shareable with people who have no Home Assistant account. They are
only reachable if your Home Assistant is reachable. The map page loads
Leaflet and OpenStreetMap tiles from public CDNs, so viewers' browsers
contact those services (Home Assistant itself does not).

## Development

```bash
python3 tests/test_locator.py      # distance / speed / ETA maths
python3 tests/test_shares.py       # token lifecycle, expiry, revocation
```

Both suites are plain Python with no Home Assistant needed.

## Trademarks

Unaffiliated with Apple. "Find My" and "Share My Location" are Apple
trademarks, referenced only to describe the kind of feature this provides.
