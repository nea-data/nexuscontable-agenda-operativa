import streamlit as st
import pandas as pd
from datetime import datetime

# =========================
# CORE
# =========================
from core.motor_cruce import generar_agenda_general
from core.control_semanal import (
    generar_control_semanal,
    generar_proximos,
    generar_vencidos,
    kpis,
)
from core.ri import ri_pro_cliente
from core.monotributo import render_monotributo
from core.comunicaciones import (
    cargar_comunicaciones,
    registrar_comunicacion,
)

# =========================
# CONFIG
# =========================
st.set_page_config(
    page_title="NexusContable · Agenda Operativa",
    layout="wide"
)

HOY = pd.Timestamp.today().normalize()

# =========================
# SESSION STATE (Cloud safe)
# =========================
if "refresh_comunicaciones" not in st.session_state:
    st.session_state.refresh_comunicaciones = 0

# =========================
# TEMPLATES DE MENSAJES
# =========================
TEMPLATES = {
    "WhatsApp": {
        "Aviso de deuda": {
            "asunto": "Aviso de deuda",
            "mensaje": "Hola {cliente}, detectamos una deuda pendiente. Podemos evaluar opciones."
        },
        "Recordatorio vencimientos": {
            "asunto": "Recordatorio de vencimientos",
            "mensaje": "Hola {cliente}, te recordamos que tenés vencimientos próximos."
        }
    },
    "Email": {
        "Aviso de deuda": {
            "asunto": "Aviso de deuda pendiente",
            "mensaje": "Estimado/a {cliente},\n\nSe registra deuda pendiente. Podemos evaluar plan de pagos."
        },
        "Recordatorio vencimientos": {
            "asunto": "Recordatorio de obligaciones",
            "mensaje": "Estimado/a {cliente},\n\nLe recordamos vencimientos fiscales próximos."
        }
    }
}

# =========================
# CARGA DE DATOS
# =========================
@st.cache_data
def cargar_datos():
    clientes = pd.read_excel("data/clientes.xlsx")
    venc_gen = pd.read_excel("data/vencimientos_anuales.xlsx")
    venc_mono = pd.read_excel("data/vencimientos_monotributistas.xlsx")
    deudas = pd.read_excel("data/deudas_web.xlsx")
    return clientes, venc_gen, venc_mono, deudas

clientes, venc_gen, venc_mono, deudas = cargar_datos()

for df in [clientes, venc_gen, venc_mono, deudas]:
    df.columns = [c.strip().lower() for c in df.columns]

# =========================
# UTILS
# =========================
def safe_str(x):
    return "" if pd.isna(x) else str(x)

def es_mono(row):
    return safe_str(row.get("monotributo")).upper() == "SI"

def deudas_cliente(cuit):
    if deudas.empty:
        return pd.DataFrame()
    return deudas[deudas["cuit"].astype(str) == str(cuit)]

def deudas_activas(df):
    if df.empty:
        return df
    if "estado_deuda" in df.columns:
        return df[df["estado_deuda"].str.upper().isin(["EXIGIBLE", "ACTIVA", "VENCIDA"])]
    return df

# =========================
# AGENDA GENERAL
# =========================
agenda_general = generar_agenda_general(clientes, venc_gen, HOY)

# =========================
# SIDEBAR
# =========================
st.sidebar.header("🧭 Navegación")
modo = st.sidebar.radio(
    "Modo de vista",
    ["Vista general", "Vista por cliente"]
)

# =========================
# VISTA GENERAL
# =========================
if modo == "Vista general":

    st.title("📅 Mi Cartera · Resumen Operativo")

    vencidos_df = generar_vencidos(agenda_general, HOY)
    proximos_7 = generar_control_semanal(agenda_general, HOY, dias=7)

    if not vencidos_df.empty:
        st.error("🔴 Operación crítica")
    elif not proximos_7.empty:
        st.warning("🟠 Atención: vencimientos próximos")
    else:
        st.success("🟢 Operación normal")

    k = kpis(agenda_general)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Obligaciones", k.get("obligaciones", 0))
    c2.metric("Vencidas", k.get("vencidas", 0))
    c3.metric("En riesgo", len(proximos_7))
    c4.metric("Clientes", k.get("clientes", 0))

    st.divider()
    st.subheader("📌 Vencimientos")
    st.dataframe(proximos_7, use_container_width=True)

# =========================
# VISTA POR CLIENTE
# =========================
else:
    st.title("👤 Vista por cliente")

    lista = sorted(clientes["razon_social"].astype(str).unique())
    cliente = st.sidebar.selectbox("Cliente", lista)

    row = clientes[clientes["razon_social"] == cliente].iloc[0]
    cuit = safe_str(row.get("cuit"))

    st.subheader(cliente)
    st.caption(f"CUIT {cuit}")

    # -------------------------
    # VENCIMIENTOS
    # -------------------------
    df_cli = agenda_general[agenda_general["cuit"].astype(str) == cuit]
    st.markdown("### 📌 Vencimientos")
    st.dataframe(df_cli, use_container_width=True)

    # -------------------------
    # DEUDAS
    # -------------------------
    d = deudas_activas(deudas_cliente(cuit))
    st.markdown("### 🚨 Deudas")
    if d.empty:
        st.success("Sin deudas activas")
    else:
        st.dataframe(d, use_container_width=True)

    # -------------------------
    # RI PRO
    # -------------------------
    st.divider()
    st.subheader("🧠 Diagnóstico RI PRO")

    _ = st.session_state.refresh_comunicaciones
    hist = cargar_comunicaciones()
    hist_cli = hist[hist["cuit"].astype(str) == cuit]

    ri = ri_pro_cliente(
        vencimientos_cliente=df_cli,
        deudas_cliente=d,
        comunicaciones_cliente=hist_cli
    )

    res = ri["resumen"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Score", res["score"])
    c2.metric("Nivel", f"{res['color']} {res['nivel']}")
    c3.metric("Acción", res["accion_sugerida"])

    # -------------------------
    # COMUNICACIÓN
    # -------------------------
    st.divider()
    st.subheader("💬 Comunicación con el cliente")

    if hist_cli.empty:
        st.info("Sin comunicaciones registradas")
    else:
        st.dataframe(hist_cli.sort_values("fecha", ascending=False), use_container_width=True)

    with st.expander("✉️ Generar y registrar comunicación"):
        canal = st.selectbox("Canal", list(TEMPLATES.keys()))
        modelo = st.selectbox("Modelo", list(TEMPLATES[canal].keys()))
        estado = st.selectbox("Estado", ["ENVIADO", "PENDIENTE", "SIN RESPUESTA"])

        asunto = TEMPLATES[canal][modelo]["asunto"]
        mensaje = TEMPLATES[canal][modelo]["mensaje"].format(cliente=cliente)

        with st.form("form_comunicacion", clear_on_submit=True):
            asunto_f = st.text_input("Asunto", asunto)
            mensaje_f = st.text_area("Mensaje", mensaje, height=120)

            submit = st.form_submit_button("✅ Registrar comunicación")

        if submit:
            registrar_comunicacion(
                cuit=cuit,
                cliente=cliente,
                canal=canal,
                motivo=modelo,
                estado=estado,
                asunto=asunto_f,
                mensaje=mensaje_f
            )
            st.session_state.refresh_comunicaciones += 1
            st.success("Comunicación registrada correctamente")

    # -------------------------
    # MONOTRIBUTO
    # -------------------------
    if es_mono(row):
        st.divider()
        render_monotributo(row, venc_mono, deudas, HOY)
