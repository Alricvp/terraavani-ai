# 🌍 Terraavani AI

> *"Terra" (Latin: Earth) + "Avani" (Sanskrit: Earth) — the Earth, watching over itself.*

> A resilient, AI-powered environmental monitoring network — distributed smart sensor nodes with on-device edge AI, real multi-hazard data fusion, and actionable early warnings for floods, landslides, forest fires, air pollution, and extreme heat across India.

**Problem Statement:** SIH PS 26178 — *Environmental Intelligence Network* (Qualcomm Inc · Disaster Management · Hardware)

**Status:** 🚧 Under construction — foundation phase

---

## 💡 The Idea

One cheap sensor node, every hazard. A distributed network of solar-powered ESP32 nodes that:

- **Sense locally** — water level, rainfall, soil moisture, tilt/vibration, temperature, humidity, air quality
- **Think locally** — edge AI on-device: anomaly detection + risk classification runs even with zero connectivity
- **Report only what matters** — critical alerts and summarized insights, not raw data streams
- **Scale cheaply** — ~₹1,800/node vs ₹3–20 lakh per commercial monitoring station

## 🏗️ Architecture (planned)

```
TIER 1 — SENSOR NODES (₹1,800 each)        TIER 2 — GATEWAYS
ESP32 + multi-sensor + edge AI   ──radio──▶  ESP32 gateway (WiFi available)
Solar powered, works offline                Forwards alerts to cloud
        │                                            │
        └──────────── TIER 3 — CLOUD ────────────────┘
              FastAPI backend + multi-hazard data fusion
              (Open-Meteo flood & air quality APIs, NASA FIRMS fire data)
                       │
              TIER 4 — DASHBOARDS & ALERTS
              Public PWA dashboard · GIS risk maps · siren/vibration/push
              · prioritized warnings with severity + confidence
```

## 🧩 Multi-Hazard Coverage

| Hazard | Detection source |
|---|---|
| 🌊 Floods / flash floods | Ultrasonic water level (node) + Open-Meteo river discharge forecast (cloud) |
| ⛰️ Landslide precursors | MPU tilt + soil saturation (node) + rainfall thresholds (cloud) |
| 🔥 Forest fires / smoke | MQ-135 smoke (node) + NASA FIRMS satellite hotspots (cloud) |
| 🏭 Air pollution | PM2.5/PM10 + gas sensing (node) + Open-Meteo Air Quality API (cloud) |
| 🌡️ Extreme heat | Temperature + humidity (node), heat-index classification (edge AI) |

## 📊 Project Inheritance

Terraavani AI evolves from our SIH project **Landsafe AI** ([github.com/Alricvp/landsafe-ai](https://github.com/Alricvp/landsafe-ai), live at [landsafe-ai.onrender.com](https://landsafe-ai.onrender.com)) — a working landslide early-warning platform with:

- ✅ Proven ESP32 firmware (median filter, auto-calibration, OLED interface)
- ✅ FastAPI + WebSocket real-time backend on Render
- ✅ Full PWA dashboard: GIS map, stations, alerts, citizen reporting, 5 languages
- ✅ Real regional data via Open-Meteo with an explainable risk model
- ✅ Browser notifications + siren + continuous vibration alerts

## 🗺️ Roadmap

- [ ] Phase 0 — Foundation (repo, architecture, plan)
- [ ] Phase 1 — Backend: multi-hazard data fusion (flood + air quality + fire APIs)
- [ ] Phase 2 — Dashboard rebrand & multi-hazard views
- [ ] Phase 3 — Edge-AI firmware (on-device anomaly detection, alert-only transmission)
- [ ] Phase 4 — Multi-sensor hardware build (ultrasonic, DHT, MQ-135, solar)
- [ ] Phase 5 — ESP-NOW/LoRa gateway relay demo

## 👥 Team Scapegoats

- 📧 crastacalrin@gmail.com
- 📱 +91 70229 41015
- 🐙 [github.com/Alricvp](https://github.com/Alricvp)
