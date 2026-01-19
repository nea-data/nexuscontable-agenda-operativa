from __future__ import annotations

import pandas as pd


def _safe_str(x) -> str:
    return "" if pd.isna(x) else str(x)


def _to_dt(s) -> pd.Series:
    return pd.to_datetime(s, errors="coerce")


def _money(x) -> float:
    try:
        return float(pd.to_numeric(x, errors="coerce"))
    except Exception:
        return 0.0


def _pick_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    if df is None or df.empty:
        return None
    cols = set(df.columns)
    for c in candidates:
        if c in cols:
            return c
    return None


def _deuda_total(df_deudas: pd.DataFrame) -> float:
    if df_deudas is None or df_deudas.empty:
        return 0.0

    col_total = _pick_col(df_deudas, ["total_deuda", "monto", "importe", "saldo"])
    if not col_total:
        return 0.0

    s = pd.to_numeric(df_deudas[col_total], errors="coerce").fillna(0)
    return float(s.sum())


def _organismos(df_deudas: pd.DataFrame) -> list[str]:
    if df_deudas is None or df_deudas.empty:
        return []
    col_org = _pick_col(df_deudas, ["organismo", "ente", "jurisdiccion"])
    if not col_org:
        return []
    return sorted(
        df_deudas[col_org].astype(str).str.strip().replace("nan", "").unique().tolist()
    )


def _antiguedad_max_meses(df_deudas: pd.DataFrame) -> int:
    """
    Busca una columna temporal para estimar antigüedad:
    - fecha_actualizacion / fecha / actualizado / etc.
    Si no existe, intenta con 'periodo' tipo 'YYYY-MM'.
    """
    if df_deudas is None or df_deudas.empty:
        return 0

    col_fecha = _pick_col(df_deudas, ["fecha_actualizacion", "fecha", "actualizado", "updated_at"])
    if col_fecha:
        fechas = _to_dt(df_deudas[col_fecha])
        if fechas.notna().any():
            hoy = pd.Timestamp.today().normalize()
            delta = (hoy - fechas).dt.days
            # Aproximación meses = días/30
            meses = (delta / 30).fillna(0)
            return int(meses.max())

    col_periodo = _pick_col(df_deudas, ["periodo", "periodo_fiscal"])
    if col_periodo:
        # esperar 'YYYY-MM' o 'YYYYMM'
        p = df_deudas[col_periodo].astype(str).str.strip()
        p = p.str.replace("/", "-", regex=False)
        p = p.str.replace(" ", "", regex=False)

        # normaliza YYYYMM -> YYYY-MM
        p = p.where(~p.str.match(r"^\d{6}$"), p.str.slice(0, 4) + "-" + p.str.slice(4, 6))
        fechas = _to_dt(p + "-01")
        if fechas.notna().any():
            hoy = pd.Timestamp.today().normalize()
            delta = (hoy - fechas).dt.days
            meses = (delta / 30).fillna(0)
            return int(meses.max())

    return 0


