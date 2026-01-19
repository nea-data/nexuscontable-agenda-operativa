import streamlit as st
import pandas as pd

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

# Comunicación (DEMO / diagnóstica)
from core.comunicaciones import (
    cargar_comunicaciones,
    registrar_comunicacion,
    ultimo_contacto_cliente,
)

# =========================
# CONFIG
# =========================
st.set_page_config(page_title="NexusContable · Agenda Operativa", layout="wide")
HOY = pd.Timestamp.today().normalize()

# =========================
# TEMPLATES (WhatsApp / Email)
# =========================
TEMPLATES = {
    "WhatsApp": {
        "Recordatorio vencimientos": {
            "asunto": "Recordatorio vencimientos",
            "mensaje": "Hola {cliente}, te recordamos vencimientos próximos. Avisanos si necesitás algo."
        },
        "Aviso de deuda": {
            "asunto": "Aviso de deuda",
            "mensaje": "Hola {cliente}, detectamos una deuda pendiente. Podemos evaluar opciones."
        },
        "Solicitud de documentación": {
            "asunto": "Solicitud de documentación",
            "mensaje": "Hola {cliente}, necesitamos documentación para continuar con presentaciones."
        }
    },
    "Email": {
        "Recordatorio mensual": {
            "asunto": "Recordatorio mensual de obligaciones",
            "mensaje": "Estimado/a {cliente},\n\nLe recordamos vencimientos fiscales próximos.\n\nSaludos."
        },
        "Aviso de deuda": {
            "asunto": "Aviso de deuda pendiente",
            "mensaje": "Estimado/a {cliente},\n\nSe registra deuda pendiente. Podemos evaluar plan de pagos.\n\nSaludos."
        },
        "Solicitud de documentación": {
            "asunto": "Solicitud de documentación",
            "mensaje": "Estimado/a {cliente},\n\nPara continuar con la gestión necesitamos documentación.\n\nSaludos."
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
    tipo = safe_str(row.get("tipo_contribuyente")).upper()
    flag = safe_str(row.get("monotributo")).upper()
    return tipo == "MONO" or flag == "SI"

# =========================
# AGENDA GENERAL
# =========================
agenda_general = generar_agenda_general(clientes, venc_gen, HOY)

if not agenda_general.empty:
    subset = [c for c in ["cuit", "impuesto", "organismo", "periodo_estimado", "fecha_vto"] if c in agenda_general.columns]
    if len(subset) >= 3:
        agenda_general = agenda_general.drop_duplicates(subset=subset)

# =========================
# DEUDAS
# =========================
def deudas_cliente(cuit):
    if deudas is None or deudas.empty or "cuit" not in deudas.columns:
        return pd.DataFrame()
    return deudas[deudas["cuit"].astype(str) == str(cuit)].copy()

def deudas_activas(df):
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    if "estado_deuda" in out.columns:
        est = out["estado_deuda"].astype(str).str.upper()
        out = out[est.isin(["EXIGIBLE", "ACTIVA", "VENCIDA"])]
    return out

def ordenar_deudas(df):
    if df is None or df.empty:
        return pd.DataFrame()
    for col in ["total_deuda", "monto", "importe"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
            return df.sort_values(col, ascending=False)
    return df

# =========================
# COMUNICACIÓN (RENDER)
# =========================
def render_comunicacion_cliente(cuit, cliente, df_vencimientos, df_deudas):

    st.divider()

    ult = ultimo_contacto_cliente(cuit)
    if ult:
        st.info(
            f"💬 Último contacto: {ult['canal']} · {ult['fecha']} · "
            f"{ult['motivo']} · hace {ult['dias']} días"
        )
    else:
        st.warning("💬 Sin comunicaciones registradas con este cliente.")

    with st.expander("💬 Comunicación con el cliente", expanded=False):

        hist = cargar_comunicaciones()
        hist_cli = hist[hist["cuit"].astype(str) == str(cuit)].copy()

        st.markdown("### 📜 Historial")
        if hist_cli.empty:
            st.info("Sin comunicaciones aún.")
        else:
            hist_cli["fecha"] = pd.to_datetime(hist_cli["fecha"])
            st.dataframe(
                hist_cli.sort_values("fecha", ascending=False)[
                    ["fecha", "canal", "motivo", "estado", "asunto"]
                ],
                use_container_width=True,
                height=220
            )

        st.divider()

        sugerido = None
        if not df_deudas.empty:
            sugerido = "Aviso de deuda"
        elif not df_vencimientos.empty:
            sugerido = "Recordatorio vencimientos"

        if sugerido:
            st.warning(f"⚡ Acción sugerida: {sugerido}")

        st.markdown("### ✉️ Generar y registrar comunicación")

        with st.form("form_comunicacion", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)

            canal = c1.selectbox("Canal", ["WhatsApp", "Email"])
            modelos = list(TEMPLATES[canal].keys())

            modelo = c2.selectbox(
                "Modelo",
                modelos,
                index=(modelos.index(sugerido) if sugerido in modelos else 0)
            )

            estado = c3.selectbox("Estado", ["ENVIADO", "PENDIENTE", "RESPONDIDO"])

            asunto = st.text_input("Asunto", value=TEMPLATES[canal][modelo]["asunto"])
            mensaje = st.text_area(
                "Mensaje",
                value=TEMPLATES[canal][modelo]["mensaje"].format(cliente=cliente),
                height=120
            )

            if st.form_submit_button("✅ Registrar comunicación"):
                registrar_comunicacion(
                    cuit=cuit,
                    cliente=cliente,
                    canal=canal,
                    motivo=modelo,
                    estado=estado,
                    asunto=asunto,
                    mensaje=mensaje
                )
                st.success("Comunicación registrada correctamente.")
                st.rerun()

# =========================
# UI — NAVEGACIÓN
# =========================
st.sidebar.header("🧭 Navegación")
modo = st.sidebar.radio("Modo de vista", ["Vista general", "Vista por cliente"])

# =========================
# VISTA GENERAL
# =========================
if modo == "Vista general":

    st.title("📅 Mi Cartera · Resumen Operativo")

    vencidos_df = generar_vencidos(agenda_general, HOY)
    proximos_7 = generar_control_semanal(agenda_general, HOY, dias=7)
    d_activas = deudas_activas(deudas)

    if not vencidos_df.empty or not d_activas.empty:
        st.error("🔴 Operación crítica")
    elif not proximos_7.empty:
        st.warning("🟠 Atención")
    else:
        st.success("🟢 Operación normal")

    k = kpis(agenda_general)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Obligaciones", k.get("obligaciones", 0))
    c2.metric("Vencidas", k.get("vencidas", 0))
    c3.metric("En riesgo", len(proximos_7))
    c4.metric("Clientes", k.get("clientes", 0))

    st.divider()
    st.dataframe(agenda_general, use_container_width=True)

# =========================
# VISTA POR CLIENTE
# =========================
else:
    st.title("👤 Vista por cliente")

    lista = sorted(clientes["razon_social"].astype(str).unique())
    cliente_sel = st.sidebar.selectbox("Cliente", lista)

    row = clientes[clientes["razon_social"] == cliente_sel].iloc[0]
    cuit = safe_str(row.get("cuit"))

    st.subheader(cliente_sel)
    st.caption(f"CUIT {cuit}")

    df_cli = agenda_general[agenda_general["cuit"].astype(str) == cuit]
    d = deudas_activas(deudas_cliente(cuit))

    st.markdown("### 📌 Vencimientos")
    st.dataframe(df_cli if not df_cli.empty else pd.DataFrame(), use_container_width=True)

    st.markdown("### 🚨 Deudas")
    st.dataframe(ordenar_deudas(d) if not d.empty else pd.DataFrame(), use_container_width=True)

    st.divider()
    st.subheader("🧠 Diagnóstico RI PRO")

    hist = cargar_comunicaciones()
    hist_cli = hist[hist["cuit"].astype(str) == cuit]

    ri = ri_pro_cliente(df_cli, d, hist_cli)
    res = ri["resumen"]

    c1, c2, c3 = st.columns(3)
    c1.metric("Score", res["score"])
    c2.metric("Nivel", f"{res['color']} {res['nivel']}")
    c3.metric("Acción", res["accion_sugerida"])

    if es_mono(row):
        st.divider()
        render_monotributo(row, venc_mono, deudas, HOY)

    render_comunicacion_cliente(cuit, cliente_sel, df_cli, d)
