# app.py — Mini Weather Station (InfluxDB + KPIs + Alertas + Auto-refresh)
import os, time
import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st
from influxdb_client import InfluxDBClient

# ---------- Config de página ----------
st.set_page_config(page_title="Mini Weather Station", page_icon="🌦️", layout="wide")

# ---------- Estilo básico coherente ----------
st.markdown("""
<style>
[data-testid="stHeader"] { background: linear-gradient(90deg,#0f172a,#1e293b); }
h1,h2,h3,h4 { color: #e2e8f0 !important; }
.block-container { padding-top: 1.5rem; }
.kpi .big { font-size: 1.8rem; font-weight: 700; }
.badge{display:inline-block;padding:6px 10px;border-radius:999px;color:white;font-weight:700}
.badge-ok{background:#16a34a}.badge-warn{background:#f59e0b}.badge-alert{background:#dc2626}
</style>
""", unsafe_allow_html=True)

# ---------- Credenciales (usar Secrets en Cloud) ----------
INFLUXDB_URL    = st.secrets.get("INFLUXDB_URL",    os.getenv("INFLUXDB_URL"))
INFLUXDB_TOKEN  = st.secrets.get("INFLUXDB_TOKEN",  os.getenv("INFLUXDB_TOKEN"))
INFLUXDB_ORG    = st.secrets.get("INFLUXDB_ORG",    os.getenv("INFLUXDB_ORG"))
INFLUXDB_BUCKET = st.secrets.get("INFLUXDB_BUCKET", os.getenv("INFLUXDB_BUCKET"))

if not all([INFLUXDB_URL, INFLUXDB_TOKEN, INFLUXDB_ORG, INFLUXDB_BUCKET]):
    st.error("Faltan credenciales de InfluxDB. Configura INFLUXDB_URL / INFLUXDB_TOKEN / INFLUXDB_ORG / INFLUXDB_BUCKET en Secrets.")
    st.stop()

client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)
q = client.query_api()

# ---------- Controles ----------
st.title("🌦️ Mini Weather Station")
st.caption("Monitoreo de temperatura, humedad y vibración ligera para espacios interiores.")

with st.sidebar:
    st.header("⚙️ Controles")
    rango = st.selectbox("Rango de tiempo", ["30m","1h","6h","12h","24h","7d","15d"], index=3)
    suav_env = st.selectbox("Suavizado ambiente", ["10s","30s","1m"], index=1)
    suav_mpu = st.selectbox("Suavizado movimiento", ["100ms","200ms","500ms","1s"], index=1)
    umbral_hi = st.slider("Alerta: sensación térmica (°C)", 25.0, 40.0, 30.0, 0.5)
    hum_min   = st.slider("Humedad mínima (%)", 10, 50, 30, 1)
    hum_max   = st.slider("Humedad máxima (%)", 60, 90, 75, 1)
    vib_thr   = st.slider("Vibración RMS (m/s²) alerta", 0.5, 3.0, 1.5, 0.1)
    refresh_s = st.slider("Auto-actualizar cada (s)", 5, 60, 15, 1)

# ---------- Helpers ----------
@st.cache_data(ttl=5)
def query_flux(query: str) -> pd.DataFrame:
    df = q.query_data_frame(org=INFLUXDB_ORG, query=query)
    if isinstance(df, list) and len(df): df = pd.concat(df, ignore_index=True)
    if df is None or df.empty or "_time" not in df.columns:
        return pd.DataFrame(columns=["Tiempo","Variable","Valor"])
    df = df[["_time","_field","_value"]].rename(columns={"_time":"Tiempo","_field":"Variable","_value":"Valor"})
    df["Tiempo"] = pd.to_datetime(df["Tiempo"], errors="coerce")
    df["Valor"]  = pd.to_numeric(df["Valor"], errors="coerce")
    return df.dropna().sort_values("Tiempo")

def badge(text, level):
    cls = {"ok":"badge-ok","warn":"badge-warn","alert":"badge-alert"}.get(level,"badge-warn")
    st.markdown(f'<span class="badge {cls}">{text}</span>', unsafe_allow_html=True)

# ---------- Consultas (usa nombres del profe) ----------
# Ambiente (DHT22): temperatura, humedad, sensacion_termica
flux_dht = f'''
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: -{rango})
  |> filter(fn: (r) => r._measurement == "studio-dht22")
  |> filter(fn: (r) => r._field == "temperatura" or r._field == "humedad" or r._field == "sensacion_termica")
  |> aggregateWindow(every: {suav_env}, fn: mean, createEmpty: false)
'''
df_dht = query_flux(flux_dht)

# Movimiento (MPU6050): aceleraciones (para RMS) y/o temperature
flux_mpu = f'''
from(bucket: "{INFLUXDB_BUCKET}")
  |> range(start: -{rango})
  |> filter(fn: (r) => r._measurement == "mpu6050")
  |> filter(fn: (r) => r._field == "accel_x" or r._field == "accel_y" or r._field == "accel_z" or
                         r._field == "temperature")
  |> aggregateWindow(every: {suav_mpu}, fn: mean, createEmpty: false)
'''
df_mpu = query_flux(flux_mpu)

