"""
Terraavani AI - Environmental Intelligence Network
Multi-hazard early-warning backend (SIH PS 26178):
  - ESP32 sensor nodes POST tilt/moisture/water-level readings
  - Multi-hazard regional data layer: live flood (river discharge),
    air quality (PM2.5/PM10), extreme heat, landslide risk
  - Serves the public PWA dashboard + WebSocket live stream
Deploy to Render for a permanent public URL.
"""

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import json
import os
import math
import base64
import uuid
import urllib.request
import urllib.parse

app = FastAPI(title="Terraavani AI", version="1.0.0")

# Allow all origins for public access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- In-memory store (last 500 readings) ----
sensor_data = []
MAX_READINGS = 500
citizen_reports = []
MAX_REPORTS = 200

# ---- Connected WebSocket clients ----
connected_clients: list[WebSocket] = []

# ---- Data model ----
class TiltReading(BaseModel):
    device_id: str
    tilt: float
    status: str
    ip: str = ""
    moisture: float = 0.0

# ---- Citizen report data model ----
class CitizenReport(BaseModel):
    report_type: str  # crack, slope_damage, blocked_road, flooding, other
    severity: str     # low, medium, high, critical
    lat: float
    lng: float
    description: str = ""
    reporter_name: str = "Anonymous"
    photo_data: str = ""  # base64 encoded image

class SMSAlert(BaseModel):
    phone: str
    message: str
    severity: str = "info"



# ---- Helper: calculate landslide risk ----
def calculate_risk(readings):
    """Calculate landslide risk based on recent tilt + moisture data."""
    if not readings:
        return {
            "risk_level": "LOW",
            "risk_score": 0,
            "tilt_risk": 0,
            "moisture_risk": 0,
            "trend": "stable",
            "prediction": "No landslide risk detected.",
            "water_density": 0,
        }

    recent = readings[-20:]  # Last 20 readings

    # Average tilt
    avg_tilt = sum(r.get("tilt", 0) for r in recent) / len(recent)
    max_tilt = max(r.get("tilt", 0) for r in recent)

    # Average moisture
    avg_moisture = sum(r.get("moisture", 0) for r in recent) / len(recent)
    max_moisture = max(r.get("moisture", 0) for r in recent)

    # Water density (kg/m^3 estimate from moisture %)
    # Soil density ~1600 kg/m^3, water adds weight
    water_density = 1000 + (avg_moisture / 100.0) * 600  # 1000-1600 range

    # Tilt risk (0-100)
    tilt_risk = min(100, (avg_tilt / 45.0) * 100)

    # Moisture risk (0-100)
    moisture_risk = min(100, (avg_moisture / 90.0) * 100)

    # Combined risk score
    # Moisture amplifies tilt risk (wet soil slides more easily)
    moisture_multiplier = 1.0 + (avg_moisture / 100.0) * 0.5
    risk_score = min(100, (tilt_risk * 0.6 + moisture_risk * 0.4) * moisture_multiplier)

    # Trend detection
    if len(readings) >= 10:
        old_avg_tilt = sum(r.get("tilt", 0) for r in readings[-20:-10]) / min(10, len(readings[-20:-10]))
        new_avg_tilt = sum(r.get("tilt", 0) for r in readings[-10:]) / min(10, len(readings[-10:]))
        if new_avg_tilt > old_avg_tilt * 1.2:
            trend = "increasing"
        elif new_avg_tilt < old_avg_tilt * 0.8:
            trend = "decreasing"
        else:
            trend = "stable"
    else:
        trend = "stable"

    # Risk level
    if risk_score >= 70 or (avg_tilt >= 40 and avg_moisture >= 70):
        risk_level = "CRITICAL"
        prediction = "⚠️ HIGH landslide probability! Ground unstable with saturated soil. Evacuate immediately!"
    elif risk_score >= 50 or (avg_tilt >= 30 and avg_moisture >= 60):
        risk_level = "HIGH"
        prediction = "🔴 Significant landslide risk. Heavy rain + tilt detected. Prepare for evacuation."
    elif risk_score >= 30 or avg_moisture >= 60:
        risk_level = "MODERATE"
        prediction = "🟡 Moderate risk. Soil moisture elevated. Monitor closely for changes."
    elif risk_score >= 15:
        risk_level = "LOW-MODERATE"
        prediction = "🟢 Minor risk detected. Normal monitoring recommended."
    else:
        risk_level = "LOW"
        prediction = "✅ Low risk. Conditions stable."

    if trend == "increasing":
        prediction += " ⚠️ Risk is INCREASING!"

    return {
        "risk_level": risk_level,
        "risk_score": round(risk_score, 1),
        "tilt_risk": round(tilt_risk, 1),
        "moisture_risk": round(moisture_risk, 1),
        "trend": trend,
        "prediction": prediction,
        "water_density": round(water_density, 1),
        "avg_tilt": round(avg_tilt, 2),
        "avg_moisture": round(avg_moisture, 1),
        "max_tilt": round(max_tilt, 2),
        "max_moisture": round(max_moisture, 1),
    }


