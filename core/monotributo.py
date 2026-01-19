import streamlit as st
import pandas as pd
import numpy as np


# =========================
# UTILS
# =========================
def safe_str(x):
    return "" if pd.isna(x) else str(x)

def semaforo_por_dias(dias: int) -> str:
    if dias < 0:
        return "🔴"
    if dias <= 30:
        return "🟠"
    if dias <= 60:
        return "🟡"
    return "🟢"

def parse_fecha(anio: int, mes: int, dia: int) -> pd.Timestamp:
    return pd.Timestamp(year=int(anio), month=int(mes), day=int(dia))


# =========================
# CONFIG (editable)
# =========================
def categoria_tope_default():
    # Placeholder (lo hacemos real después con tabla)
    return {
        "A": 700000,
        "B": 1050000,
        "C": 1500000,
        "D": 2100000,
        "E": 3000000,
        "F": 4200000,
        "G": 6000000,
        "H": 8500000,
    }


# =========================
# DATA BUILDERS
# =========================
def generar_pagos_monotributo(cuit: str, venc_mono: pd.DataFrame, deudas_df: pd.DataFrame, hoy: pd.Timestamp) -> pd.DataFrame:
    """
    venc_mono: se espera que tenga columnas mes, dia (para el año actual).
    deudas_df: puede venir filtrada por CUIT o completa; si es completa, filtramos.
    """
    if venc_mono is None or venc_mono.empty:
        return pd.DataFrame()

    anio = int(hoy.year)
    pagos = []

    for _, v in venc_mono.iterrows():
        mes = int(v.get("mes"))
        dia = int(v.get("dia"))
        fecha = parse_fecha(anio, mes, dia)
        pagos.append({
            "periodo": f"{anio}-{mes:02d}",
            "fecha_pago": fecha,
        })

    df = pd.DataFrame(pagos)
    if df.empty:
        return df

    # Filtrar deudas mono
    d = deudas_df.copy() if deudas_df is not None else pd.DataFrame()
    if not d.empty:
        if "cuit" in d.columns:
            d = d[d["cuit"].astype(str) == str(cuit)]
        if "impuesto" in d.columns:
            d = d[d["impuesto"].astype(str).str.upper() == "MONOTRIBUTO"]

    deuda_map = {}
    if not d.empty and "periodo" in d.columns and "total_deuda" in d.columns:
        for _, r in d.iterrows():
            deuda_map[str(r["periodo"])] = float(r["total_deuda"])

    df["deuda_detectada"] = df["periodo"].astype(str).map(deuda_map).fillna(0.0)
    df["estado_pago"] = df["fecha_pago"].apply(lambda x: "VENCIDO" if x < hoy else "PENDIENTE")
    df.loc[df["deuda_detectada"] > 0, "estado_pago"] = "CON_DEUDA"
    df["dias_restantes"] = (df["fecha_pago"] - hoy).dt.days
    df["semaforo"] = df["dias_restantes"].apply(semaforo_por_dias)

    return df.sort_values("fecha_pago").reset_index(drop=True)


def recategorizaciones(anio: int, hoy: pd.Timestamp) -> pd.DataFrame:
    # Fechas simuladas (ajustables). Luego lo hacemos configurable.
    df = pd.DataFrame([
        {"evento": "Recategorización 1° semestre", "fecha": pd.Timestamp(f"{anio}-02-05")},
        {"evento": "Recategorización 2° semestre", "fecha": pd.Timestamp(f"{anio}-07-20")},
    ])
    df["dias_restantes"] = (df["fecha"] - hoy).dt.days
    df["semaforo"] = df["dias_restantes"].apply(semaforo_por_dias)
    return df


def generar_facturacion_simulada(cuit: str, anio: int) -> pd.DataFrame:
    # determinística por CUIT (no cambia en cada refresh)
    seed = int(str(cuit)[-6:]) if str(cuit).isdigit() else 123456
    rng = np.random.default_rng(seed)

    meses = list(range(1, 13))
    fact = []
    for _m in meses:
        val = int(rng.normal(130000, 45000))
        val = max(val, 25000)
        fact.append(val)

    df = pd.DataFrame({
        "periodo": [f"{anio}-{m:02d}" for m in meses],
        "facturacion": fact
    })
    df["acumulado"] = df["facturacion"].cumsum()
    return df


