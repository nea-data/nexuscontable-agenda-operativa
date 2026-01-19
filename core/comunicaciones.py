import pandas as pd
from datetime import datetime
import os

RUTA_COM = "data/comunicaciones.csv"

COLUMNAS = [
    "fecha",
    "cuit",
    "cliente",
    "canal",
    "motivo",
    "estado",
    "asunto",
    "mensaje"
]

# =========================
# CARGA
# =========================
def cargar_comunicaciones():
    if not os.path.exists(RUTA_COM):
        return pd.DataFrame(columns=COLUMNAS)

    df = pd.read_csv(RUTA_COM)
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df

# =========================
# REGISTRO
# =========================
def registrar_comunicacion(
    cuit,
    cliente,
    canal,
    motivo,
    estado,
    asunto,
    mensaje
):
    nuevo = {
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "cuit": str(cuit),
        "cliente": cliente,
        "canal": canal,
        "motivo": motivo,
        "estado": estado,
        "asunto": asunto,
        "mensaje": mensaje
    }

    df = cargar_comunicaciones()
    df = pd.concat([df, pd.DataFrame([nuevo])], ignore_index=True)
    df.to_csv(RUTA_COM, index=False)

# =========================
# ÚLTIMO CONTACTO (BADGE)
# =========================
def ultimo_contacto_cliente(cuit):
    df = cargar_comunicaciones()
    df = df[df["cuit"].astype(str) == str(cuit)]

    if df.empty:
        return None

    ult = df.sort_values("fecha", ascending=False).iloc[0]
    dias = (pd.Timestamp.today() - ult["fecha"]).days

    return {
        "canal": ult["canal"],
        "fecha": ult["fecha"].strftime("%d/%m/%Y"),
        "dias": dias,
        "motivo": ult["motivo"]
    }