# ---- REST endpoint for ESP32 ----
@app.post("/api/tilt")
async def receive_tilt(reading: TiltReading):
    entry = {
        "device_id": reading.device_id,
        "tilt": reading.tilt,
        "moisture": reading.moisture,
        "status": reading.status,
        "ip": reading.ip,
        "timestamp": datetime.now().isoformat(),
    }

    sensor_data.append(entry)
    if len(sensor_data) > MAX_READINGS:
        sensor_data.pop(0)

    # Broadcast to dashboard clients
    message = json.dumps({"type": "sensor", "data": entry})
    disconnected = []
    for client in connected_clients:
        try:
            await client.send_text(message)
        except:
            disconnected.append(client)
    for client in disconnected:
        connected_clients.remove(client)

    return {"ok": True, "data": entry}


# ---- Get latest data ----
@app.get("/api/latest")
async def get_latest():
    if not sensor_data:
        return {"data": None}
    risk = calculate_risk(sensor_data)
    return {"data": sensor_data[-1], "risk": risk}


@app.get("/api/history")
async def get_history():
    return {"data": sensor_data}


@app.get("/api/risk")
async def get_risk():
    risk = calculate_risk(sensor_data)
    return {"data": risk}


# ---- Citizen Reports API ----
@app.post("/api/report")
async def submit_report(report: CitizenReport):
    entry = {
        "id": str(uuid.uuid4())[:8],
        "report_type": report.report_type,
        "severity": report.severity,
        "lat": report.lat,
        "lng": report.lng,
        "description": report.description,
        "reporter_name": report.reporter_name,
        "photo_data": report.photo_data,
        "timestamp": datetime.now().isoformat(),
        "verified": False,
    }
    citizen_reports.append(entry)
    if len(citizen_reports) > MAX_REPORTS:
        citizen_reports.pop(0)

    # Broadcast to dashboard clients
    message = json.dumps({"type": "report", "data": entry})
    disconnected = []
    for client in connected_clients:
        try:
            await client.send_text(message)
        except:
            disconnected.append(client)
    for client in disconnected:
        connected_clients.remove(client)

    return {"ok": True, "report_id": entry["id"]}


@app.get("/api/reports")
async def get_reports():
    return {"data": citizen_reports}


@app.get("/api/reports/count")
async def get_report_count():
    return {"total": len(citizen_reports), "critical": sum(1 for r in citizen_reports if r["severity"] == "critical"), "high": sum(1 for r in citizen_reports if r["severity"] == "high")}


# ---- SMS Alerts API ----
sms_recipients = []  # stored phone numbers

@app.post("/api/sms/register")
async def register_sms(alert: SMSAlert):
    """Register phone number for SMS alerts."""
    if alert.phone not in sms_recipients:
        sms_recipients.append(alert.phone)
    return {"ok": True, "message": f"Phone {alert.phone} registered for SMS alerts (TextBelt)", "total_recipients": len(sms_recipients)}

