# Terraavani AI — Complete Project Memory

> Hand this file to any AI agent (or teammate) and it can continue the project instantly.

## What This Project Is

**Terraavani AI** — a resilient, AI-powered environmental monitoring network for
**Smart India Hackathon PS 26178** (Qualcomm Inc · Disaster Management · Hardware).

Core pitch: "One cheap sensor node, every hazard." Distributed solar-powered ESP32
nodes with ON-DEVICE edge AI that sense (water level, rain, soil moisture, tilt,
temperature, humidity, smoke/air quality), think locally (anomaly detection without
cloud), and transmit only critical alerts — plus a cloud dashboard fusing real
regional data (Open-Meteo flood/air-quality, NASA FIRMS) into GIS risk maps and
prioritized warnings.

## History / Inheritance

This team previously built **Landsafe AI** (landslide early warning for NER):
- Repo: https://github.com/Alricvp/landsafe-ai (kept as portfolio piece, still live)
- Live: https://landsafe-ai.onrender.com
- Still works: ESP32+MPU-6500+moisture+OLED firmware (median filter, auto-calibration),
  FastAPI+WebSocket backend on Render, single-file PWA dashboard (GIS map, stations,
  alerts, incident, citizen photo reporting, history, 5 languages, siren + vibration +
  browser notifications, offline PWA), Open-Meteo real data risk model.
- Landsafe was for MDoNER PS (AI landslide detection NER). Team could not register that
  PS due to a registration fumble, so the team pivoted to PS 26178 which explicitly lists
  landslide precursors among hazards — nothing built is wasted.

## Current Status (updated Sep 27, 2026, evening)

- CODE-READY MVP. Working tree (all committed locally, NO remote yet):
  - backend/server.py — Landsafe FastAPI port, rebranded Terraavani AI v1.0.0,
    + NEW /api/hazards endpoint (10 NE cities: flood via Open-Meteo Flood API
    GloFAS river discharge, air quality via CAMS PM2.5/PM10/European-AQI,
    heat via tmax index; cached 10 min; batch-fetch works, verified live).
  - backend/dashboard.html — full PWA ported + rebranded TERRAAVANI AI
    (0 landsafe strings remain; storage keys terraavani-*; sw cache terraavani-v1).
  - backend/sw.js, manifest.json, historical.json, requirements.txt — ported+rebranded.
  - firmware/tilt_detector_oled/ — proven ESP32 node firmware (MPU-6500+moisture+OLED).
  - render.yaml — service name terraavani-ai, PYTHON_VERSION 3.11.0.
- User explicitly said: "make a repo with code ready so we can directly start
  working later" — so do NOT deploy/create Render until user asks.
- NEXT SESSION: (1) user creates empty GitHub repo `terraavani-ai` -> push,
  (2) optional: new Render workspace -> deploy -> test /api/hazards live,
  (3) then Phase 2 UI work: multi-hazard cards/tab in dashboard using /api/hazards,
  (4) Phase 3 edge-AI firmware, (5) hardware additions (HC-SR04/DHT22/MQ-135/solar).

## Key Decisions (do not re-litigate)

| Decision | Choice | Reason |
|---|---|---|
| Name | **Terraavani AI** | Unique (verified via search — zero tech hits); Terra (Latin) + Avani (Sanskrit: Earth) — "Earth watching over Earth"; renamed from working title TerraSentinel |
| Hosting | **Render, NEW workspace** | 750 free instance hours are PER WORKSPACE — new workspace = fresh hours; Vercel lacks WebSocket support; Railway/Glitch dead/paid |
| Repo strategy | Keep landsafe-ai frozen; new `terrasentinel-ai` repo | Two repos = portfolio progression; never delete landsafe-ai (Render depends on it) |
| AI on device | Edge AI is REQUIRED by PS (Qualcomm judges this hard) | Anomaly detection (z-score) + risk fusion on ESP32; transmit alerts only |
| Free data | Open-Meteo (rain/soil/flood/air-quality, no key), NASA FIRMS (fire, free key) | Real multi-hazard data at ₹0 |

## Target Architecture

```
TIER 1  Sensor nodes (₹1,800 BOM): ESP32 + MPU-6500 (tilt/vibration) + HC-SR04
        (water level) + capacitive moisture + DHT22 (temp/humidity) + MQ-135
        (smoke/AQ) + SSD1306 OLED + solar(6V panel + TP4056 + 18650) + IP65 box
TIER 2  Gateway nodes: ESP32 with WiFi — ESP-NOW/LoRa relay → cloud (range demo,
        no SIMs needed)
TIER 3  Cloud: FastAPI + WebSocket (port from Landsafe), multi-hazard fusion layer,
        risk engine with severity + confidence scores
TIER 4  Dashboard: single-file PWA (port + rebrand from Landsafe): GIS risk heatmap,
        stations, multi-hazard alerts, citizen reporting, 5 languages, siren/
        vibration/push notifications
```

