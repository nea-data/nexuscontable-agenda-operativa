import pandas as pd

def generar_control_semanal(df: pd.DataFrame, hoy: pd.Timestamp, dias: int = 7) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    hasta = hoy + pd.Timedelta(days=int(dias))
    out = df[(df["fecha_vto"] >= hoy) & (df["fecha_vto"] <= hasta)].copy()

    # prioridad: primero lo más cercano
    if "dias_restantes" in out.columns:
        out = out.sort_values(["dias_restantes", "cliente", "impuesto"])
    else:
        out = out.sort_values(["fecha_vto", "cliente", "impuesto"])

    return out.reset_index(drop=True)


def generar_proximos(df: pd.DataFrame, hoy: pd.Timestamp, dias: int = 30) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    hasta = hoy + pd.Timedelta(days=int(dias))
    out = df[(df["fecha_vto"] >= hoy) & (df["fecha_vto"] <= hasta)].copy()
    return out.sort_values(["fecha_vto", "cliente", "impuesto"]).reset_index(drop=True)


def generar_vencidos(df: pd.DataFrame, hoy: pd.Timestamp) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()

    out = df[df["fecha_vto"] < hoy].copy()
    if "dias_restantes" in out.columns:
        out = out.sort_values(["dias_restantes", "cliente", "impuesto"])
    else:
        out = out.sort_values(["fecha_vto", "cliente", "impuesto"])
    return out.reset_index(drop=True)


def kpis(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"obligaciones": 0, "vencidas": 0, "ok": 0, "clientes": 0}

    vencidas = int((df.get("estado_agenda") == "VENCIDO").sum()) if "estado_agenda" in df.columns else 0
    ok = int((df.get("estado_agenda") == "OK").sum()) if "estado_agenda" in df.columns else 0

    return {
        "obligaciones": int(len(df)),
        "vencidas": vencidas,
        "ok": ok,
        "clientes": int(df["cliente"].nunique()) if "cliente" in df.columns else 0,
    }