# ---------- KPIs ----------
st.subheader("Indicadores rápidos")
k1,k2,k3,k4 = st.columns(4)

temp_now = hum_now = hi_now = np.nan
if not df_dht.empty:
    last = df_dht.groupby("Variable").tail(1).set_index("Variable")["Valor"]
    temp_now = float(last.get("temperatura", np.nan))
    hum_now  = float(last.get("humedad", np.nan))
    hi_now   = float(last.get("sensacion_termica", np.nan))

k1.markdown('<div class="kpi"><div>🌡️ Temperatura</div><div class="big">'
            + (f"{temp_now:.1f} °C" if np.isfinite(temp_now) else "—") + "</div></div>", unsafe_allow_html=True)
k2.markdown('<div class="kpi"><div>💧 Humedad</div><div class="big">'
            + (f"{hum_now:.1f} %" if np.isfinite(hum_now) else "—") + "</div></div>", unsafe_allow_html=True)

with k3:
    if not np.isfinite(hi_now) or not np.isfinite(hum_now):
        badge("Sin datos", "warn")
    elif hi_now <= 27 and 30 <= hum_now <= 60:
        badge("Confortable", "ok")
    elif hi_now <= umbral_hi and 25 <= hum_now <= 70:
        badge("Precaución", "warn")
    else:
        badge("Alerta térmica", "alert")

# Movimiento actual (lo calculamos más abajo y lo mostramos aquí)
vib_rms_now = np.nan
mov_flag_now = 0  # 0: normal, 1: movimiento

# ---------- Gráficas: Temperatura / Humedad ----------
st.subheader("Ambiente")
if df_dht.empty:
    st.info("No hay datos de DHT22 en el rango.")
else:
    for var, titulo, unidad in [
        ("temperatura", "Temperatura (°C)", "°C"),
        ("humedad", "Humedad (%)", "%"),
    ]:
        sub = df_dht[df_dht["Variable"]==var]
        if not sub.empty:
            fig = px.line(sub, x="Tiempo", y="Valor", title=titulo, template="plotly_white")
            fig.update_layout(margin=dict(l=0,r=0,b=0,t=40))
            st.plotly_chart(fig, use_container_width=True)

# ---------- Vibración: vib_rms + bandera de movimiento ----------
st.subheader("Movimiento / Vibración")
if df_mpu.empty or not any(df_mpu["Variable"].isin(["accel_x","accel_y","accel_z"])):
    st.info("No hay aceleraciones (accel_x/y/z) en el rango seleccionado.")
else:
    acc = df_mpu[df_mpu["Variable"].isin(["accel_x","accel_y","accel_z"])]
    piv = acc.pivot(index="Tiempo", columns="Variable", values="Valor").dropna()
    a_mag = np.sqrt((piv**2).sum(axis=1))          # magnitud total
    a_dyn = np.maximum(a_mag - 9.81, 0)            # quitar gravedad (aprox)
    vib_rms = (a_dyn**2).rolling(20, min_periods=5).mean()**0.5
    vib_df = vib_rms.rename("vib_rms").reset_index()

    # bandera binaria de movimiento para la mini estación
    mov_flag = (vib_rms > vib_thr).astype(int).rename("movimiento")
    mov_df = mov_flag.reset_index()

    if not vib_df.empty:
        vib_rms_now = float(vib_df["vib_rms"].iloc[-1])
        mov_flag_now = int(mov_df["movimiento"].iloc[-1])
        # Gráfica vib_rms
        fig_v = px.line(vib_df, x="Tiempo", y="vib_rms", title="Vibración RMS (m/s²)", template="plotly_white")
        fig_v.update_layout(margin=dict(l=0,r=0,b=0,t=40))
        st.plotly_chart(fig_v, use_container_width=True)
        # Gráfica bandera movimiento (0/1)
        fig_m = px.step(mov_df, x="Tiempo", y="movimiento", title="Movimiento detectado (0 = normal, 1 = movimiento)",
                        template="plotly_white")
        fig_m.update_yaxes(range=[-0.1, 1.1])
        fig_m.update_layout(margin=dict(l=0,r=0,b=0,t=40))
        st.plotly_chart(fig_m, use_container_width=True)

# ---------- Alertas ----------
if np.isfinite(hi_now) and hi_now > umbral_hi:
    st.warning("🌡️ Alta sensación térmica. Ventila o hidrátate.")
if np.isfinite(hum_now) and (hum_now < hum_min or hum_now > hum_max):
    st.warning("💧 Humedad fuera de rango (ideal 30–60%).")
if np.isfinite(vib_rms_now) and vib_rms_now > vib_thr:
    st.error("🟣 Vibración elevada — posible golpe/actividad en la superficie.")

# ---------- Pie y auto-refresh ----------
st.caption(f"Bucket: {INFLUXDB_BUCKET} · Org: {INFLUXDB_ORG} · Rango: {rango} · Refresco: {refresh_s}s")
time.sleep(refresh_s)
st.experimental_rerun()
