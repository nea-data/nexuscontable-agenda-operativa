import pandas as pd
from datetime import date


# ======================================================
# UTILS
# ======================================================
def safe_str(x) -> str:
    return "" if pd.isna(x) else str(x).strip()


def parse_terminacion(terminacion) -> list[int]:
    """
    Convierte:
    '0-1-2' -> [0,1,2]
    '6-7-8-9' -> [6,7,8,9]
    """
    if pd.isna(terminacion):
        return []
    return [int(x) for x in str(terminacion).split("-") if x.isdigit()]


def ultimo_digito_cuit(cuit) -> int | None:
    try:
        return int(str(cuit).strip()[-1])
    except Exception:
        return None


def construir_fecha_vto(anio: int, mes: int, dia: int) -> pd.Timestamp:
    return pd.Timestamp(date(anio, mes, dia))


def semaforo_por_dias(dias: int) -> str:
    if dias < 0:
        return "🔴"
    if dias <= 7:
        return "🟠"
    return "🟢"


def es_monotributista(cli: pd.Series) -> bool:
    # tu archivo tiene "tipo_contibuyente" (con b) + "monotributo"
    tipo = safe_str(cli.get("tipo_contibuyente")).upper()
    flag = safe_str(cli.get("monotributo")).upper()
    return (tipo == "MONO") or (flag == "SI")


def responsabilidades_cliente(cli: pd.Series) -> set[tuple[str, str]]:
    """
    Devuelve el set de (impuesto, organismo) que realmente aplica al cliente.
    Basado en tu clientes.xlsx:
      - iva SI -> (IVA, ARCA)
      - iibb_corr SI -> (IIBB, DGR)
      - iibb_chaco SI -> (IIBB, ATP(CHACO))
      - ts_corr SI -> (TS, ACOR)
    """
    resp = set()

    if safe_str(cli.get("iva")).upper() == "SI":
        resp.add(("IVA", "ARCA"))

    if safe_str(cli.get("iibb_corr")).upper() == "SI":
        resp.add(("IIBB", "DGR"))

    if safe_str(cli.get("iibb_chaco")).upper() == "SI":
        resp.add(("IIBB", "ATP(CHACO)"))

    if safe_str(cli.get("ts_corr")).upper() == "SI":
        resp.add(("TS", "ACOR"))

    return resp


# ======================================================
# MOTOR PRINCIPAL
# ======================================================
def generar_agenda_general(
    clientes: pd.DataFrame,
    vencimientos: pd.DataFrame,
    hoy: pd.Timestamp,
) -> pd.DataFrame:
    """
    Agenda RI (presentaciones).
    Genera SOLO obligaciones que aplican al cliente según clientes.xlsx.

    Garantiza 1 fila por:
    cuit + impuesto + organismo + periodo_estimado
    """

    registros = []

    clientes = clientes.copy()
    vencimientos = vencimientos.copy()

    clientes.columns = [c.lower().strip() for c in clientes.columns]
    vencimientos.columns = [c.lower().strip() for c in vencimientos.columns]

    hoy = pd.to_datetime(hoy).normalize()

    for _, cli in clientes.iterrows():
        cuit = cli.get("cuit")
        cliente = cli.get("razon_social")

        if pd.isna(cuit) or pd.isna(cliente):
            continue

        # Monotributo se maneja por módulo aparte
        if es_monotributista(cli):
            continue

        dig = ultimo_digito_cuit(cuit)
        if dig is None:
            continue

        resp = responsabilidades_cliente(cli)
        if not resp:
            continue  # cliente sin RI marcada

        for _, vto in vencimientos.iterrows():
            impuesto = safe_str(vto.get("impuesto")).upper()
            organismo = safe_str(vto.get("organismo")).upper()

            # ✅ filtro por responsabilidades reales del cliente
            if (impuesto, organismo) not in resp:
                continue

            # ✅ filtro por terminación CUIT
            terminaciones = parse_terminacion(vto.get("terminacion"))
            if dig not in terminaciones:
                continue

            mes = int(vto.get("mes"))
            dia = int(vto.get("dia"))

            # período estimado:
            # si el mes de vencimiento <= mes actual -> mismo año
            # si no -> año anterior (porque corresponde al período anterior)
            if mes <= hoy.month:
                anio = hoy.year
            else:
                anio = hoy.year - 1

            periodo = f"{anio}-{mes:02d}"
            fecha_vto = construir_fecha_vto(hoy.year, mes, dia)  # fecha real en el año corriente

            # OJO: si estamos en enero y mes=12, fecha_vto sería dic del año actual (futuro),
            # pero en la práctica tu base se usa para vencimientos del año corriente.
            # Si querés que siempre sea el año del "hoy", esto está OK.
            # Si querés que acompañe el "anio" del período, avísame y lo ajustamos.

            dias_restantes = (fecha_vto - hoy).days

            registros.append({
                "cuit": str(cuit),
                "cliente": safe_str(cliente),
                "impuesto": impuesto,
                "organismo": organismo,
                "periodo_estimado": periodo,
                "fecha_vto": fecha_vto,
                "dias_restantes": dias_restantes,
                "semaforo": semaforo_por_dias(dias_restantes),
            })

    agenda = pd.DataFrame(registros)

    if agenda.empty:
        return agenda

    # ✅ dedupe final por llave lógica
    agenda = agenda.drop_duplicates(
        subset=["cuit", "impuesto", "organismo", "periodo_estimado"]
    ).sort_values(["fecha_vto", "cliente", "impuesto"])

    return agenda.reset_index(drop=True)