@app.post("/api/sms/send")
async def send_sms(alert: SMSAlert):
    """Send SMS via TextBelt (free, no signup). 1 SMS/day on free tier."""
    if alert.phone not in sms_recipients:
        sms_recipients.append(alert.phone)
    
    # Format phone for India
    phone = alert.phone.strip()
    if not phone.startswith("+"):
        if phone.startswith("0"):
            phone = "+91" + phone[1:]
        elif len(phone) == 10:
            phone = "+91" + phone
        else:
            phone = "+" + phone
    
    try:
        data = urllib.parse.urlencode({
            "phone": phone,
            "message": alert.message[:160],
            "key": "textbelt",  # Free tier key
        }).encode()
        req = urllib.request.Request(
            "https://textbelt.com/text",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        resp = urllib.request.urlopen(req, timeout=10)
        result = json.loads(resp.read().decode())
        if result.get("success"):
            return {"ok": True, "sent": True, "via": "TextBelt", "quota_remaining": result.get("quotaRemaining", "?")}
        else:
            return {"ok": True, "sent": False, "via": "TextBelt", "error": result.get("error", "unknown")}
    except Exception as e:
        print(f"[SMS] To: {phone} | {alert.message}")
        return {"ok": True, "sent": False, "via": "fallback", "note": f"TextBelt error: {e}. Free tier allows 1 SMS/day."}

@app.get("/api/sms/recipients")
async def get_sms_recipients():
    return {"recipients": sms_recipients}

# ---- Historical Landslide Data ----
@app.get("/api/historical")
async def get_historical():
    hist_path = os.path.join(os.path.dirname(__file__), "historical.json")
    try:
        with open(hist_path, "r") as f:
            data = json.load(f)
        # Calculate summary stats
        total_deaths = sum(d.get("deaths", 0) for d in data)
        total_incidents = len(data)
        years = sorted(set(d["year"] for d in data))
        states = {}
        for d in data:
            loc = d["location"].split(",")[-1].strip()
            states[loc] = states.get(loc, 0) + 1
        return {
            "data": data,
            "summary": {
                "total_incidents": total_incidents,
                "total_deaths": total_deaths,
                "years_covered": f"{min(years)}-{max(years)}",
                "most_affected_states": sorted(states.items(), key=lambda x: -x[1])[:5]
            }
        }
    except FileNotFoundError:
        return {"data": [], "summary": {}}


# ---- REAL regional monitoring stations (NER corridors) ----
# Real coordinates along known landslide-prone NER corridors.
NER_STATIONS = [
    {"id": "ESP32-NER-001", "name": "Gangtok — 32nd Mile NH10 Corridor", "loc": "East Sikkim, Sikkim",      "state": "Sikkim",     "lat": 27.18, "lng": 88.53, "slope": 42.5},
    {"id": "ESP32-NER-002", "name": "Haflong — Jatinga Valley Escarpment", "loc": "Dima Hasao, Assam",        "state": "Assam",      "lat": 25.18, "lng": 93.02, "slope": 38.0},
    {"id": "ESP32-NER-003", "name": "Cherrapunji — Shella Gorge Rim",      "loc": "East Khasi Hills, Meghalaya","state": "Meghalaya", "lat": 25.30, "lng": 91.70, "slope": 48.0},
    {"id": "ESP32-NER-004", "name": "Guwahati — Khasi Hills NH6 Section",  "loc": "Kamrup, Assam",             "state": "Assam",      "lat": 26.14, "lng": 91.74, "slope": 35.0},
    {"id": "ESP32-NER-005", "name": "Kohima — Dimapur NH2 Stretch",        "loc": "Kohima, Nagaland",          "state": "Nagaland",   "lat": 25.67, "lng": 94.11, "slope": 45.0},
    {"id": "ESP32-NER-006", "name": "Aizawl — Reiek Tlang Ridge",          "loc": "Mamit, Mizoram",            "state": "Mizoram",    "lat": 23.73, "lng": 92.72, "slope": 44.0},
    {"id": "ESP32-NER-007", "name": "Tupul — Ijei River Rail Corridor",     "loc": "Noney, Manipur",            "state": "Manipur",    "lat": 24.83, "lng": 93.70, "slope": 46.8},
    {"id": "ESP32-NER-008", "name": "Itanagar — Hollongi Highway Cut",      "loc": "Papum Pare, Arunachal",     "state": "Arunachal Pradesh", "lat": 27.10, "lng": 93.62, "slope": 40.0},
    {"id": "ESP32-NER-009", "name": "Agartala — Baramura Hill Range",       "loc": "West Tripura, Tripura",     "state": "Tripura",    "lat": 23.83, "lng": 91.28, "slope": 32.0},
    {"id": "ESP32-NER-010", "name": "Imphal — Kangchup Road Section",       "loc": "Imphal West, Manipur",      "state": "Manipur",    "lat": 24.82, "lng": 93.94, "slope": 38.0},
]

# Cache so we don't hammer Open-Meteo (Render free tier friendly)
_station_cache = {"data": None, "ts": 0}
CACHE_TTL = 600  # 10 minutes

def _station_risk(rain24, soilmoist, slope):
    """Real, explainable risk model: rain + satellite soil moisture + slope."""
    rain_risk = min(100.0, (max(rain24, 0.0) / 150.0) * 100.0)   # 150mm/24h = max rain risk
    soil_risk = min(100.0, max(soilmoist, 0.0) * 100.0)          # Open-Meteo gives 0..1 m3/m3
    slope_mult = 1.0 + max((slope - 30.0), 0.0) / 100.0          # steeper slopes amplify
    score = min(100.0, (rain_risk * 0.45 + soil_risk * 0.55) * slope_mult)
    level = "HIGH" if score >= 65 else ("MODERATE" if score >= 40 else "LOW")
    return round(score, 1), level

@app.get("/api/stations")
async def get_stations():
    """Real-time regional data for all NER monitoring stations via Open-Meteo."""
    import time as _time
    now = _time.time()
    if _station_cache["data"] and now - _station_cache["ts"] < CACHE_TTL:
        return {"data": _station_cache["data"], "source": "cache"}

    lats = ",".join(str(s["lat"]) for s in NER_STATIONS)
    lngs = ",".join(str(s["lng"]) for s in NER_STATIONS)
    url = (
        "https://api.open-meteo.com/v1/forecast"
        f"?latitude={lats}&longitude={lngs}"
        "&current=temperature_2m,relative_humidity_2m,precipitation,weather_code"
        "&hourly=soil_moisture_0_to_1cm"
        "&daily=precipitation_sum,precipitation_probability_max"
        "&past_days=1&forecast_days=3&timezone=Asia%2FKolkata"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "TerraavaniAI/1.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        payload = json.loads(resp.read().decode())
        results = payload if isinstance(payload, list) else [payload]
    except Exception as e:
        print(f"[stations] Open-Meteo failed: {e}")
        if _station_cache["data"]:
            return {"data": _station_cache["data"], "source": "cache-stale"}
        return {"data": [], "source": "error"}

    out = []
    for st, wx in zip(NER_STATIONS, results):
        try:
            # 24h rainfall = yesterday's daily sum + today so far (mm)
            daily = wx.get("daily", {}).get("precipitation_sum", []) or [0.0, 0.0]
            rain24 = round(sum(x or 0.0 for x in daily[:2]), 1)  # [yesterday, today]
            # Latest satellite/model soil moisture (m3/m3, 0..1)
            sm_series = wx.get("hourly", {}).get("soil_moisture_0_to_1cm", []) or []
            soil = sm_series[-1] if sm_series else 0.0
            cur = wx.get("current", {}) or {}
            score, level = _station_risk(rain24, soil, st["slope"])
            tilt_est = round((score / 100.0) * 1.8, 2)  # expected creep proxy from model
            # --- 72h forecast: predicted rain per day -> predicted risk ---
            daily_rain = wx.get("daily", {}).get("precipitation_sum", []) or []
            daily_prob = wx.get("daily", {}).get("precipitation_probability_max", []) or []
            forecast = []
            daily_times = wx.get("daily", {}).get("time", []) or []
            for i in range(2, min(4, len(daily_rain))):  # entries 2,3 = tomorrow, day-after
                fr = max(daily_rain[i] or 0.0, 0.0)
                fs, fl = _station_risk(fr, soil, st["slope"])
                forecast.append({
                    "day": ("Tomorrow", "Day After")[i - 2],
                    "date": daily_times[i] if i < len(daily_times) else "",
                    "rain": round(fr, 1),
                    "prob": daily_prob[i] if i < len(daily_prob) else None,
                    "score": fs,
                    "level": fl,
                })
            out.append({
                **st,
                "rain": rain24,
                "moisture": round(soil * 100.0, 1),
                "temperature": cur.get("temperature_2m"),
                "humidity": cur.get("relative_humidity_2m"),
                "weather_code": cur.get("weather_code"),
                "tilt": tilt_est,
                "score": score,
                "level": level,
                "forecast": forecast,
                "online": True,
            })
        except Exception as e:
            print(f"[stations] parse failed for {st['id']}: {e}")

    if out:
        _station_cache["data"] = out
        _station_cache["ts"] = now
    return {"data": out, "source": "open-meteo"}



# ============================================================
#  MULTI-HAZARD REGIONAL DATA LAYER  (Terraavani AI)
#  Real free sources: Open-Meteo Flood API (GloFAS river discharge),
#  Open-Meteo Air Quality API (CAMS: PM2.5/PM10/AQI), heat index
#  from the forecast API. Landslide risk comes from /api/stations.
# ============================================================

_HAZARD_CITIES = [
    {"name": "Guwahati",    "state": "Assam",            "lat": 26.14, "lng": 91.74},
    {"name": "Dibrugarh",   "state": "Assam",            "lat": 27.47, "lng": 94.91},
    {"name": "Silchar",     "state": "Assam",            "lat": 24.83, "lng": 92.79},
    {"name": "Shillong",    "state": "Meghalaya",        "lat": 25.58, "lng": 91.89},
    {"name": "Gangtok",     "state": "Sikkim",           "lat": 27.33, "lng": 88.61},
    {"name": "Imphal",      "state": "Manipur",          "lat": 24.82, "lng": 93.94},
    {"name": "Agartala",    "state": "Tripura",          "lat": 23.83, "lng": 91.28},
    {"name": "Aizawl",      "state": "Mizoram",          "lat": 23.73, "lng": 92.72},
    {"name": "Kohima",      "state": "Nagaland",         "lat": 25.67, "lng": 94.11},
    {"name": "Itanagar",    "state": "Arunachal Pradesh","lat": 27.10, "lng": 93.62},
]

_hazard_cache = {"data": None, "ts": 0}

def _flood_level(discharge_today, discharge_max3):
    """Classify GloFAS river discharge vs its own 3-day envelope."""
    if discharge_max3 <= 0:
        return "LOW", 10.0
    ratio = discharge_today / max(discharge_max3, 0.001)
    if ratio >= 0.95 and discharge_today > 300:
        return "HIGH", min(95.0, 60.0 + ratio * 30.0)
    if ratio >= 0.85 and discharge_today > 150:
        return "MODERATE", min(70.0, 45.0 + ratio * 20.0)
    return "LOW", min(35.0, 10.0 + ratio * 25.0)

def _aqi_level(pm25, pm10, aqi):
    """Indian-style bands on CAMS European AQI + PM2.5."""
    if pm25 > 90 or aqi > 150: return "HIGH", min(95.0, aqi * 0.6)
    if pm25 > 55 or aqi > 95:  return "MODERATE", min(70.0, aqi * 0.55)
    return "LOW", max(8.0, aqi * 0.5)

def _heat_level(temp_c, rh):
    """Simplified heat-index risk (IMD heat-wave notion)."""
    hi = temp_c + 0.05 * rh  # crude but explainable comfort-adjusted index
    if temp_c >= 40 or hi >= 47: return "HIGH", min(95.0, hi)
    if temp_c >= 35 or hi >= 41: return "MODERATE", min(70.0, hi)
    return "LOW", max(5.0, hi * 0.8)

def _flood_json(urls):
    """Fetch several Flood-API tiles in one pass (batched by lat/lng lists)."""
    lats = ",".join(str(c["lat"]) for c in _HAZARD_CITIES)
    lngs = ",".join(str(c["lng"]) for c in _HAZARD_CITIES)
    url = ("https://flood-api.open-meteo.com/v1/flood"
           f"?latitude={lats}&longitude={lngs}"
           "&daily=river_discharge&forecast_days=3")
    req = urllib.request.Request(url, headers={"User-Agent": "TerraavaniAI/1.0"})
    resp = urllib.request.urlopen(req, timeout=15)
    payload = json.loads(resp.read().decode())
    return payload if isinstance(payload, list) else [payload]

@app.get("/api/hazards")
async def get_hazards():
    """Multi-hazard regional snapshot: flood + air quality + heat, per city."""
    import time as _time
    now = _time.time()
    if _hazard_cache["data"] and now - _hazard_cache["ts"] < CACHE_TTL:
        return {"data": _hazard_cache["data"], "source": "cache"}

    lats = ",".join(str(c["lat"]) for c in _HAZARD_CITIES)
    lngs = ",".join(str(c["lng"]) for c in _HAZARD_CITIES)
    try:
        aq_url = ("https://air-quality-api.open-meteo.com/v1/air-quality"
                  f"?latitude={lats}&longitude={lngs}"
                  "&current=pm2_5,pm10,european_aqi")
        wx_url = ("https://api.open-meteo.com/v1/forecast"
                  f"?latitude={lats}&longitude={lngs}"
                  "&daily=temperature_2m_max&forecast_days=1")
        flood_list = _flood_json(None)

        def _get(url):
            req = urllib.request.Request(url, headers={"User-Agent": "TerraavaniAI/1.0"})
            resp = urllib.request.urlopen(req, timeout=15)
            payload = json.loads(resp.read().decode())
            return payload if isinstance(payload, list) else [payload]

        aq_list = _get(aq_url)
        wx_list = _get(wx_url)
    except Exception as e:
        print(f"[hazards] fetch failed: {e}")
        if _hazard_cache["data"]:
            return {"data": _hazard_cache["data"], "source": "cache-stale"}
        return {"data": [], "source": "error"}

    out = []
    for city, aq, wx, fl in zip(_HAZARD_CITIES, aq_list, wx_list, flood_list):
        try:
            cur = aq.get("current", {}) or {}
            pm25 = float(cur.get("pm2_5") or 0.0)
            pm10 = float(cur.get("pm10") or 0.0)
            aqi = float(cur.get("european_aqi") or 0.0)
            aq_lvl, aq_score = _aqi_level(pm25, pm10, aqi)

            tmax = (wx.get("daily", {}).get("temperature_2m_max") or [None])[0]
            tmax = float(tmax) if tmax is not None else 0.0
            rh_default = 70.0
            h_lvl, h_score = _heat_level(tmax, rh_default)

            rd = (fl.get("daily", {}).get("river_discharge") or [0.0, 0.0, 0.0])
            f_lvl, f_score = _flood_level(float(rd[0] or 0.0), max(float(x or 0.0) for x in rd))

            worst = max(aq_score, h_score, f_score)
            overall = "HIGH" if worst >= 65 else ("MODERATE" if worst >= 40 else "LOW")
            out.append({
                **city,
                "air": {"pm25": pm25, "pm10": pm10, "aqi": aqi, "level": aq_lvl, "score": round(aq_score)},
                "heat": {"tmax": tmax, "level": h_lvl, "score": round(h_score)},
                "flood": {"discharge": round(float(rd[0] or 0.0), 1),
                          "discharge_3d_max": round(max(float(x or 0.0) for x in rd), 1),
                          "level": f_lvl, "score": round(f_score)},
                "overall": overall,
                "overall_score": round(worst),
            })
        except Exception as e:
            print(f"[hazards] parse failed for {city['name']}: {e}")

    if out:
        _hazard_cache["data"] = out
        _hazard_cache["ts"] = now
    return {"data": out, "source": "open-meteo"}


# ---- Health check ----
@app.get("/health")
async def health():
    return {"status": "ok", "readings": len(sensor_data), "reports": len(citizen_reports), "sms_recipients": len(sms_recipients)}


# ---- WebSocket for real-time dashboard updates ----
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connected_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        if websocket in connected_clients:
            connected_clients.remove(websocket)


# ---- Static files ----
@app.get("/sw.js")
async def serve_sw():
    path = os.path.join(os.path.dirname(__file__), "sw.js")
    return FileResponse(path, media_type="application/javascript")

@app.get("/manifest.json")
async def serve_manifest():
    path = os.path.join(os.path.dirname(__file__), "manifest.json")
    return FileResponse(path, media_type="application/json")

@app.get("/historical.json")
async def serve_historical_file():
    path = os.path.join(os.path.dirname(__file__), "historical.json")
    return FileResponse(path, media_type="application/json")


# ---- Serve dashboard ----
@app.get("/", response_class=HTMLResponse)
async def serve_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(dashboard_path, "r") as f:
        content = f.read()

    host = os.getenv("RENDER_EXTERNAL_URL", "")
    if host:
        ws_url = host.replace("https://", "wss://").replace("http://", "ws://")
        content = content.replace(
            "`ws://${location.host}/ws`",
            f"'{ws_url}/ws'"
        )

    return HTMLResponse(content=content)


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    print(f"\n=== Landsafe AI Server v2.0 ===")
    print(f"Dashboard: http://localhost:{port}")
    print(f"API endpoint: POST http://localhost:{port}/api/tilt\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