def _vencimientos_buckets(df_vto: pd.DataFrame) -> dict:
    """
    Espera columnas típicas:
    - fecha_vto
    - dias_restantes
    Devuelve: criticos (<=7), proximos (8-30), futuros (>30)
    """
    out = {"criticos": [], "proximos": [], "futuros": []}

    if df_vto is None or df_vto.empty:
        return out

    df = df_vto.copy()

    col_fecha = _pick_col(df, ["fecha_vto", "vto", "fecha"])
    if col_fecha:
        df[col_fecha] = _to_dt(df[col_fecha])

    col_dias = _pick_col(df, ["dias_restantes", "dias", "restantes"])
    if not col_dias:
        # si no hay dias_restantes, lo calculamos con fecha_vto
        if col_fecha:
            hoy = pd.Timestamp.today().normalize()
            df["dias_restantes"] = (df[col_fecha] - hoy).dt.days
            col_dias = "dias_restantes"

    if not col_dias:
        return out

    df[col_dias] = pd.to_numeric(df[col_dias], errors="coerce")

    # columnas para mostrar
    col_imp = _pick_col(df, ["impuesto", "tributo"])
    col_org = _pick_col(df, ["organismo", "ente"])
    col_per = _pick_col(df, ["periodo_estimado", "periodo", "periodo_fiscal"])
    cols_show = []
    for c in [col_imp, col_org, col_per, col_fecha, col_dias]:
        if c and c not in cols_show:
            cols_show.append(c)

    def _rows_to_list(df_part: pd.DataFrame) -> list[dict]:
        if df_part.empty:
            return []
        tmp = df_part.copy()
        # renombres amigables
        ren = {}
        if col_imp: ren[col_imp] = "impuesto"
        if col_org: ren[col_org] = "organismo"
        if col_per: ren[col_per] = "periodo"
        if col_fecha: ren[col_fecha] = "fecha_vto"
        if col_dias: ren[col_dias] = "dias_restantes"
        tmp = tmp[cols_show].rename(columns=ren)
        if "fecha_vto" in tmp.columns:
            tmp["fecha_vto"] = pd.to_datetime(tmp["fecha_vto"], errors="coerce").dt.strftime("%d/%m/%Y")
        tmp["dias_restantes"] = pd.to_numeric(tmp.get("dias_restantes"), errors="coerce")
        tmp = tmp.sort_values("dias_restantes", ascending=True)
        return tmp.to_dict("records")

    crit = df[df[col_dias] <= 7].copy()
    prox = df[(df[col_dias] >= 8) & (df[col_dias] <= 30)].copy()
    fut = df[df[col_dias] > 30].copy()

    out["criticos"] = _rows_to_list(crit)
    out["proximos"] = _rows_to_list(prox)
    out["futuros"] = _rows_to_list(fut)
    return out


def _score_vencimientos(buckets: dict) -> int:
    """
    Escala simple (0-40):
    - críticos pesan mucho
    - próximos pesan medio
    """
    ncrit = len(buckets.get("criticos", []))
    nprox = len(buckets.get("proximos", []))

    score = 0
    score += min(30, ncrit * 15)   # 1 crítico ya sube fuerte
    score += min(10, nprox * 3)    # varios próximos suman
    return int(score)


def _score_deuda(total_deuda: float, antiguedad_meses: int) -> int:
    """
    Escala simple (0-40):
    - por monto + por antigüedad
    Ajustable luego con reglas reales.
    """
    score = 0

    # monto
    if total_deuda <= 0:
        score += 0
    elif total_deuda <= 100_000:
        score += 10
    elif total_deuda <= 500_000:
        score += 20
    else:
        score += 30

    # antigüedad
    if antiguedad_meses >= 6:
        score += 10
    elif antiguedad_meses >= 3:
        score += 5

    return int(min(40, score))


def _score_comunicacion(df_com: pd.DataFrame) -> tuple[int, dict]:
    """
    Escala simple (0-20).
    Busca si hay comunicaciones recientes y si hay pendientes sin respuesta.
    Columnas esperadas:
    - fecha
    - estado (ENVIADO/PENDIENTE/RESPONDIDO)
    - canal
    """
    info = {
        "estado": "—",
        "canal_recomendado": "—",
        "dias_sin_respuesta": "—",
        "accion_sugerida": None,
    }

    if df_com is None or df_com.empty:
        # sin historial: riesgo bajo, pero sugiere iniciar contacto si hay problemas
        return 0, {**info, "estado": "SIN HISTORIAL", "canal_recomendado": "WhatsApp"}

    df = df_com.copy()
    col_fecha = _pick_col(df, ["fecha", "created_at", "timestamp"])
    col_estado = _pick_col(df, ["estado", "status"])
    col_canal = _pick_col(df, ["canal", "channel"])

    if col_fecha:
        df[col_fecha] = _to_dt(df[col_fecha])

    # último contacto
    if col_fecha and df[col_fecha].notna().any():
        ult = df.sort_values(col_fecha, ascending=False).iloc[0]
        hoy = pd.Timestamp.today().normalize()
        dias = int((hoy - ult[col_fecha]).days) if pd.notna(ult[col_fecha]) else None
        info["dias_sin_respuesta"] = dias if dias is not None else "—"
        if col_canal:
            info["canal_recomendado"] = _safe_str(ult.get(col_canal)).strip() or "WhatsApp"

    # estados
    score = 0
    if col_estado:
        est = df[col_estado].astype(str).str.upper()
        # pendientes pesan
        n_pend = int((est == "PENDIENTE").sum())
        n_env = int((est == "ENVIADO").sum())
        n_resp = int((est == "RESPONDIDO").sum())

        if n_pend > 0:
            score += min(15, n_pend * 8)
            info["estado"] = "PENDIENTE"
            info["accion_sugerida"] = "Recontactar / solicitar respuesta"
        elif n_env > 0 and n_resp == 0:
            score += 6
            info["estado"] = "ENVIADO SIN RESPUESTA"
            info["accion_sugerida"] = "Confirmar recepción"
        else:
            info["estado"] = "OK"
    else:
        info["estado"] = "OK"

    # envejecimiento
    dias = info.get("dias_sin_respuesta")
    if isinstance(dias, int):
        if dias >= 15:
            score += 5
            info["accion_sugerida"] = info["accion_sugerida"] or "Recontactar (15+ días)"
        elif dias >= 7:
            score += 3

    return int(min(20, score)), info


