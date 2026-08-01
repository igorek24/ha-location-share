"""Public, token-authenticated views for shared locations.

Two endpoints, both unauthenticated by design - the token in the URL *is*
the credential, exactly like Apple's or Google's share links:

    /api/location_share/<token>        a self-contained live map page
    /api/location_share/<token>/data   JSON the page polls

Every request validates the token and its expiry, and unknown or expired
tokens get an identical 404 so a link cannot be probed for validity.
"""

from __future__ import annotations

import logging
import math
import random
from typing import Any

from aiohttp import web
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .share_manager import PRECISION_APPROXIMATE, ShareManager

_LOGGER = logging.getLogger(__name__)

APPROXIMATE_METERS = 500
GONE_HTML = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Location link</title><style>
body{font-family:system-ui,-apple-system,sans-serif;background:#0f172a;color:#e2e8f0;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;text-align:center}
div{max-width:22rem;padding:2rem}h1{font-size:1.25rem;margin:0 0 .5rem}
p{color:#94a3b8;margin:0;line-height:1.5}</style></head>
<body><div><h1>This link is no longer active</h1>
<p>The location share has expired or was revoked.</p></div></body></html>"""


def _blur(latitude: float, longitude: float, token: str) -> tuple[float, float]:
    """Offset a position by a stable pseudo-random amount (~500 m)."""
    rng = random.Random(token)            # stable per share, not per request
    angle = rng.uniform(0, 2 * math.pi)
    radius = APPROXIMATE_METERS * (0.5 + rng.random() / 2)
    d_lat = radius / 111_320
    d_lon = radius / (111_320 * max(0.1, abs(math.cos(math.radians(latitude)))))
    return (
        round(latitude + d_lat * math.sin(angle), 6),
        round(longitude + d_lon * math.cos(angle), 6),
    )


class LocationShareDataView(HomeAssistantView):
    """JSON position for a share token."""

    url = "/api/location_share/{token}/data"
    name = "api:location_share:data"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, manager: ShareManager) -> None:
        self._hass = hass
        self._manager = manager

    async def get(self, request: web.Request, token: str) -> web.Response:
        share = self._manager.get(token)
        if share is None:
            return web.json_response({"error": "not_found"}, status=404)

        state = self._hass.states.get(share.entity_id)
        if state is None:
            return web.json_response({"error": "unavailable"}, status=404)

        latitude = state.attributes.get("latitude")
        longitude = state.attributes.get("longitude")
        if latitude is None or longitude is None:
            return web.json_response(
                {"error": "no_position", "label": share.label}, status=200
            )

        if share.precision == PRECISION_APPROXIMATE:
            latitude, longitude = _blur(latitude, longitude, token)
            accuracy = APPROXIMATE_METERS
        else:
            accuracy = state.attributes.get("gps_accuracy")

        data: dict[str, Any] = {
            "label": share.label,
            "latitude": latitude,
            "longitude": longitude,
            "accuracy": accuracy,
            "updated": state.last_changed.isoformat(),
            "expires_in": share.seconds_remaining,
            "precision": share.precision,
        }
        runtime = self._hass.data.get(DOMAIN, {})
        extra = runtime.get("live", {}).get(share.entity_id, {})
        for key in ("eta_seconds", "eta_text", "distance_home_m", "speed_kmh", "battery"):
            if extra.get(key) is not None:
                data[key] = extra[key]

        await self._manager.async_record_view(token)
        return web.json_response(data, headers={"Cache-Control": "no-store"})


class LocationSharePageView(HomeAssistantView):
    """The map page itself."""

    url = "/api/location_share/{token}"
    name = "api:location_share:page"
    requires_auth = False

    def __init__(self, hass: HomeAssistant, manager: ShareManager) -> None:
        self._hass = hass
        self._manager = manager

    async def get(self, request: web.Request, token: str) -> web.Response:
        share = self._manager.get(token)
        if share is None:
            return web.Response(text=GONE_HTML, content_type="text/html", status=404)
        return web.Response(
            text=_PAGE.replace("__TOKEN__", token).replace("__LABEL__", share.label),
            content_type="text/html",
            headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
        )


_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex,nofollow">
<title>__LABEL__ &middot; live location</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
  :root{color-scheme:dark}
  *{box-sizing:border-box}
  body{margin:0;font-family:system-ui,-apple-system,"Segoe UI",sans-serif;background:#0f172a;color:#e2e8f0}
  #map{position:fixed;inset:0}
  .panel{position:fixed;left:0;right:0;bottom:0;z-index:1000;padding:1rem 1.1rem calc(1rem + env(safe-area-inset-bottom));
    background:rgba(15,23,42,.92);backdrop-filter:blur(10px);border-top:1px solid rgba(148,163,184,.25)}
  .row{display:flex;align-items:baseline;gap:.6rem;flex-wrap:wrap}
  h1{font-size:1.05rem;margin:0;font-weight:600}
  .eta{font-size:1.05rem;font-weight:600;color:#38bdf8}
  .meta{margin:.35rem 0 0;font-size:.82rem;color:#94a3b8;line-height:1.45}
  .dot{display:inline-block;width:.5rem;height:.5rem;border-radius:50%;background:#22c55e;margin-right:.35rem;
    vertical-align:middle;animation:pulse 2s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.35}}
  .stale .dot{background:#f59e0b;animation:none}
  .leaflet-container{background:#0f172a}
</style></head>
<body>
<div id="map"></div>
<div class="panel" id="panel">
  <div class="row"><h1 id="who">__LABEL__</h1><span class="eta" id="eta"></span></div>
  <p class="meta"><span class="dot"></span><span id="status">Locating&hellip;</span></p>
  <p class="meta" id="expiry"></p>
</div>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
const TOKEN = "__TOKEN__";
const map = L.map('map', {zoomControl:false}).setView([0,0], 3);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
  {maxZoom:19, attribution:'&copy; OpenStreetMap'}).addTo(map);
L.control.zoom({position:'topright'}).addTo(map);

let marker, circle, first = true;

function ago(iso){
  const secs = Math.max(0, (Date.now() - new Date(iso).getTime())/1000);
  if (secs < 60) return "just now";
  if (secs < 3600) return Math.round(secs/60) + " min ago";
  return Math.round(secs/3600) + " h ago";
}
function human(secs){
  if (secs < 60) return "under a minute";
  const m = Math.round(secs/60);
  if (m < 60) return m + " min";
  const h = Math.floor(m/60), r = m%60;
  return r ? h+" h "+r+" min" : h+" h";
}

async function tick(){
  try{
    const res = await fetch(`/api/location_share/${TOKEN}/data`, {cache:'no-store'});
    if(!res.ok){
      document.getElementById('status').textContent =
        res.status === 404 ? "This link is no longer active." : "Location unavailable.";
      document.getElementById('panel').classList.add('stale');
      return;
    }
    const d = await res.json();
    if(d.error === "no_position"){
      document.getElementById('status').textContent = "Waiting for a position fix\\u2026";
      return;
    }
    const pos = [d.latitude, d.longitude];
    if(!marker){
      marker = L.marker(pos).addTo(map);
      circle = L.circle(pos, {radius: d.accuracy || 0, color:'#38bdf8',
                              fillColor:'#38bdf8', fillOpacity:.12, weight:1}).addTo(map);
    } else {
      marker.setLatLng(pos);
      circle.setLatLng(pos).setRadius(d.accuracy || 0);
    }
    if(first){ map.setView(pos, 15); first = false; }

    document.getElementById('who').textContent = d.label;
    document.getElementById('eta').textContent = d.eta_text ? ("~" + d.eta_text + " away") : "";
    const bits = ["Updated " + ago(d.updated)];
    if(d.speed_kmh != null && d.speed_kmh > 2) bits.push(Math.round(d.speed_kmh) + " km/h");
    if(d.battery != null) bits.push("battery " + d.battery + "%");
    if(d.precision === "approximate") bits.push("approximate location");
    document.getElementById('status').textContent = bits.join(" \\u00b7 ");
    document.getElementById('expiry').textContent =
      "This link expires in " + human(d.expires_in) + ".";
    document.getElementById('panel').classList.toggle('stale',
      (Date.now() - new Date(d.updated).getTime()) > 10*60*1000);
  }catch(e){
    document.getElementById('status').textContent = "Connection problem\\u2026";
  }
}
tick(); setInterval(tick, 15000);
</script>
</body></html>"""