## Hardware Additions vs Landsafe Node

| Sensor | Hazard | ~Price |
|---|---|---|
| HC-SR04 ultrasonic | Water level / flood | ₹60 |
| DHT22 (or BME280) | Temp + humidity / heat | ₹150 |
| MQ-135 | Smoke / air quality | ₹160 |
| Solar 6V 2W + TP4056 + 18650 | Untethered node | ₹330 |
| IP65 enclosure | Field deployment | ₹250 |

Total node BOM ≈ ₹1,800 (vs ₹3–20 lakh commercial station — the budget slide).

## Budget Story (judges ask — have it ready)

- Demo upgrade spend: ~₹1,050–1,200 (new sensors + spares + enclosure)
- One production node: ~₹1,800 (bulk at 100+: ₹1,300–1,500)
- Pilot (10 nodes + 2 gateways): ~₹40,000
- City pilot (50 nodes + 6 gateways): ~₹1.2 lakh
- NER state-wide (500 nodes): ~₹10–12 lakh
- Recurring: ₹0 SIMs (LoRa/ESP-NOW), hosting ₹0 now → ~₹3k/mo at state scale

## Existing Code Worth Copying (from landsafe-ai)

- `backend/server.py` — FastAPI skeleton: /api/tilt, /api/latest, /ws, /health,
  static serving of sw.js/manifest.json, Open-Meteo fetch pattern (cached ~10 min)
- `backend/dashboard.html` — whole PWA (tabs: Overview/GIS/Stations/Alerts/Incident/
  Report/History, language switcher, siren via Web Audio, vibration loop, service
  worker notifications with vibration pattern, perm modal with unblock help)
- `firmware/tilt_detector_oled/` — MPU driver + median-of-9 + 500-sample calibration
  + SSD1306 animated intro + WiFi + HTTP posting
- `backend/sw.js` / `manifest.json` — PWA offline + notification display

## Pitfalls Learned (do not repeat)

1. Free-tier OS push notifications ALWAYS need a one-time browser permission — design
   the branded modal + unblock-help flow (already built in Landsafe, port it).
2. `new Notification()` silently fails on Android Chrome — must use service-worker
   `showNotification()` (already built, port it).
3. Service worker caches old pages — bump cache version in sw.js every deploy that
   touches dashboard/sw.js.
4. Android "desktop-mode" zoom-out happens if ANYTHING overflows horizontally — test
   header on 360px width.
5. Render free tier sleeps after 15 min idle — set up UptimeRobot before demo day.
6. Chrome swallows permission prompts not tied to a fresh user gesture — use the modal
   button as the trigger.
7. Median filter + dead-zone + auto-calibration were what finally fixed the jumpy
   tilt readings — never remove them.
8. `.gitignore` personal images, PDFs, PROJECT_MEMORY.md (this file) — repo must look
   professional to judges.

## Standing Rules

1. **Never add AI co-author trailers to commits** — no "Co-Authored-By" lines.
   Commit as the user's git identity only (Alricvp). AI-attributed commits can
   cause hackathon disqualification.
2. Never delete/rename the landsafe-ai repo (Render deployment depends on it).
3. Bump sw.js cache version on every dashboard/service-worker deploy.
4. Repo must stay judge-clean: no personal images, PDFs, or internal notes tracked.

## Phase Plan

- [x] Phase 0 — Foundation (this repo skeleton + memory file)
- [ ] Phase 1 — Backend: copy FastAPI skeleton; add Open-Meteo Flood API + Air
      Quality API + NASA FIRMS fire data endpoints
- [ ] Phase 2 — Dashboard: port + rebrand to Terraavani; multi-hazard tab views
- [ ] Phase 3 — Edge-AI firmware: on-device z-score anomaly detection, risk fusion,
      alert-only transmission mode
- [ ] Phase 4 — Multi-sensor hardware: buy parts (~₹1,200 demo budget), wire
      HC-SR04 + DHT22 + MQ-135 + solar, extend firmware
- [ ] Phase 5 — Gateway relay demo: 2× ESP32 ESP-NOW (sensor → gateway → cloud),
      RSSI/packet stats on gateway OLED
- [ ] Pre-demo: UptimeRobot pinger, README screenshots, PPT updates

## Team

Team **scapegoats** — crastacalrin@gmail.com · +91 70229 41015 · github.com/Alricvp