def _nivel_color(score_total: int) -> tuple[str, str]:
    """
    Devuelve (nivel, color_emoji)
    """
    if score_total >= 60:
        return "CRÍTICO", "🔴"
    if score_total >= 35:
        return "ALTO", "🔴"
    if score_total >= 20:
        return "MEDIO", "🟠"
    return "BAJO", "🟢"


def _accion_principal(nivel: str, deuda_total: float, ncrit: int, nprox: int) -> str:
    """
    Acción prioritaria simple y coherente con la vista simulada.
    """
    if deuda_total > 0:
        return "Evaluar pago o plan de pagos"
    if ncrit > 0:
        return "Priorizar presentaciones críticas"
    if nprox > 0:
        return "Organizar presentaciones próximas"
    if nivel in ("CRÍTICO", "ALTO"):
        return "Revisar situación fiscal integral"
    return "Operación normal"


def ri_pro_cliente(
    vencimientos_cliente: pd.DataFrame | None,
    deudas_cliente: pd.DataFrame | None,
    comunicaciones_cliente: pd.DataFrame | None = None,
) -> dict:
    """
    Motor RI PRO:
    - Analiza vencimientos (criticos/proximos/futuros)
    - Analiza deudas (total/organismos/antigüedad)
    - Analiza comunicación (estado y score)
    - Devuelve dict listo para render en Streamlit
    """

    # --- vencimientos
    buckets = _vencimientos_buckets(vencimientos_cliente)
    ncrit = len(buckets.get("criticos", []))
    nprox = len(buckets.get("proximos", []))

    score_v = _score_vencimientos(buckets)

    # --- deudas
    deuda_total = _deuda_total(deudas_cliente)
    orgs = _organismos(deudas_cliente)
    ant_meses = _antiguedad_max_meses(deudas_cliente)

    score_d = _score_deuda(deuda_total, ant_meses)

    # --- comunicación
    score_c, info_c = _score_comunicacion(comunicaciones_cliente)

    # total
    score_total = int(score_v + score_d + score_c)
    nivel, color = _nivel_color(score_total)

    accion = _accion_principal(nivel, deuda_total, ncrit, nprox)

    # chips
    chips = []
    if deuda_total > 0:
        chips.append("Deuda exigible")
    if ncrit > 0:
        chips.append("Vencimientos críticos")
    elif nprox > 0:
        chips.append("Vencimientos próximos")
    if info_c.get("estado") and info_c["estado"] not in ("—", "OK"):
        chips.append(f"Comunicación: {info_c['estado']}")

    return {
        "resumen": {
            "score": score_total,
            "nivel": nivel,
            "color": color,
            "accion_sugerida": accion,
            "chips": chips,
            "composicion": {
                "vencimientos": score_v,
                "deudas": score_d,
                "comunicacion": score_c,
                "total": score_total,
            },
        },
        "riesgo_vencimientos": buckets,
        "riesgo_deuda": {
            "total_deuda": float(deuda_total),
            "organismos": orgs,
            "antiguedad_max_meses": int(ant_meses),
            "accion_sugerida": "Evaluar plan de pagos" if deuda_total > 0 else None,
        },
        "estado_comunicacion": info_c,
    }