# =========================
# UI RENDER
# =========================
def render_monotributo(cliente_row: pd.Series, venc_mono: pd.DataFrame, deudas_df: pd.DataFrame, hoy: pd.Timestamp):
    cuit = safe_str(cliente_row.get("cuit")).strip()
    nombre = safe_str(cliente_row.get("razon_social")).strip()
    anio = int(hoy.year)

    st.subheader("🧾 Monotributo (PRO)")
    st.caption("Pagos mensuales + deuda + recategorización + control de facturación (simulado, editable)")

    # ---------------------
    # 1) PAGOS MENSUALES
    # ---------------------
    pagos = generar_pagos_monotributo(cuit, venc_mono, deudas_df, hoy)

    if pagos.empty:
        st.info("No hay cronograma de pagos cargado en vencimientos_monotributistas.xlsx")
        return

    prox = pagos[pagos["fecha_pago"] >= hoy].head(1)
    prox_fecha = prox["fecha_pago"].iloc[0] if not prox.empty else None

    total_deuda_mono = float(pagos["deuda_detectada"].sum())
    con_deuda = int((pagos["estado_pago"] == "CON_DEUDA").sum())

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📌 Cliente", nombre)
    c2.metric("💳 Próximo pago", prox_fecha.strftime("%d/%m/%Y") if prox_fecha else "—")
    c3.metric("⚠️ Cuotas con deuda", con_deuda)
    c4.metric("💰 Deuda detectada", f"${total_deuda_mono:,.0f}".replace(",", "."))

    st.markdown("### 💳 Pagos mensuales (Monotributo)")
    pagos_view = pagos.copy()
    pagos_view["fecha_pago"] = pagos_view["fecha_pago"].dt.strftime("%d/%m/%Y")
    st.dataframe(
        pagos_view[["semaforo", "periodo", "fecha_pago", "estado_pago", "deuda_detectada"]],
        use_container_width=True
    )

    # ---------------------
    # 2) RECATEGORIZACIÓN
    # ---------------------
    st.markdown("### 🔄 Recategorización")
    recat = recategorizaciones(anio, hoy)
    prox_recat = recat[recat["fecha"] >= hoy].head(1)
    if not prox_recat.empty:
        r = prox_recat.iloc[0]
        st.info(
            f"{r['semaforo']} Próxima: **{r['evento']}** — "
            f"Vence: **{r['fecha'].strftime('%d/%m/%Y')}** — "
            f"Faltan: **{int(r['dias_restantes'])} días**"
        )

    recat_view = recat.copy()
    recat_view["fecha"] = recat_view["fecha"].dt.strftime("%d/%m/%Y")
    st.dataframe(recat_view[["semaforo", "evento", "fecha", "dias_restantes"]], use_container_width=True)

    # ---------------------
    # 3) FACTURACIÓN + TOPE
    # ---------------------
    st.markdown("### 📈 Facturación y control de categoría (simulado)")

    topes = categoria_tope_default()
    colA, colB, colC = st.columns(3)
    categoria = colA.selectbox("Categoría actual (simulada)", list(topes.keys()), index=2)
    tope = colB.number_input("Tope anual (editable)", min_value=0, value=int(topes[categoria]), step=50000)
    modo_edit = colC.checkbox("Editar facturación mensual", value=False)

    df_fact = generar_facturacion_simulada(cuit, anio)

    if modo_edit:
        df_fact_edit = st.data_editor(
            df_fact[["periodo", "facturacion"]].copy(),
            use_container_width=True,
            num_rows="fixed"
        )
        df_fact["facturacion"] = df_fact_edit["facturacion"].astype(float)
        df_fact["acumulado"] = df_fact["facturacion"].cumsum()

    acumulado = float(df_fact["acumulado"].iloc[-1]) if not df_fact.empty else 0.0
    pct = (acumulado / tope) * 100 if tope > 0 else 0.0

    if pct >= 100:
        riesgo = "🔴 Supera el tope"
    elif pct >= 85:
        riesgo = "🟠 Muy cerca del tope"
    elif pct >= 70:
        riesgo = "🟡 Cerca del tope"
    else:
        riesgo = "🟢 En rango"

    a, b, c = st.columns(3)
    a.metric("Acumulado anual", f"${acumulado:,.0f}".replace(",", "."))
    b.metric("% del tope usado", f"{pct:.1f}%")
    c.metric("Riesgo", riesgo)

    st.dataframe(df_fact, use_container_width=True)

    st.caption("Luego esto lo conectamos a ARCA (facturación) o a bancos/MP cuando sumes extractores.")
