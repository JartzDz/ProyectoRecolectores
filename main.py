# CELDA 1 (DISTANCIA): Carga grafo + obtiene clientes (por etiqueta o fallback polÃ­gono) + estaciÃ³n/relleno
import osmnx as ox
import networkx as nx
import numpy as np
import geopandas as gpd
import shapely.geometry as geom
import sys
from shapely.validation import explain_validity
from pyproj import CRS
from pathlib import Path

CAPACIDAD_MAXIMA_CAMION_KG = 12000.0
NUM_VEHICULOS_MAX = 10
HORAS_TRABAJO_MIN_H = 6.5
HORAS_TRABAJO_H = 8.0
NUMERO_RECOLECTORES_CAMION = 3
NUMERO_CHOFER_CAMION = 1
SUELDO_RECOLECTORES_USD = 665.0
SUELDO_CHOFER_USD = 801.0
TIEMPO_PARADA_SEG = 30.0
VELOCIDAD_ACERCAMIENTO_KMH = 50.0
VELOCIDAD_RECOLECCION_KMH = 10.0
VELOCIDAD_TRANSPORTE_KMH = 40.0
VELOCIDAD_RETORNO_KMH = 50.0
TOTAL_PESO_PESADO_TON = 120.0
TOTAL_PESO_LIGERO_TON = 60.0
TOTAL_BASURA_KG = (TOTAL_PESO_PESADO_TON + TOTAL_PESO_LIGERO_TON) * 1000.0
PRECIO_DIESEL_USD_GAL = 2.99
RENDIMIENTO_KM_GAL = 4.5
PESO_BASURA_NODOS_RESTAURANTES = 8.0
PESO_BASURA_NODOS_TIENDAS = 3.0
PESO_BASURA_NODOS_OTROS_CLIENTES = 2.0
PESOS_BASURA_POR_TIPO_NODO = {
    "hogar_urbano": 1.0,
    "bar": 4.06,
    "restaurante": 8.5,
    "hotel": 5.69,
    "escuela": 37.09,
    "universidad": 111.19,
    "mercado_pequeno": 1149.25,
    "mercado_grande": 7208.96,
    "otros": 1.0,
}

try:
    from IPython.display import display
except ImportError:
    def display(obj):
        """Fallback simple para ejecuciÃ³n local fuera de notebooks."""
        try:
            print(obj.to_string(index=False))
        except Exception:
            print(obj)

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

print("1) Cargando grafo...")
G = ox.load_graphml("grafo_actualizado.graphml")
G_RUTEO = G
print("   -> OK grafo cargado.")

# 0) Validar que exista 'length' (distancia en metros)
u0, v0, d0 = next(iter(G.edges(data=True)))
if "length" not in d0:
    raise ValueError("âŒ El grafo no tiene atributo 'length' en aristas. No se puede trabajar por distancia.")

# 1) Coordenadas clave
loc_estacion = (-2.8758464, -78.9814250)  # (lat, lon)
loc_relleno  = (-2.965480,  -78.930210)   # (lat, lon)

# 2) Intentar leer clientes/estaciÃ³n/relleno por etiquetas si existen
nodos_clientes = []
dict_demandas = {}
id_estacion = None
id_relleno = None

tiene_tipo = False
for _, data in G.nodes(data=True):
    if "tipo_nodo" in data:
        tiene_tipo = True
        break

if tiene_tipo:
    print("2) DetectÃ© 'tipo_nodo' en el grafo. Leyendo clientes etiquetados...")
    for nodo, data in G.nodes(data=True):
        tipo = data.get("tipo_nodo", "")
        if tipo == "cliente":
            nodos_clientes.append(nodo)
            # demanda opcional
            valor_crudo = data.get("demanda_kg", 0)
            try:
                dict_demandas[nodo] = float(valor_crudo)
            except:
                dict_demandas[nodo] = 0.0
        elif tipo == "estacion":
            id_estacion = nodo
        elif tipo == "relleno":
            id_relleno = nodo

# 3) Si no detectÃ³ estaciÃ³n/relleno por etiqueta, usar nearest_nodes
if id_estacion is None:
    id_estacion = ox.distance.nearest_nodes(G, loc_estacion[1], loc_estacion[0])
if id_relleno is None:
    id_relleno = ox.distance.nearest_nodes(G, loc_relleno[1],  loc_relleno[0])

# 4) Fallback: si no hay clientes etiquetados, usar polÃ­gono + buffer (para acercarte a 307)
if len(nodos_clientes) == 0:
    print("âš ï¸ No hay clientes etiquetados. Uso fallback: polÃ­gono detallado + buffer para aproximar 307.")

    puntos_zona_google = [
        (-2.887645, -79.009025), (-2.887736, -79.007586), (-2.887923, -79.006348),
        (-2.888075, -79.005389), (-2.888244, -79.004639), (-2.888711, -79.002377),
        (-2.888831, -79.001439), (-2.888814, -78.999706), (-2.888882, -79.000000),
        (-2.889047, -78.999089), (-2.890028, -78.997606), (-2.891069, -78.996014),
        (-2.891151, -78.996080), (-2.891296, -78.996259), (-2.892042, -78.996402),
        (-2.892213, -78.996397), (-2.905865, -78.996412), (-2.905359, -78.997740),
        (-2.905135, -78.998550), (-2.904920, -78.999181), (-2.904504, -79.000336),
        (-2.903815, -79.000955), (-2.903401, -79.001480), (-2.902941, -79.002025),
        (-2.902452, -79.002893), (-2.899352, -79.008342), (-2.901985, -79.003782),
        (-2.901472, -79.004734), (-2.901022, -79.005559), (-2.900472, -79.006512),
        (-2.900035, -79.007237), (-2.899901, -79.007484), (-2.899655, -79.007843),
        (-2.899341, -79.008347), (-2.899476, -79.008544), (-2.898821, -79.009357),
        (-2.898456, -79.010400), (-2.897691, -79.012220), (-2.896549, -79.013150),
        (-2.897221, -79.011194), (-2.888812, -79.009837), (-2.888588, -79.009670),
        (-2.888575, -79.008742), (-2.887736, -79.008997)
    ]

    polygon_points = [(lon, lat) for (lat, lon) in puntos_zona_google]
    poligono = geom.Polygon(polygon_points)

    if not poligono.is_valid:
        print("   PolÃ­gono invÃ¡lido:", explain_validity(poligono))
        poligono = poligono.buffer(0)

    if poligono.geom_type == "MultiPolygon":
        poligono = max(poligono.geoms, key=lambda g: g.area)

    # nodos a GeoDataFrame
    gdf_nodes = gpd.GeoDataFrame(
        {"node": list(G.nodes())},
        geometry=[geom.Point(G.nodes[n]["x"], G.nodes[n]["y"]) for n in G.nodes()],
        crs="EPSG:4326"
    )

    # UTM (metros)
    def utm_epsg_from_lonlat(lon, lat):
        zone = int(np.floor((lon + 180) / 6) + 1)
        return 32700 + zone if lat < 0 else 32600 + zone

    epsg_utm = utm_epsg_from_lonlat(loc_estacion[1], loc_estacion[0])
    utm_crs = CRS.from_epsg(epsg_utm)

    gdf_nodes_utm = gdf_nodes.to_crs(utm_crs)
    poly_utm = gpd.GeoSeries([poligono], crs="EPSG:4326").to_crs(utm_crs).iloc[0]

    TARGET = 307
    best = None

    for b in range(0, 21):
        poly_buf = poly_utm.buffer(b)
        mask = gdf_nodes_utm.geometry.within(poly_buf) | gdf_nodes_utm.geometry.touches(poly_buf)
        c = int(mask.sum())
        if best is None or abs(c - TARGET) < abs(best[1] - TARGET):
            best = (b, c, mask)

    buffer_opt, count_opt, mask_opt = best
    nodos_clientes = gdf_nodes_utm.loc[mask_opt, "node"].tolist()

    print(f"   -> Buffer elegido: {buffer_opt} m | clientes: {count_opt}")

print("\nâœ… DATOS LISTOS:")
print(f"   -> Clientes a visitar: {len(nodos_clientes)}")
print(f"   -> Nodo EstaciÃ³n: {id_estacion}")
print(f"   -> Nodo Relleno:  {id_relleno}")

# Si no tienes demandas aquÃ­, lo normal es calcularlas en la CELDA 2 (POIs o distribuciÃ³n base)
if len(dict_demandas) > 0:
    print(f"   -> Demanda Total (si aplica): {sum(dict_demandas.values()):.2f} kg")
else:
    print("   -> Demanda: se definirÃ¡ en CELDA 2 (recomendado).")

# CELDA 2 (ROBUSTA): POIs + demandas (sirve con o sin poligono_zona)
import pandas as pd
import numpy as np
import shapely.geometry as geom

print("1) Descargando Puntos de InterÃ©s (POIs) de OSM...")

tags = {
    'amenity': ['restaurant', 'cafe', 'fast_food', 'bar', 'pub', 'marketplace', 'school', 'college', 'university'],
    'shop': True,
    'tourism': ['hotel', 'hostel'],
    'building': ['apartments', 'retail', 'commercial', 'university', 'school']
}

# ---------------------------------------------------------
# A) Asegurar un polÃ­gono para consultar POIs
# ---------------------------------------------------------
if "poligono_zona" in globals() and poligono_zona is not None:
    poly_query = poligono_zona
    print("   -> Usando polÃ­gono definido (poligono_zona).")
else:
    print("   -> No existe poligono_zona. Creando polÃ­gono desde nodos_clientes (convex hull)...")
    pts = [(G.nodes[n]['x'], G.nodes[n]['y']) for n in nodos_clientes]
    poly_query = geom.MultiPoint(pts).convex_hull.buffer(0.0005)  # ~50m aprox (ojo: aprox)

# ---------------------------------------------------------
# B) Descargar POIs
# ---------------------------------------------------------
try:
    pois = ox.features_from_polygon(poly_query, tags)
    print(f"   -> Se encontraron {len(pois)} POIs relevantes.")
except Exception as e:
    print(f"   -> No se pudieron obtener POIs ({e}). Usaremos distribuciÃ³n base.")
    pois = pd.DataFrame()

# ---------------------------------------------------------
# C) Pesos base por nodo (residencial)
# ---------------------------------------------------------
pesos_nodos = {nodo: PESOS_BASURA_POR_TIPO_NODO["hogar_urbano"] for nodo in nodos_clientes}
tipos_basura_nodos = {nodo: "hogar_urbano" for nodo in nodos_clientes}

def tipo_basura_desde_poi(row):
    amenity = row.get("amenity", None)
    tourism = row.get("tourism", None)
    shop = row.get("shop", None)
    building = row.get("building", None)
    name = str(row.get("name", "") or "").lower()

    if isinstance(amenity, str) and amenity in ["university", "college"]:
        return "universidad"
    if isinstance(building, str) and building == "university":
        return "universidad"
    if isinstance(amenity, str) and amenity == "school":
        return "escuela"
    if isinstance(building, str) and building == "school":
        return "escuela"
    if isinstance(tourism, str) and tourism in ["hotel", "hostel"]:
        return "hotel"
    if isinstance(amenity, str) and amenity in ["bar", "pub"]:
        return "bar"
    if isinstance(amenity, str) and amenity in ["restaurant", "fast_food", "cafe"]:
        return "restaurante"
    if isinstance(amenity, str) and amenity == "marketplace":
        return "mercado_grande"
    if isinstance(shop, str) and shop in ["supermarket", "department_store", "mall", "wholesale"]:
        return "mercado_grande"
    if isinstance(shop, str) and shop in ["convenience", "greengrocer", "bakery", "butcher", "deli", "general"]:
        return "mercado_pequeno"
    if "mercado" in name or "market" in name:
        return "mercado_grande"
    if (shop is not None and not pd.isna(shop)) or isinstance(building, str) and building in ["retail", "commercial"]:
        return "otros"
    return "otros"

# ---------------------------------------------------------
# D) Aumentar peso si hay negocio cerca
# ---------------------------------------------------------
if not pois.empty:
    print("2) Asignando basura comercial a nodos cercanos...")

    pois = pois.copy()
    pois["pt"] = pois.geometry.representative_point()

    for _, row in pois.iterrows():
        nearest_node = ox.distance.nearest_nodes(G, row["pt"].x, row["pt"].y)
        if nearest_node not in pesos_nodos:
            continue

        tipo_basura = tipo_basura_desde_poi(row)
        peso_tipo = PESOS_BASURA_POR_TIPO_NODO.get(tipo_basura, PESOS_BASURA_POR_TIPO_NODO["otros"])

        if peso_tipo > pesos_nodos[nearest_node]:
            pesos_nodos[nearest_node] = peso_tipo
            tipos_basura_nodos[nearest_node] = tipo_basura

# ---------------------------------------------------------
# E) Normalizar a TOTAL_BASURA_KG + aleatoriedad controlada
# ---------------------------------------------------------
total_peso_calculado = sum(pesos_nodos.values())
factor_ajuste = TOTAL_BASURA_KG / total_peso_calculado

dict_demandas = {}
lista_demandas_visual = []

np.random.seed(42)
for nodo in nodos_clientes:
    kg_reales = pesos_nodos[nodo] * factor_ajuste
    variacion = np.random.uniform(0.95, 1.05)

    # piso 0 para evitar negativos por cualquier motivo
    kg_final = max(0.0, round(kg_reales * variacion, 2))

    G.nodes[nodo]["demanda_kg"] = kg_final
    G.nodes[nodo]["tipo_basura"] = tipos_basura_nodos.get(nodo, "hogar_urbano")
    G.nodes[nodo]["peso_relativo_basura"] = float(pesos_nodos[nodo])
    dict_demandas[nodo] = kg_final
    lista_demandas_visual.append(kg_final)

# ---------------------------------------------------------
# F) Ajuste final EXACTO y SIN negativos (una sola vez)
# ---------------------------------------------------------
diferencia = round(TOTAL_BASURA_KG - sum(dict_demandas.values()), 2)

if diferencia > 0:
    # falta basura: sumo a un nodo
    n0 = nodos_clientes[0]
    dict_demandas[n0] = round(dict_demandas[n0] + diferencia, 2)
    G.nodes[n0]["demanda_kg"] = dict_demandas[n0]

elif diferencia < 0:
    # sobra basura: resto repartiendo desde los que mÃ¡s tienen
    exceso = -diferencia
    nodos_ordenados = sorted(nodos_clientes, key=lambda n: dict_demandas[n], reverse=True)

    for nodo in nodos_ordenados:
        if exceso <= 0:
            break
        quitar = min(dict_demandas[nodo], exceso)
        dict_demandas[nodo] = round(dict_demandas[nodo] - quitar, 2)
        G.nodes[nodo]["demanda_kg"] = dict_demandas[nodo]
        exceso = round(exceso - quitar, 2)

    if exceso > 0:
        print(f"âš ï¸ Aviso: no se pudo ajustar todo el exceso ({exceso} kg).")

# (Opcional) micro-ajuste final por redondeos (ya deberÃ­a ser 0.00 casi siempre)
residual = round(TOTAL_BASURA_KG - sum(dict_demandas.values()), 2)
if residual != 0:
    n0 = nodos_clientes[0]
    dict_demandas[n0] = max(0.0, round(dict_demandas[n0] + residual, 2))
    G.nodes[n0]["demanda_kg"] = dict_demandas[n0]

# ---------------------------------------------------------
# G) EstadÃ­sticas
# ---------------------------------------------------------
print("\n--- ESTADÃSTICAS DE GENERACIÃ“N DE BASURA ---")
print(f"Total Basura: {sum(dict_demandas.values()):.2f} kg (Objetivo: {TOTAL_BASURA_KG})")
print(f"Nodo con MENOS basura: {min(dict_demandas.values()):.2f} kg (Residencial)")
print(f"Nodo con MÃS basura:   {max(dict_demandas.values()):.2f} kg (Hotspot)")
print(f"Promedio: {np.mean(list(dict_demandas.values())):.2f} kg")
print("Tipos de nodo:", pd.Series(list(tipos_basura_nodos.values())).value_counts().to_dict())

top_3 = sorted(dict_demandas.items(), key=lambda x: x[1], reverse=True)[:3]
print(f"\nTop 3 Hotspots: {top_3}")

# ---------------------------------------------------------
# H) Usar salida oficial del pipeline de compactacion
# ---------------------------------------------------------
PIPELINE_COMPACTADOS_PATH = "clientes_compactados.gpkg"
PIPELINE_COMPACTADOS_LAYER = "clientes"

if not Path(PIPELINE_COMPACTADOS_PATH).exists():
    raise FileNotFoundError(
        "No existe clientes_compactados.gpkg. Ejecuta primero pipeline_compactación.py "
        "sin modificarlo para generar la capa oficial de clientes compactados."
    )

gdf_compactados = gpd.read_file(PIPELINE_COMPACTADOS_PATH, layer=PIPELINE_COMPACTADOS_LAYER)
if "id_nodo" not in gdf_compactados.columns or "demanda_kg" not in gdf_compactados.columns:
    raise ValueError("clientes_compactados.gpkg debe tener columnas id_nodo y demanda_kg en layer='clientes'.")

nodos_compactados = []
dict_demandas_compactadas = {}
for _, row in gdf_compactados.iterrows():
    try:
        nodo = int(row["id_nodo"])
        demanda = float(row["demanda_kg"])
    except Exception:
        continue
    if nodo in G.nodes and demanda > 0:
        nodos_compactados.append(nodo)
        dict_demandas_compactadas[nodo] = round(demanda, 2)
        G.nodes[nodo]["demanda_kg"] = round(demanda, 2)
        if "clientes_agrupados" in row:
            try:
                G.nodes[nodo]["clientes_agrupados"] = int(row["clientes_agrupados"])
            except Exception:
                pass

if not nodos_compactados:
    raise ValueError("La capa clientes del pipeline no contiene clientes compactados utilizables.")

nodos_clientes = nodos_compactados
dict_demandas = dict_demandas_compactadas

print("\n--- CLIENTES COMPACTADOS DEL PIPELINE ---")
print(f"Clientes compactados usados: {len(nodos_clientes)}")
print(f"Demanda compactada total: {sum(dict_demandas.values()):.2f} kg")

# CELDA 3 (COINCIDE CON CELDA 6): Matriz OD DISTANCIAS (m) + helpers de TIEMPO por tramo
import numpy as np
import networkx as nx

# -----------------------------
# Velocidades del escenario (km/h)
# -----------------------------
V_ESTACION_A_PRIMERO = VELOCIDAD_ACERCAMIENTO_KMH
V_RECOLECCION        = VELOCIDAD_RECOLECCION_KMH
V_ULTIMO_A_DEPOSITO  = VELOCIDAD_TRANSPORTE_KMH
V_DEPOSITO_A_EST     = VELOCIDAD_RETORNO_KMH

# (Debe coincidir con CELDA 6)
TIEMPO_RECOLECCION_POR_NODO = TIEMPO_PARADA_SEG  # segundos

def vel_mps(vel_kmh: float) -> float:
    return vel_kmh * 1000.0 / 3600.0

def tiempo_segundos(dist_m_val, vel_kmh):
    """Convierte distancia (m) y velocidad (km/h) a tiempo (s)."""
    if dist_m_val is None or not np.isfinite(dist_m_val):
        return np.inf
    v = vel_mps(vel_kmh)
    return dist_m_val / v if v > 0 else np.inf

# -----------------------------
# 1) Definir nodos importantes
# -----------------------------
estacion = id_estacion
deposito = id_relleno
clientes = list(nodos_clientes)

lista_lugares = [estacion, deposito] + clientes
n = len(lista_lugares)
idx = {node: i for i, node in enumerate(lista_lugares)}

print(f"Calculando matriz de DISTANCIAS por calles entre {n} puntos (weight='length', grafo dirigido)...")

# -----------------------------
# 2) Matriz de distancias mÃ­nimas (m) por OSM
# -----------------------------
dist_m = np.full((n, n), np.inf, dtype=float)

for k, origen in enumerate(lista_lugares, 1):
    d = nx.single_source_dijkstra_path_length(G_RUTEO, origen, weight="length")
    i = idx[origen]
    for destino, j in idx.items():
        dist_m[i, j] = d.get(destino, np.inf)

    if k % 50 == 0:
        print(f"  procesados {k}/{n} orÃ­genes...")

print("âœ… Matriz de distancias lista.")

# -----------------------------
# 3) Helpers D() y T() (esto es lo que usa CELDA 6)
# -----------------------------
def D(a, b):
    """Distancia mÃ­nima (m) entre nodos a y b."""
    return dist_m[idx[a], idx[b]]

def T(a, b, vel_kmh):
    """Tiempo (s) entre a y b aplicando velocidad por tramo."""
    return tiempo_segundos(D(a, b), vel_kmh)

# -----------------------------
# 4) Funciones de tiempo por viaje (COINCIDE con la lÃ³gica de CELDA 6)
# -----------------------------
def tiempo_viaje_s(ruta_clientes, origen_es_estacion=True,
                   incluir_recoleccion=True,
                   estacion=estacion, deposito=deposito):
    """
    Tiempo de un viaje (SIN retorno final a estaciÃ³n), exactamente como CELDA 6:
    - AproximaciÃ³n (origen->primer cliente) a 40 km/h
    - Entre clientes a 10 km/h
    - RecolecciÃ³n por nodo (opcional): 60s por parada (igual que CELDA 6)
    - Ãšltimo cliente -> depÃ³sito a 30 km/h
    """
    if not ruta_clientes:
        return np.inf, {"error": "Ruta vacÃ­a"}

    primer = ruta_clientes[0]
    ultimo = ruta_clientes[-1]

    detalle = {}

    # 1) AproximaciÃ³n (40)
    origen_nodo = estacion if origen_es_estacion else deposito
    t_aprox = T(origen_nodo, primer, V_ESTACION_A_PRIMERO)

    # 2) Interno (10) + recolecciÃ³n
    t_interno = 0.0
    if incluir_recoleccion:
        # En CELDA 6: suma 1 vez por cada nodo visitado
        t_interno += TIEMPO_RECOLECCION_POR_NODO  # primer nodo

    for a, b in zip(ruta_clientes[:-1], ruta_clientes[1:]):
        t_interno += T(a, b, V_RECOLECCION)
        if incluir_recoleccion:
            t_interno += TIEMPO_RECOLECCION_POR_NODO

    # 3) Descarga (30)
    t_desc = T(ultimo, deposito, V_ULTIMO_A_DEPOSITO)

    total = t_aprox + t_interno + t_desc

    detalle["aprox_s"] = t_aprox
    detalle["interno_s"] = t_interno
    detalle["descarga_s"] = t_desc
    detalle["total_s"] = total
    detalle["total_min"] = total / 60.0

    return total, detalle

def tiempo_fin_turno_s(estacion=estacion, deposito=deposito):
    """Retorno final depÃ³sito -> estaciÃ³n (40 km/h)."""
    return T(deposito, estacion, V_DEPOSITO_A_EST)

# -----------------------------
# 5) Prueba rÃ¡pida (solo viaje + retorno final aparte)
# -----------------------------
ruta_ejemplo = clientes[:5]
t_viaje, det = tiempo_viaje_s(ruta_ejemplo, origen_es_estacion=True, incluir_recoleccion=True)

print("\n--- PRUEBA VIAJE EJEMPLO (sin retorno final) ---")
print("Clientes:", ruta_ejemplo)
print(f"Tiempo viaje: {det['total_min']:.2f} min")
print("Detalle (min):")
print(f"  Aprox (40):     {det['aprox_s']/60:.2f}")
print(f"  Interno (10)+rec: {det['interno_s']/60:.2f}")
print(f"  Descarga (30):  {det['descarga_s']/60:.2f}")

t_fin = tiempo_fin_turno_s()
print(f"\nRetorno final (DepÃ³sito->EstaciÃ³n, 40): {t_fin/60:.2f} min")

# CELDA 4: Clarke & Wright usando DISTANCIAS por calles (metros) + tiempos compatibles con CELDA 6
import numpy as np

# (Debe coincidir con CELDA 3 / CELDA 6)
V_ESTACION_A_PRIMERO = VELOCIDAD_ACERCAMIENTO_KMH
V_RECOLECCION        = VELOCIDAD_RECOLECCION_KMH
V_ULTIMO_A_DEPOSITO  = VELOCIDAD_TRANSPORTE_KMH
V_DEPOSITO_A_EST     = VELOCIDAD_RETORNO_KMH
TIEMPO_RECOLECCION_POR_NODO = TIEMPO_PARADA_SEG  # s

def tiempo_segundos(dist_m, vel_kmh):
    if dist_m is None or not np.isfinite(dist_m):
        return np.inf
    vel_mps = vel_kmh * 1000.0 / 3600.0
    return dist_m / vel_mps if vel_mps > 0 else np.inf

def D(dist_matriz, idx, a, b):
    """Distancia mÃ­nima (m) entre a y b desde dist_m."""
    return dist_matriz[idx[a], idx[b]]

# =========================================================
# 1) AHORROS Clarke & Wright (distancia)
# =========================================================
def calcular_ahorros_dist(nodos, dist_matriz, idx, deposito_id):
    """
    Savings clÃ¡sico:
      s(i,j) = d(i,dep) + d(dep,j) - d(i,j)
    usando DISTANCIAS por calles (m).
    """
    ahorros = []
    for i in nodos:
        for j in nodos:
            if i == j:
                continue

            d_i_dep = D(dist_matriz, idx, i, deposito_id)
            d_dep_j = D(dist_matriz, idx, deposito_id, j)
            d_i_j   = D(dist_matriz, idx, i, j)

            if not (np.isfinite(d_i_dep) and np.isfinite(d_dep_j) and np.isfinite(d_i_j)):
                continue

            saving = (d_i_dep + d_dep_j) - d_i_j
            if saving > 0:
                ahorros.append({'i': i, 'j': j, 'saving': saving})

    ahorros.sort(key=lambda x: x['saving'], reverse=True)
    return ahorros

# =========================================================
# 2) EJECUTAR Clarke & Wright (distancia) con restricciÃ³n de CAPACIDAD
# =========================================================
def ejecutar_clarke_wright_dist(nodos_clientes, dict_demanda, dist_matriz, idx, deposito_id, max_capacidad):
    """
    Devuelve rutas como:
      [{'camino':[c1,c2,...], 'carga':...}, ...]
    """
    rutas = {}
    for nodo in nodos_clientes:
        rutas[nodo] = {
            'camino': [nodo],
            'carga': float(dict_demanda.get(nodo, 0.0)),
        }

    lista_ahorros = calcular_ahorros_dist(nodos_clientes, dist_matriz, idx, deposito_id)
    print(f"Posibles uniones calculadas: {len(lista_ahorros)}")

    for s in lista_ahorros:
        i, j = s['i'], s['j']

        ruta_i_id = None
        ruta_j_id = None

        # i debe ser FINAL de su ruta, j debe ser INICIO de su ruta (C&W clÃ¡sico)
        for r_id, datos in rutas.items():
            if datos['camino'][-1] == i:
                ruta_i_id = r_id
            if datos['camino'][0] == j:
                ruta_j_id = r_id

        if ruta_i_id and ruta_j_id and (ruta_i_id != ruta_j_id):
            carga_total = rutas[ruta_i_id]['carga'] + rutas[ruta_j_id]['carga']
            if carga_total <= max_capacidad:
                rutas[ruta_i_id]['camino'] = rutas[ruta_i_id]['camino'] + rutas[ruta_j_id]['camino']
                rutas[ruta_i_id]['carga']  = carga_total
                del rutas[ruta_j_id]

    return list(rutas.values())

# =========================================================
# 3) TIEMPOS (COMPATIBLES CON CELDA 6)
# =========================================================
def tiempo_viaje_desde_dist_s(ruta_clientes, dist_matriz, idx, estacion_id, deposito_id,
                             origen_es_estacion=True,
                             incluir_recoleccion=True):
    """
    Tiempo de UN VIAJE (sin retorno final a estaciÃ³n), igual que CELDA 6:
      - Origen (estaciÃ³n si primer viaje, depÃ³sito si no) -> primer cliente: 40
      - Entre clientes: 10 + 60s por parada (opcional)
      - Ãšltimo cliente -> depÃ³sito: 30
    """
    if not ruta_clientes:
        return np.inf

    total = 0.0

    # 1) AproximaciÃ³n (40)
    origen = estacion_id if origen_es_estacion else deposito_id
    total += tiempo_segundos(D(dist_matriz, idx, origen, ruta_clientes[0]), V_ESTACION_A_PRIMERO)

    # 2) Interno (10) + recolecciÃ³n
    if incluir_recoleccion:
        total += TIEMPO_RECOLECCION_POR_NODO  # primera parada

    for a, b in zip(ruta_clientes[:-1], ruta_clientes[1:]):
        total += tiempo_segundos(D(dist_matriz, idx, a, b), V_RECOLECCION)
        if incluir_recoleccion:
            total += TIEMPO_RECOLECCION_POR_NODO

    # 3) Descarga (30)
    total += tiempo_segundos(D(dist_matriz, idx, ruta_clientes[-1], deposito_id), V_ULTIMO_A_DEPOSITO)

    return total

def tiempo_fin_turno_s(dist_matriz, idx, deposito_id, estacion_id):
    """Retorno final depÃ³sito -> estaciÃ³n (40)."""
    return tiempo_segundos(D(dist_matriz, idx, deposito_id, estacion_id), V_DEPOSITO_A_EST)

print("Funciones C&W (distancia) compiladas y tiempos alineados con CELDA 6 âœ…")

# CELDA 4: Clarke & Wright usando DISTANCIAS por calles (metros) + tiempos compatibles con CELDA 6
import numpy as np

# (Debe coincidir con CELDA 3 / CELDA 6)
V_ESTACION_A_PRIMERO = VELOCIDAD_ACERCAMIENTO_KMH
V_RECOLECCION        = VELOCIDAD_RECOLECCION_KMH
V_ULTIMO_A_DEPOSITO  = VELOCIDAD_TRANSPORTE_KMH
V_DEPOSITO_A_EST     = VELOCIDAD_RETORNO_KMH
TIEMPO_RECOLECCION_POR_NODO = TIEMPO_PARADA_SEG  # s

def tiempo_segundos(dist_m, vel_kmh):
    if dist_m is None or not np.isfinite(dist_m):
        return np.inf
    vel_mps = vel_kmh * 1000.0 / 3600.0
    return dist_m / vel_mps if vel_mps > 0 else np.inf

def D(dist_matriz, idx, a, b):
    """Distancia mÃ­nima (m) entre a y b desde dist_m."""
    return dist_matriz[idx[a], idx[b]]

# =========================================================
# 1) AHORROS Clarke & Wright (distancia)
# =========================================================
def calcular_ahorros_dist(nodos, dist_matriz, idx, deposito_id):
    """
    Savings clÃ¡sico:
      s(i,j) = d(i,dep) + d(dep,j) - d(i,j)
    usando DISTANCIAS por calles (m).
    """
    ahorros = []
    for i in nodos:
        for j in nodos:
            if i == j:
                continue

            d_i_dep = D(dist_matriz, idx, i, deposito_id)
            d_dep_j = D(dist_matriz, idx, deposito_id, j)
            d_i_j   = D(dist_matriz, idx, i, j)

            if not (np.isfinite(d_i_dep) and np.isfinite(d_dep_j) and np.isfinite(d_i_j)):
                continue

            saving = (d_i_dep + d_dep_j) - d_i_j
            if saving > 0:
                ahorros.append({'i': i, 'j': j, 'saving': saving})

    ahorros.sort(key=lambda x: x['saving'], reverse=True)
    return ahorros

# =========================================================
# 2) EJECUTAR Clarke & Wright (distancia) con restricciÃ³n de CAPACIDAD
# =========================================================
def ejecutar_clarke_wright_dist(nodos_clientes, dict_demanda, dist_matriz, idx, deposito_id, max_capacidad):
    """
    Devuelve rutas como:
      [{'camino':[c1,c2,...], 'carga':...}, ...]
    """
    rutas = {}
    for nodo in nodos_clientes:
        rutas[nodo] = {
            'camino': [nodo],
            'carga': float(dict_demanda.get(nodo, 0.0)),
        }

    lista_ahorros = calcular_ahorros_dist(nodos_clientes, dist_matriz, idx, deposito_id)
    print(f"Posibles uniones calculadas: {len(lista_ahorros)}")

    for s in lista_ahorros:
        i, j = s['i'], s['j']

        ruta_i_id = None
        ruta_j_id = None

        # i debe ser FINAL de su ruta, j debe ser INICIO de su ruta (C&W clÃ¡sico)
        for r_id, datos in rutas.items():
            if datos['camino'][-1] == i:
                ruta_i_id = r_id
            if datos['camino'][0] == j:
                ruta_j_id = r_id

        if ruta_i_id and ruta_j_id and (ruta_i_id != ruta_j_id):
            carga_total = rutas[ruta_i_id]['carga'] + rutas[ruta_j_id]['carga']
            if carga_total <= max_capacidad:
                rutas[ruta_i_id]['camino'] = rutas[ruta_i_id]['camino'] + rutas[ruta_j_id]['camino']
                rutas[ruta_i_id]['carga']  = carga_total
                del rutas[ruta_j_id]

    return list(rutas.values())

# =========================================================
# 3) TIEMPOS (COMPATIBLES CON CELDA 6)
# =========================================================
def tiempo_viaje_desde_dist_s(ruta_clientes, dist_matriz, idx, estacion_id, deposito_id,
                             origen_es_estacion=True,
                             incluir_recoleccion=True):
    """
    Tiempo de UN VIAJE (sin retorno final a estaciÃ³n), igual que CELDA 6:
      - Origen (estaciÃ³n si primer viaje, depÃ³sito si no) -> primer cliente: 40
      - Entre clientes: 10 + 60s por parada (opcional)
      - Ãšltimo cliente -> depÃ³sito: 30
    """
    if not ruta_clientes:
        return np.inf

    total = 0.0

    # 1) AproximaciÃ³n (40)
    origen = estacion_id if origen_es_estacion else deposito_id
    total += tiempo_segundos(D(dist_matriz, idx, origen, ruta_clientes[0]), V_ESTACION_A_PRIMERO)

    # 2) Interno (10) + recolecciÃ³n
    if incluir_recoleccion:
        total += TIEMPO_RECOLECCION_POR_NODO  # primera parada

    for a, b in zip(ruta_clientes[:-1], ruta_clientes[1:]):
        total += tiempo_segundos(D(dist_matriz, idx, a, b), V_RECOLECCION)
        if incluir_recoleccion:
            total += TIEMPO_RECOLECCION_POR_NODO

    # 3) Descarga (30)
    total += tiempo_segundos(D(dist_matriz, idx, ruta_clientes[-1], deposito_id), V_ULTIMO_A_DEPOSITO)

    return total

def tiempo_fin_turno_s(dist_matriz, idx, deposito_id, estacion_id):
    """Retorno final depÃ³sito -> estaciÃ³n (40)."""
    return tiempo_segundos(D(dist_matriz, idx, deposito_id, estacion_id), V_DEPOSITO_A_EST)

print("Funciones C&W (distancia) compiladas y tiempos alineados con CELDA 6 âœ…")

# ---------------------------------------------------------
# 4) Materializar lista_viajes para ejecuciÃ³n local
# ---------------------------------------------------------
PARAMETROS_OPERATIVOS = {
    "num_vehiculos": NUM_VEHICULOS_MAX,
    "capacidad_max_kg": CAPACIDAD_MAXIMA_CAMION_KG,
    "capacidad_min_kg": 0.0,
    "velocidad_acercamiento_kmh": VELOCIDAD_ACERCAMIENTO_KMH,
    "velocidad_recoleccion_kmh": VELOCIDAD_RECOLECCION_KMH,
    "velocidad_transporte_kmh": VELOCIDAD_TRANSPORTE_KMH,
    "velocidad_retorno_kmh": VELOCIDAD_RETORNO_KMH,
    "personas_por_camion": NUMERO_RECOLECTORES_CAMION + NUMERO_CHOFER_CAMION,
    "choferes": NUMERO_CHOFER_CAMION,
    "obreros": NUMERO_RECOLECTORES_CAMION,
    "obreros_min": 3,
    "sueldo_recolector_usd": SUELDO_RECOLECTORES_USD,
    "sueldo_chofer_usd": SUELDO_CHOFER_USD,
    "precio_diesel_usd_gal": PRECIO_DIESEL_USD_GAL,
    "rendimiento_km_gal": RENDIMIENTO_KM_GAL,
    "horario_inicio": "06:00",
    "horario_fin": "24:00",
    "almuerzo_inicio": "13:00",
    "almuerzo_fin": "14:00",
    "horario_turno_manana": ("06:30", "13:00"),
    "horario_turno_tarde": ("13:00", "17:00"),
    "horario_desalojo_vespertino": "19:00",
    "ventana_desalojo_tarde": ("13:00", "17:00"),
    "ventana_desalojo_vespertino": ("19:00", "20:00"),
    "receso_nocturno_inicio": "20:00",
    "receso_nocturno_fin": "21:00",
    "sectores_urbanos_total": 10,
    "sectores_manana": 5,
    "sectores_noche": 5,
    "zonas_criticas": ["Rafael Maria Arizaga", "Heroes de Verdeloma", "Juan Montalvo", "Huayna Capac"],
    "horas_pico": [("15:00", "19:00"), ("20:00", "24:00")],
    "dia_critico": "viernes",
    "costo_min_usd": 90.0,
    "costo_promedio_min_usd": 150.0,
    "costo_promedio_max_usd": 190.0,
    "costo_max_usd": 220.0,
    "distancia_camion_dia_km": 70.0,
    "frecuencia_recorridos_dia": 2,
    "dias_operacion_anual": 365,
}

NUM_VEHICULOS = PARAMETROS_OPERATIVOS["num_vehiculos"]
CAPACIDAD_MAXIMA_KG = float(globals().get("CAPACIDAD_MAXIMA_KG", PARAMETROS_OPERATIVOS["capacidad_max_kg"]))
CAPACIDAD_MINIMA_KG = PARAMETROS_OPERATIVOS["capacidad_min_kg"]
V_ESTACION_A_PRIMERO = PARAMETROS_OPERATIVOS["velocidad_acercamiento_kmh"]
V_RECOLECCION = PARAMETROS_OPERATIVOS["velocidad_recoleccion_kmh"]
V_ULTIMO_A_DEPOSITO = PARAMETROS_OPERATIVOS["velocidad_transporte_kmh"]
V_DEPOSITO_A_EST = PARAMETROS_OPERATIVOS["velocidad_retorno_kmh"]
PESO_AHORRO_DIST = 0.60
PESO_AHORRO_TIEMPO = 0.40
NUM_ZONAS_CLUSTER = max(
    1,
    min(
        NUM_VEHICULOS,
        int(np.ceil(sum(float(v) for v in dict_demandas.values()) / CAPACIDAD_MAXIMA_KG)),
    ),
)

def distancia_ruta_interna_m(camino, dist_matriz, idx):
    total = 0.0
    for a, b in zip(camino[:-1], camino[1:]):
        d = D(dist_matriz, idx, a, b)
        if not np.isfinite(d):
            return np.inf
        total += float(d)
    return total

def distancia_viaje_total_m(camino, dist_matriz, idx, estacion_id, deposito_id, origen_es_estacion=True):
    if not camino:
        return np.inf
    origen = estacion_id if origen_es_estacion else deposito_id
    total = D(dist_matriz, idx, origen, camino[0])
    total += distancia_ruta_interna_m(camino, dist_matriz, idx)
    total += D(dist_matriz, idx, camino[-1], deposito_id)
    return float(total) if np.isfinite(total) else np.inf

def metricas_rutas(rutas, dist_matriz, idx, estacion_id, deposito_id):
    dist_total = 0.0
    tiempo_total = 0.0
    carga_total = 0.0
    paradas = 0
    validas = 0
    for r in rutas:
        camino = list(r.get("camino", []))
        if not camino:
            continue
        d = distancia_viaje_total_m(camino, dist_matriz, idx, estacion_id, deposito_id, True)
        t = tiempo_viaje_desde_dist_s(camino, dist_matriz, idx, estacion_id, deposito_id, True, True)
        if np.isfinite(d) and np.isfinite(t):
            dist_total += d
            tiempo_total += t
            validas += 1
        carga_total += float(r.get("carga", 0.0))
        paradas += len(camino)
    return {
        "rutas": len(rutas),
        "rutas_validas": validas,
        "paradas": paradas,
        "carga_kg": carga_total,
        "distancia_km": dist_total / 1000.0,
        "tiempo_h": tiempo_total / 3600.0,
        "kg_por_km": carga_total / (dist_total / 1000.0) if dist_total > 0 else np.nan,
    }

def kmeans_zonas(nodos, k, max_iter=60, seed=7):
    if not nodos:
        return {}
    k = max(1, min(int(k), len(nodos)))
    coords = np.array([[G.nodes[n]["x"], G.nodes[n]["y"]] for n in nodos], dtype=float)
    scale = coords.std(axis=0)
    scale[scale == 0] = 1.0
    X = (coords - coords.mean(axis=0)) / scale
    rng = np.random.default_rng(seed)
    centroides = X[rng.choice(len(X), size=k, replace=False)]
    labels = np.zeros(len(X), dtype=int)
    for _ in range(max_iter):
        distancias = ((X[:, None, :] - centroides[None, :, :]) ** 2).sum(axis=2)
        nuevos = distancias.argmin(axis=1)
        if np.array_equal(labels, nuevos):
            break
        labels = nuevos
        for c in range(k):
            mask = labels == c
            if mask.any():
                centroides[c] = X[mask].mean(axis=0)
    zonas = {}
    for nodo, zona in zip(nodos, labels):
        zonas.setdefault(int(zona) + 1, []).append(nodo)
    return zonas

def calcular_ahorros_hibridos(nodos, dist_matriz, idx, deposito_id):
    candidatos = []
    for i in nodos:
        for j in nodos:
            if i == j:
                continue
            d_i_dep = D(dist_matriz, idx, i, deposito_id)
            d_dep_j = D(dist_matriz, idx, deposito_id, j)
            d_i_j = D(dist_matriz, idx, i, j)
            if not (np.isfinite(d_i_dep) and np.isfinite(d_dep_j) and np.isfinite(d_i_j)):
                continue
            ahorro_dist = (d_i_dep + d_dep_j) - d_i_j
            ahorro_tiempo = (
                tiempo_segundos(d_i_dep, V_ULTIMO_A_DEPOSITO)
                + tiempo_segundos(d_dep_j, V_ESTACION_A_PRIMERO)
                - tiempo_segundos(d_i_j, V_RECOLECCION)
            )
            if ahorro_dist > 0 or ahorro_tiempo > 0:
                candidatos.append({"i": i, "j": j, "ahorro_dist_m": float(ahorro_dist), "ahorro_tiempo_s": float(ahorro_tiempo)})
    max_d = max([abs(c["ahorro_dist_m"]) for c in candidatos] + [1.0])
    max_t = max([abs(c["ahorro_tiempo_s"]) for c in candidatos] + [1.0])
    for c in candidatos:
        c["saving"] = PESO_AHORRO_DIST * (c["ahorro_dist_m"] / max_d) + PESO_AHORRO_TIEMPO * (c["ahorro_tiempo_s"] / max_t)
    candidatos.sort(key=lambda x: x["saving"], reverse=True)
    return candidatos

def ejecutar_clarke_wright_hibrido(nodos_zona, dict_demanda, dist_matriz, idx, deposito_id, max_capacidad):
    rutas = {nodo: {"camino": [nodo], "carga": float(dict_demanda.get(nodo, 0.0))} for nodo in nodos_zona}
    lista_ahorros = calcular_ahorros_hibridos(nodos_zona, dist_matriz, idx, deposito_id)
    for s in lista_ahorros:
        i, j = s["i"], s["j"]
        ruta_i_id = None
        ruta_j_id = None
        for r_id, datos in rutas.items():
            if datos["camino"][-1] == i:
                ruta_i_id = r_id
            if datos["camino"][0] == j:
                ruta_j_id = r_id
        if ruta_i_id is not None and ruta_j_id is not None and ruta_i_id != ruta_j_id:
            carga_total = rutas[ruta_i_id]["carga"] + rutas[ruta_j_id]["carga"]
            if carga_total <= max_capacidad:
                rutas[ruta_i_id]["camino"] = rutas[ruta_i_id]["camino"] + rutas[ruta_j_id]["camino"]
                rutas[ruta_i_id]["carga"] = carga_total
                del rutas[ruta_j_id]
    return list(rutas.values())

def two_opt_ruta(camino, dist_matriz, idx, max_iter=100):
    if len(camino) < 4:
        return camino, 0.0
    mejor = list(camino)
    mejor_dist = distancia_ruta_interna_m(mejor, dist_matriz, idx)
    mejora_total = 0.0
    mejoro = True
    iteraciones = 0
    while mejoro and iteraciones < max_iter:
        mejoro = False
        iteraciones += 1
        for i in range(0, len(mejor) - 2):
            for j in range(i + 2, len(mejor)):
                candidato = mejor[:i + 1] + list(reversed(mejor[i + 1:j + 1])) + mejor[j + 1:]
                d_candidato = distancia_ruta_interna_m(candidato, dist_matriz, idx)
                if d_candidato + 1e-6 < mejor_dist:
                    mejora_total += mejor_dist - d_candidato
                    mejor = candidato
                    mejor_dist = d_candidato
                    mejoro = True
                    break
            if mejoro:
                break
    return mejor, mejora_total

def aplicar_two_opt(rutas, dist_matriz, idx):
    rutas_opt = []
    mejora_total = 0.0
    for r in rutas:
        nueva = dict(r)
        camino_opt, mejora = two_opt_ruta(list(r.get("camino", [])), dist_matriz, idx)
        nueva["camino"] = camino_opt
        nueva["mejora_2opt_m"] = float(mejora)
        mejora_total += float(mejora)
        rutas_opt.append(nueva)
    return rutas_opt, mejora_total

def ejecutar_clarke_wright_optimizado(nodos_clientes, dict_demanda, dist_matriz, idx, estacion_id, deposito_id, num_zonas):
    """
    Flujo principal:
      1) Clustering espacial inicial crea zonas operativas.
      2) Clarke & Wright optimiza solo dentro de cada zona.
      3) 2-opt mejora el orden interno sin mezclar zonas.
    """
    zonas = kmeans_zonas(nodos_clientes, num_zonas)
    rutas_finales = []
    mejora_total_2opt_m = 0.0

    for zona_id, nodos_zona in sorted(zonas.items()):
        rutas_zona = ejecutar_clarke_wright_hibrido(
            nodos_zona,
            dict_demanda,
            dist_matriz,
            idx,
            deposito_id,
            CAPACIDAD_MAXIMA_KG,
        )
        rutas_zona, mejora_zona_m = aplicar_two_opt(rutas_zona, dist_matriz, idx)
        mejora_total_2opt_m += float(mejora_zona_m)

        for ruta in rutas_zona:
            ruta["zona"] = int(zona_id)
            rutas_finales.append(ruta)

    return rutas_finales, zonas, mejora_total_2opt_m

rutas_base_bryan = ejecutar_clarke_wright_dist(
    nodos_clientes=nodos_clientes,
    dict_demanda=dict_demandas,
    dist_matriz=dist_m,
    idx=idx,
    deposito_id=deposito,
    max_capacidad=CAPACIDAD_MAXIMA_KG,
)

metricas_base = metricas_rutas(rutas_base_bryan, dist_m, idx, estacion, deposito)
print(f"Zonas cluster por capacidad: {NUM_ZONAS_CLUSTER}")

rutas_clarke_wright, zonas_hibridas, mejora_2opt_m = ejecutar_clarke_wright_optimizado(
    nodos_clientes=nodos_clientes,
    dict_demanda=dict_demandas,
    dist_matriz=dist_m,
    idx=idx,
    estacion_id=estacion,
    deposito_id=deposito,
    num_zonas=NUM_ZONAS_CLUSTER,
)

metricas_hibrido = metricas_rutas(rutas_clarke_wright, dist_m, idx, estacion, deposito)
df_comparacion_algoritmos = pd.DataFrame([
    {"algoritmo": "Base Bryan - Clarke & Wright distancia", **metricas_base},
    {"algoritmo": "Clustering inicial + Clarke & Wright por zona + 2-opt", **metricas_hibrido},
])
df_comparacion_algoritmos["mejora_distancia_pct_vs_base"] = np.nan
df_comparacion_algoritmos["mejora_tiempo_pct_vs_base"] = np.nan
if metricas_base["distancia_km"] > 0:
    df_comparacion_algoritmos.loc[1, "mejora_distancia_pct_vs_base"] = 100 * (
        metricas_base["distancia_km"] - metricas_hibrido["distancia_km"]
    ) / metricas_base["distancia_km"]
if metricas_base["tiempo_h"] > 0:
    df_comparacion_algoritmos.loc[1, "mejora_tiempo_pct_vs_base"] = 100 * (
        metricas_base["tiempo_h"] - metricas_hibrido["tiempo_h"]
    ) / metricas_base["tiempo_h"]
df_comparacion_algoritmos.to_csv("comparacion_algoritmos.csv", index=False, encoding="utf-8-sig")

print("\n======================")
print("COMPARACION CLARKE & WRIGHT")
print("======================")
print(f"Zonas iniciales por clustering/capacidad: {len(zonas_hibridas)}")
print(f"Rutas generadas por Clarke & Wright zonal: {len(rutas_clarke_wright)}")
print(f"Mejora interna por 2-opt: {mejora_2opt_m/1000:.2f} km")
display(df_comparacion_algoritmos.round(2))

def construir_viaje_operativo(camino, carga, zona=None, subzona=None, motivo=None):
    if not camino:
        viaje = {
            "camino": [],
            "carga": carga,
            "valido": False,
            "motivo": motivo or "Ruta vacia",
            "tiempo_s": {
                "si_sale_estacion": np.inf,
                "si_sale_relleno": np.inf,
            },
            "dist_tramos_m": {
                "aprox_desde_estacion": np.inf,
                "aprox_desde_relleno": np.inf,
                "recoleccion": 0.0,
                "descarga": np.inf,
            },
            "zona": zona,
        }
        if subzona is not None:
            viaje["subzona"] = subzona
        return viaje

    d_aprox_est = D(dist_m, idx, estacion, camino[0])
    d_aprox_rel = D(dist_m, idx, deposito, camino[0])
    d_descarga = D(dist_m, idx, camino[-1], deposito)

    d_recoleccion = 0.0
    valido = True
    for a, b in zip(camino[:-1], camino[1:]):
        d_seg = D(dist_m, idx, a, b)
        if not np.isfinite(d_seg):
            valido = False
            d_recoleccion = np.inf
            break
        d_recoleccion += float(d_seg)

    t_est = tiempo_viaje_desde_dist_s(
        camino, dist_m, idx, estacion, deposito, origen_es_estacion=True, incluir_recoleccion=True
    )
    t_rel = tiempo_viaje_desde_dist_s(
        camino, dist_m, idx, estacion, deposito, origen_es_estacion=False, incluir_recoleccion=True
    )

    if not (np.isfinite(d_aprox_est) and np.isfinite(d_aprox_rel) and np.isfinite(d_descarga)):
        valido = False
    if not (np.isfinite(t_est) and np.isfinite(t_rel)):
        valido = False

    viaje = {
        "camino": camino,
        "carga": carga,
        "valido": bool(valido),
        "tiempo_s": {
            "si_sale_estacion": float(t_est),
            "si_sale_relleno": float(t_rel),
        },
        "dist_tramos_m": {
            "aprox_desde_estacion": float(d_aprox_est),
            "aprox_desde_relleno": float(d_aprox_rel),
            "recoleccion": float(d_recoleccion),
            "descarga": float(d_descarga),
        },
        "zona": zona,
    }
    if subzona is not None:
        viaje["subzona"] = subzona
    if motivo:
        viaje["motivo"] = motivo
    return viaje

def dividir_ruta_por_capacidad(ruta_info, capacidad_kg):
    camino = list(ruta_info.get("camino", []))
    zona = ruta_info.get("zona", None)
    partes = []
    parte_camino = []
    parte_carga = 0.0
    subzona = 1

    def cerrar_parte():
        nonlocal parte_camino, parte_carga, subzona
        if parte_camino:
            partes.append({
                "camino": parte_camino,
                "carga": round(float(parte_carga), 2),
                "zona": zona,
                "subzona": subzona,
            })
            subzona += 1
            parte_camino = []
            parte_carga = 0.0

    for nodo in camino:
        demanda_nodo = float(dict_demandas.get(nodo, 0.0))

        if demanda_nodo > capacidad_kg:
            cerrar_parte()
            restante = demanda_nodo
            while restante > 0:
                carga_parcial = min(restante, capacidad_kg)
                partes.append({
                    "camino": [nodo],
                    "carga": round(float(carga_parcial), 2),
                    "zona": zona,
                    "subzona": subzona,
                    "motivo": "Demanda de nodo dividida por capacidad",
                })
                subzona += 1
                restante = round(restante - carga_parcial, 2)
            continue

        if parte_carga + demanda_nodo > capacidad_kg:
            cerrar_parte()

        parte_camino.append(nodo)
        parte_carga += demanda_nodo

    cerrar_parte()
    return partes

lista_viajes = []
for ruta_info in rutas_clarke_wright:
    for parte in dividir_ruta_por_capacidad(ruta_info, CAPACIDAD_MAXIMA_KG):
        lista_viajes.append(construir_viaje_operativo(
            camino=list(parte.get("camino", [])),
            carga=float(parte.get("carga", 0.0)),
            zona=parte.get("zona", None),
            subzona=parte.get("subzona", None),
            motivo=parte.get("motivo", None),
        ))

def dividir_viaje_por_tiempo(viaje, max_tiempo_s):
    if not viaje.get("valido", True) or not viaje.get("camino"):
        return [viaje]
    if float(viaje.get("tiempo_s", {}).get("si_sale_estacion", np.inf)) <= max_tiempo_s:
        return [viaje]

    partes = []
    camino_actual = []
    carga_actual = 0.0
    subzona_base = viaje.get("subzona", 1)
    subzona = int(subzona_base) if isinstance(subzona_base, int) else 1

    def carga_nodo(nodo):
        return float(dict_demandas.get(nodo, 0.0))

    def construir_parte(camino, carga, subzona_id):
        return construir_viaje_operativo(
            camino=list(camino),
            carga=round(float(carga), 2),
            zona=viaje.get("zona", None),
            subzona=subzona_id,
            motivo="Ruta dividida por tiempo maximo",
        )

    for nodo in viaje["camino"]:
        demanda = carga_nodo(nodo)
        candidato_camino = camino_actual + [nodo]
        candidato_carga = carga_actual + demanda
        candidato = construir_parte(candidato_camino, candidato_carga, subzona)
        candidato_t = float(candidato.get("tiempo_s", {}).get("si_sale_estacion", np.inf))

        if camino_actual and (candidato_t > max_tiempo_s or candidato_carga > CAPACIDAD_MAXIMA_KG):
            partes.append(construir_parte(camino_actual, carga_actual, subzona))
            subzona += 1
            camino_actual = [nodo]
            carga_actual = demanda
        else:
            camino_actual = candidato_camino
            carga_actual = candidato_carga

    if camino_actual:
        partes.append(construir_parte(camino_actual, carga_actual, subzona))

    return partes

MAX_TIEMPO_SERVICIO_S = HORAS_TRABAJO_H * 3600.0
lista_viajes_tiempo = []
for viaje in lista_viajes:
    lista_viajes_tiempo.extend(dividir_viaje_por_tiempo(viaje, MAX_TIEMPO_SERVICIO_S))
lista_viajes = lista_viajes_tiempo

MIN_CARGA_VIAJE_KG = 0.60 * CAPACIDAD_MAXIMA_KG

def fusionar_viajes_livianos(viajes, min_carga_kg, max_capacidad_kg, max_tiempo_s):
    """Une viajes livianos cuando la fusion respeta capacidad y tiempo maximo."""
    viajes = [dict(v) for v in viajes]
    activo = [True] * len(viajes)
    cambio = True

    while cambio:
        cambio = False
        livianos = sorted(
            (
                i for i, v in enumerate(viajes)
                if activo[i]
                and v.get("valido", True)
                and float(v.get("carga", 0.0)) < min_carga_kg
            ),
            key=lambda i: float(viajes[i].get("carga", 0.0)),
        )

        for i in livianos:
            if not activo[i]:
                continue

            mejor = None
            for j, candidato_base in enumerate(viajes):
                if i == j or not activo[j] or not candidato_base.get("valido", True):
                    continue
                if viajes[i].get("zona", None) != candidato_base.get("zona", None):
                    continue

                carga_total = float(viajes[i].get("carga", 0.0)) + float(candidato_base.get("carga", 0.0))
                if carga_total > max_capacidad_kg + 0.01:
                    continue

                opciones = [
                    list(candidato_base.get("camino", [])) + list(viajes[i].get("camino", [])),
                    list(viajes[i].get("camino", [])) + list(candidato_base.get("camino", [])),
                ]
                for camino_candidato in opciones:
                    combinado = construir_viaje_operativo(
                        camino=camino_candidato,
                        carga=round(carga_total, 2),
                        zona=candidato_base.get("zona", viajes[i].get("zona", None)),
                        subzona=candidato_base.get("subzona", None),
                        motivo="Viajes fusionados para balancear carga",
                    )
                    tiempo_est = float(combinado.get("tiempo_s", {}).get("si_sale_estacion", np.inf))
                    if not combinado.get("valido", True) or tiempo_est > max_tiempo_s:
                        continue
                    score = (
                        min(carga_total, max_capacidad_kg) / max_capacidad_kg,
                        -abs(max_capacidad_kg - carga_total),
                        -tiempo_est,
                    )
                    if mejor is None or score > mejor[0]:
                        mejor = (score, j, combinado)

            if mejor is not None:
                _, j, combinado = mejor
                viajes[j] = combinado
                activo[i] = False
                cambio = True
                break

    fusionados = [v for v, ok in zip(viajes, activo) if ok]
    livianos_finales = [
        v for v in fusionados
        if v.get("valido", True) and float(v.get("carga", 0.0)) < min_carga_kg
    ]
    if livianos_finales:
        print(
            "Advertencia: "
            f"{len(livianos_finales)} viajes quedan bajo {min_carga_kg/1000:.1f} t "
            "porque no se pudieron fusionar sin exceder capacidad o 8h."
        )
    return fusionados

lista_viajes = fusionar_viajes_livianos(
    lista_viajes,
    MIN_CARGA_VIAJE_KG,
    CAPACIDAD_MAXIMA_KG,
    MAX_TIEMPO_SERVICIO_S,
)

sobrecargados = [v for v in lista_viajes if float(v.get("carga", 0.0)) > CAPACIDAD_MAXIMA_KG + 0.01]
if sobrecargados:
    raise ValueError(f"Hay {len(sobrecargados)} viajes sobre la capacidad maxima de {CAPACIDAD_MAXIMA_KG:.0f} kg.")

excedidos_tiempo = [
    v for v in lista_viajes
    if float(v.get("tiempo_s", {}).get("si_sale_estacion", 0.0)) > MAX_TIEMPO_SERVICIO_S + 1.0
]
if excedidos_tiempo:
    print(f"Advertencia: {len(excedidos_tiempo)} viajes individuales exceden 8h aun tras dividir; revisar conectividad/zona.")

print(f"Viajes Clarke & Wright generados: {len(lista_viajes)}")
print(f"Viajes vÃ¡lidos para asignaciÃ³n: {sum(1 for v in lista_viajes if v.get('valido'))}")


# CELDA 6: Asignacion generica de rutas/camiones, sin horarios por turno
import numpy as np

HORAS_TRABAJO = HORAS_TRABAJO_H * 3600  # segundos
HORAS_TRABAJO_MIN = HORAS_TRABAJO_MIN_H * 3600  # segundos
OPERACION_GENERICA = {
    "descarga": "fin",
    "estado_inicial_camion": "vacio",
    "estado_final_camion": "vacio_en_relleno",
    "descripcion": "Estacion -> Recoleccion -> Relleno",
}

# --------------------------
# Helpers de tiempo (igual)
# --------------------------
def tiempo_segundos(dist_m_val, vel_kmh):
    if dist_m_val is None or not np.isfinite(dist_m_val):
        return np.inf
    vel_mps = vel_kmh * 1000.0 / 3600.0
    return dist_m_val / vel_mps if vel_mps > 0 else np.inf

def D(a, b):
    return dist_m[idx[a], idx[b]]

def T(a, b, vel_kmh):
    return tiempo_segundos(D(a, b), vel_kmh)

V_DEPOSITO_A_EST = PARAMETROS_OPERATIVOS["velocidad_retorno_kmh"]
t_retorno_casa = T(id_relleno, id_estacion, V_DEPOSITO_A_EST)
print(f"Tiempo de seguridad (Relleno -> EstaciÃ³n): {t_retorno_casa/60:.2f} min")

if not np.isfinite(t_retorno_casa):
    print("âš ï¸ No hay camino Relleno -> EstaciÃ³n en la matriz de distancias.")
    print("   SoluciÃ³n tÃ­pica: recalcular dist_m con un grafo no dirigido (nx.Graph(G)).")

# ---------------------------------------------------------
# 1) Lista de zonas/sectores validos
# ---------------------------------------------------------
viajes_pendientes = [v for v in lista_viajes if v.get("valido", True) and v.get("camino", [])]
viajes_pendientes.sort(key=lambda v: (float(v.get("carga", 0.0)), len(v.get("camino", []))), reverse=True)

def distancia_interna_camino_m(camino):
    total = 0.0
    for a, b in zip(camino[:-1], camino[1:]):
        d = D(a, b)
        if not np.isfinite(d):
            return np.inf
        total += float(d)
    return total

def construir_viaje_asignado(fuente, origen_nodo):
    camino = list(fuente.get("camino", []))
    if not camino:
        return None
    primer = camino[0]
    ultimo = camino[-1]
    carga = float(fuente.get("carga", 0.0))
    if carga > CAPACIDAD_MAXIMA_KG + 0.01:
        return None

    d_recol_m = distancia_interna_camino_m(camino)
    t_recol_s = tiempo_segundos(d_recol_m, V_RECOLECCION) + len(camino) * TIEMPO_RECOLECCION_POR_NODO

    d_aprox = D(origen_nodo, primer)
    d_desc = D(ultimo, id_relleno)
    t_aprox = tiempo_segundos(d_aprox, V_ESTACION_A_PRIMERO)
    t_desc = tiempo_segundos(d_desc, V_ULTIMO_A_DEPOSITO)
    origen_txt = "Estacion" if int(origen_nodo) == int(id_estacion) else "Relleno"
    tramos = [
        {"tipo": "Aprox", "de": origen_txt, "a": "Recoleccion", "nodo_de": int(origen_nodo), "nodo_a": int(primer), "dur_s": t_aprox, "dist_m": d_aprox},
        {"tipo": "Recol", "de": "Recoleccion", "a": "Recoleccion", "nodo_de": int(primer), "nodo_a": int(ultimo), "dur_s": t_recol_s, "dist_m": d_recol_m},
        {"tipo": "Desc", "de": "Recoleccion", "a": "Relleno", "nodo_de": int(ultimo), "nodo_a": int(id_relleno), "dur_s": t_desc, "dist_m": d_desc},
    ]
    distancias = {"aprox_m": d_aprox, "recoleccion_m": d_recol_m, "descarga_m": d_desc, "cierre_m": 0.0}
    costos = {"aprox_s": t_aprox, "interno_s": t_recol_s, "descarga_s": t_desc, "cierre_s": 0.0}

    total_s = sum(float(t["dur_s"]) for t in tramos)
    total_m = sum(float(t["dist_m"]) for t in tramos)
    if not np.isfinite(total_s) or not np.isfinite(total_m):
        return None

    zonas = []
    if "zona" in fuente:
        zonas.append(int(fuente["zona"]))
    return {
        "nodos": camino,
        "carga": carga,
        "origen": origen_txt,
        "origen_nodo": int(origen_nodo),
        "fin_nodo": int(id_relleno),
        "modalidad_descarga": OPERACION_GENERICA["descarga"],
        "estado_inicial_camion": OPERACION_GENERICA["estado_inicial_camion"],
        "estado_final_camion": OPERACION_GENERICA["estado_final_camion"],
        "zonas": sorted(set(zonas)),
        "costos": costos,
        "distancias_m": distancias,
        "tramos_operativos": tramos,
        "ventana_desalojo": "Sin restriccion",
        "tiempo_productivo_s": float(total_s),
        "distancia_m": float(total_m),
    }

def origen_para_siguiente_viaje(camion):
    return id_estacion if len(camion.get("viajes", [])) == 0 else id_relleno

def zonas_de_camion(camion):
    zonas = set()
    for viaje in camion.get("viajes", []):
        for z in viaje.get("zonas", []) or []:
            zonas.add(int(z))
    return zonas

def construir_camion_desde_viajes(camion_id, viajes):
    for viaje in viajes:
        (viaje.get("costos", {}) or {})["balance_turno_s"] = 0.0

    tiempo_productivo_s = float(sum(v.get("tiempo_productivo_s", 0.0) for v in viajes))
    tiempo_total_s = tiempo_productivo_s
    distancia_total_m = float(sum(v.get("distancia_m", 0.0) for v in viajes))
    if not viajes:
        return None
    return {
        "id": int(camion_id),
        "vehiculo_id": int(camion_id),
        "descarga": OPERACION_GENERICA["descarga"],
        "estado_inicial_camion": OPERACION_GENERICA["estado_inicial_camion"],
        "estado_final_camion": OPERACION_GENERICA["estado_final_camion"],
        "descripcion_operacion": OPERACION_GENERICA["descripcion"],
        "viajes": viajes,
        "tiempo_total_s": tiempo_total_s,
        "tiempo_total_h": tiempo_total_s / 3600.0,
        "tiempo_productivo_s": tiempo_productivo_s,
        "tiempo_productivo_h": tiempo_productivo_s / 3600.0,
        "jornada_min_referencia_h": HORAS_TRABAJO_MIN_H,
        "distancia_total_m": distancia_total_m,
        "retorno_final": False,
    }

camiones_tmp = []
camion_id = 1
for fuente in viajes_pendientes:
    mejor_idx = None
    mejor_score = -np.inf
    for idx_camion, camion in enumerate(camiones_tmp):
        zonas_actuales = zonas_de_camion(camion)
        zona_fuente = fuente.get("zona", None)
        if zonas_actuales and zona_fuente is not None and int(zona_fuente) not in zonas_actuales:
            continue
        viaje_candidato = construir_viaje_asignado(fuente, origen_para_siguiente_viaje(camion))
        if viaje_candidato is None:
            continue
        tiempo_candidato = float(camion["tiempo_productivo_s"]) + float(viaje_candidato["tiempo_productivo_s"])
        if tiempo_candidato > HORAS_TRABAJO + 1.0:
            continue
        score = tiempo_candidato
        if score > mejor_score:
            mejor_score = score
            mejor_idx = idx_camion

    if mejor_idx is not None:
        camion = camiones_tmp[mejor_idx]
        viaje_asignado = construir_viaje_asignado(fuente, origen_para_siguiente_viaje(camion))
        camion["viajes"].append(viaje_asignado)
        actualizado = construir_camion_desde_viajes(camion["id"], camion["viajes"])
        camiones_tmp[mejor_idx] = actualizado
        continue

    if camion_id > NUM_VEHICULOS:
        raise ValueError(
            f"La solucion requiere mas de {NUM_VEHICULOS} camiones. "
            "Ajusta zonas/capacidad/tiempos o aumenta la flota disponible."
        )
    viaje_nuevo = construir_viaje_asignado(fuente, id_estacion)
    if viaje_nuevo is None:
        print("Viaje no enrutable; se omite una zona.")
        continue
    if viaje_nuevo["tiempo_productivo_s"] > HORAS_TRABAJO:
        print(f"Viaje {camion_id} excede 8h ({viaje_nuevo['tiempo_productivo_s']/3600.0:.2f}h). Se mantiene para no perder cobertura.")
    camiones_tmp.append(construir_camion_desde_viajes(camion_id, [viaje_nuevo]))
    camion_id += 1

camiones = camiones_tmp

servicios_sobrecargados = []
for camion in camiones:
    for i_viaje, viaje in enumerate(camion.get("viajes", []), start=1):
        carga_viaje = float(viaje.get("carga", 0.0))
        if carga_viaje > CAPACIDAD_MAXIMA_KG + 0.01:
            servicios_sobrecargados.append((camion.get("id"), i_viaje, carga_viaje))
if servicios_sobrecargados:
    raise ValueError(
        "Viajes sobre capacidad maxima de "
        f"{CAPACIDAD_MAXIMA_KG:.0f} kg: {servicios_sobrecargados}"
    )

for c in camiones:
    carga = sum(float(v.get("carga", 0.0)) for v in c["viajes"])
    print(f"\n--- Camion {c['vehiculo_id']} ---")
    print("Flujo por viaje: Estacion/Relleno -> Recoleccion -> Relleno")
    print(f"Viajes: {len(c['viajes'])} | Carga jornada: {carga:.2f} kg | Tiempo productivo: {c.get('tiempo_productivo_h', c['tiempo_total_h']):.2f} h")

vehiculos_fisicos = len(set(c['vehiculo_id'] for c in camiones))
if vehiculos_fisicos > NUM_VEHICULOS:
    raise ValueError(f"Se requieren {vehiculos_fisicos} camiones y el maximo disponible es {NUM_VEHICULOS}.")
print(f"\nRESUMEN FINAL: {sum(len(c.get('viajes', [])) for c in camiones)} viajes, {vehiculos_fisicos} camiones usados de {NUM_VEHICULOS} disponibles.")

# CELDA 7 (COMPLETA): Densidad poblacional real (hab/kmÂ²) por nodo usando raster de densidad + fallback vecindario
import geopandas as gpd
import pandas as pd
import numpy as np
import rasterio
from rasterio.mask import mask
from rasterio.windows import Window
from shapely.geometry import Point
from shapely.geometry import mapping

POP_RASTER_PATH = "ecu_pd_2020_1km.tif"
RADIO_M = 500  # buffer en metros (ajusta 200-800 segÃºn zona)

print("Calculando densidad poblacional (hab/kmÂ²) por nodo...")

# ---------------------------------------------------------
# A) Construir GeoDataFrame de puntos clientes (WGS84)
# ---------------------------------------------------------
gdf_pts = gpd.GeoDataFrame(
    [{
        "id_nodo": int(n),
        "demanda_kg": float(dict_demandas.get(n, 0.0)),
        "tipo_basura": str(tipos_basura_nodos.get(n, G.nodes[n].get("tipo_basura", "hogar_urbano"))),
        "peso_relativo_basura": float(pesos_nodos.get(n, G.nodes[n].get("peso_relativo_basura", 1.0))),
        "geometry": Point(G.nodes[n]['x'], G.nodes[n]['y'])
    } for n in nodos_clientes],
    crs="EPSG:4326"
)

print("  -> Puntos clientes:", len(gdf_pts))

# ---------------------------------------------------------
# B) Buffer en metros: reproyectar a UTM para Ã¡rea real
# ---------------------------------------------------------
utm_crs = gdf_pts.estimate_utm_crs()
gdf_m = gdf_pts.to_crs(utm_crs)
gdf_m["buffer"] = gdf_m.geometry.buffer(RADIO_M)

# Ãrea confiable (kmÂ²) desde UTM
area_km2 = (gdf_m["buffer"].area / 1e6).values  # kmÂ²

# ---------------------------------------------------------
# C) Helpers: promedio en buffer + fallback vecindario
# ---------------------------------------------------------
def nanmean_from_mask(src, geom, nodata):
    """Promedio de valores vÃ¡lidos dentro de un polÃ­gono (buffer)."""
    out_img, _ = mask(src, [mapping(geom)], crop=True)
    band = out_img[0].astype(float)
    if nodata is not None:
        band[band == nodata] = np.nan
    if np.all(np.isnan(band)):
        return np.nan
    return float(np.nanmean(band))

def densidad_vecindario(src, x, y, nodata, half_windows_px=(0, 1, 2, 3, 5, 8, 12, 20)):
    """
    Fallback: busca densidad vÃ¡lida alrededor del punto (x,y) en ventanas crecientes.
    half_windows_px=0 significa solo el pixel del punto.
    """
    # Convertir a fila/col
    row, col = src.index(x, y)

    for hw in half_windows_px:
        r0 = max(row - hw, 0)
        c0 = max(col - hw, 0)
        r1 = min(row + hw, src.height - 1)
        c1 = min(col + hw, src.width - 1)

        win = Window.from_slices((r0, r1 + 1), (c0, c1 + 1))
        arr = src.read(1, window=win).astype(float)

        if nodata is not None:
            arr[arr == nodata] = np.nan

        if not np.all(np.isnan(arr)):
            return float(np.nanmean(arr))

    return np.nan

# ---------------------------------------------------------
# D) Leer raster y calcular densidad/poblaciÃ³n por nodo
# ---------------------------------------------------------
densidades = []
poblaciones = []

with rasterio.open(POP_RASTER_PATH) as src:
    nodata = src.nodata

    # buffers al CRS del raster
    gdf_buf = gdf_m.set_geometry("buffer").to_crs(src.crs)
    # puntos al CRS del raster (para fallback vecindario)
    gdf_pts_r = gdf_pts.to_crs(src.crs)

    for geom_buf, pt, a_km2 in zip(gdf_buf.geometry, gdf_pts_r.geometry, area_km2):
        # 1) intento con buffer (promedio dentro del Ã¡rea)
        dens = np.nan
        try:
            dens = nanmean_from_mask(src, geom_buf, nodata)
        except Exception:
            dens = np.nan

        # 2) si buffer es NaN -> fallback vecindario (pixel cercano vÃ¡lido)
        if not np.isfinite(dens):
            dens = densidad_vecindario(src, pt.x, pt.y, nodata)

        # 3) poblaciÃ³n estimada (densidad hab/kmÂ² * Ã¡rea kmÂ²)
        pop = float(dens * a_km2) if np.isfinite(dens) else np.nan

        densidades.append(dens)
        poblaciones.append(pop)

# Guardar resultados en gdf_pts (WGS84)
gdf_pts["densidad_pob_km2"] = np.array(densidades, dtype=float)
gdf_pts["pob_buffer"] = np.array(poblaciones, dtype=float)

# ---------------------------------------------------------
# E) DiagnÃ³stico
# ---------------------------------------------------------
n_total = len(gdf_pts)
n_nan = int(np.isnan(gdf_pts["densidad_pob_km2"]).sum())

print("\nâœ… Resultado CELDA 7")
print("Filas en gdf_pts:", n_total)
print("Nodos sin densidad:", n_nan)

print("\nResumen densidad_pob_km2:")
print(gdf_pts["densidad_pob_km2"].describe())

print("\nResumen pob_buffer:")
print(gdf_pts["pob_buffer"].describe())

# (opcional) listar ejemplos NaN
if n_nan > 0:
    print("\nEjemplos de nodos NaN (primeros 10):")
    print(gdf_pts[gdf_pts["densidad_pob_km2"].isna()][["id_nodo","demanda_kg"]].head(10).to_string(index=False))

# CELDA 8 (V2.1.2): ExportaciÃ³n QGIS (Base + Tramos con De/A) -> varios archivos + densidad poblacional real en clientes
import geopandas as gpd
from shapely.geometry import Point, LineString
import numpy as np
import networkx as nx
import osmnx as ox
import os

print("--- INICIANDO EXPORTACIÃ“N A QGIS (V2.1.2) ---")

# =========================================================
# Helpers (MultiDiGraph safe)
# =========================================================
def best_edge_attr(G, u, v, attr, default=0.0):
    data = G.get_edge_data(u, v)
    if data is None:
        return default
    if isinstance(data, dict):  # MultiDiGraph
        if not all(isinstance(attrs, dict) for attrs in data.values()):
            return float(data.get(attr, default))
        best = None
        for _, attrs in data.items():
            val = float(attrs.get(attr, default))
            if best is None or val < best:
                best = val
        return float(best if best is not None else default)
    return float(data.get(attr, default))

def _safe_float_geom(x, default=np.inf):
    try:
        val = float(x)
        return val if np.isfinite(val) else default
    except Exception:
        return default

def best_edge_data(G, u, v):
    data = G.get_edge_data(u, v)
    if data is None:
        return {}
    if isinstance(data, dict) and all(isinstance(attrs, dict) for attrs in data.values()):
        def edge_score(attrs):
            return (
                _safe_float_geom(attrs.get("travel_time", np.inf)),
                _safe_float_geom(attrs.get("length", np.inf)),
            )
        return min(data.values(), key=edge_score)
    return data if isinstance(data, dict) else {}

def _dist2_xy(a, b):
    return (float(a[0]) - float(b[0])) ** 2 + (float(a[1]) - float(b[1])) ** 2

def edge_coords_directed(G, u, v):
    attrs = best_edge_data(G, u, v)
    geom_edge = attrs.get("geometry")
    coords = []
    if geom_edge is not None:
        try:
            if isinstance(geom_edge, str):
                from shapely import wkt
                geom_edge = wkt.loads(geom_edge)
            if geom_edge.geom_type == "LineString":
                coords = list(geom_edge.coords)
            elif geom_edge.geom_type == "MultiLineString":
                for line in geom_edge.geoms:
                    coords.extend(list(line.coords))
        except Exception:
            coords = []

    if len(coords) < 2:
        coords = [(G.nodes[u]["x"], G.nodes[u]["y"]), (G.nodes[v]["x"], G.nodes[v]["y"])]

    u_xy = (G.nodes[u]["x"], G.nodes[u]["y"])
    v_xy = (G.nodes[v]["x"], G.nodes[v]["y"])
    normal = _dist2_xy(coords[0], u_xy) + _dist2_xy(coords[-1], v_xy)
    invertida = _dist2_xy(coords[0], v_xy) + _dist2_xy(coords[-1], u_xy)
    if invertida + 1e-18 < normal:
        coords = list(reversed(coords))
    return coords

def path_to_coords(G, path):
    if not path or len(path) < 2:
        return []
    coords = []
    for u, v in zip(path[:-1], path[1:]):
        seg = edge_coords_directed(G, u, v)
        if coords and seg and _dist2_xy(coords[-1], seg[0]) < 1e-18:
            coords.extend(seg[1:])
        else:
            coords.extend(seg)
    return coords

def path_to_linestring(G, path):
    coords = path_to_coords(G, path)
    return LineString(coords) if len(coords) >= 2 else None

def tiene_retroceso_inmediato(path):
    if not path or len(path) < 3:
        return False
    return any(a == c for a, _, c in zip(path[:-2], path[1:-1], path[2:]))

def shortest_path_sin_retroceso(G, source, target, weight="travel_time"):
    try:
        base = nx.shortest_path(G, source, target, weight=weight)
        if not tiene_retroceso_inmediato(base):
            return base
    except Exception:
        base = None

    import heapq
    start_state = (None, source)
    heap = [(0.0, None, source, [source])]
    best = {start_state: 0.0}

    while heap:
        cost, prev, current, path = heapq.heappop(heap)
        if current == target:
            return path
        if cost > best.get((prev, current), np.inf) + 1e-9:
            continue
        vecinos = G.successors(current) if hasattr(G, "successors") else G.neighbors(current)
        for nxt in vecinos:
            if prev is not None and nxt == prev:
                continue
            edge_w = best_edge_attr(G, current, nxt, weight, np.inf)
            if not np.isfinite(edge_w):
                edge_w = best_edge_attr(G, current, nxt, "length", np.inf)
            if not np.isfinite(edge_w):
                continue
            new_cost = cost + float(edge_w)
            state = (current, nxt)
            if new_cost + 1e-9 < best.get(state, np.inf):
                best[state] = new_cost
                heapq.heappush(heap, (new_cost, current, nxt, path + [nxt]))

    if base is not None:
        return base
    return nx.shortest_path(G, source, target, weight=weight)

def routed_sequence_to_linestring(G, nodos_ruta):
    if not nodos_ruta or len(nodos_ruta) < 2:
        return None
    coords = []
    for a, b in zip(nodos_ruta[:-1], nodos_ruta[1:]):
        seg_path = shortest_path_sin_retroceso(G, a, b, weight="travel_time")
        seg_coords = path_to_coords(G, seg_path)
        if coords and seg_coords and _dist2_xy(coords[-1], seg_coords[0]) < 1e-18:
            coords.extend(seg_coords[1:])
        else:
            coords.extend(seg_coords)
    return LineString(coords) if len(coords) >= 2 else None

def path_dist_m(G, path):
    if not path or len(path) < 2:
        return 0.0
    dist = 0.0
    for u, v in zip(path[:-1], path[1:]):
        dist += best_edge_attr(G, u, v, "length", 0.0)
    return float(dist)

def path_time_s(G, path):
    if not path or len(path) < 2:
        return 0.0
    t = 0.0
    for u, v in zip(path[:-1], path[1:]):
        t += best_edge_attr(G, u, v, "travel_time", np.nan)
    return float(t)

def dist_ruteada_m(G, u, v):
    """Distancia (m) del camino mÃ¡s corto ruteado por travel_time (usa length)."""
    try:
        path = nx.shortest_path(G, u, v, weight="travel_time")
        return path_dist_m(G, path)
    except Exception:
        return np.nan

def dist_recoleccion_m(G, nodos_ruta):
    """Distancia (m) ruta interna recolecciÃ³n (cliente->cliente ruteado por travel_time)."""
    if not nodos_ruta or len(nodos_ruta) < 2:
        return 0.0
    total = 0.0
    for a, b in zip(nodos_ruta[:-1], nodos_ruta[1:]):
        try:
            seg = nx.shortest_path(G, a, b, weight="travel_time")
            total += path_dist_m(G, seg)
        except Exception:
            return np.nan
    return float(total)

# Coordenadas reales desde el grafo
x_est, y_est = G.nodes[id_estacion]['x'], G.nodes[id_estacion]['y']
x_rel, y_rel = G.nodes[id_relleno]['x'], G.nodes[id_relleno]['y']

# =========================================================
# 0) Validar densidad poblacional calculada (CELDA 7)
# =========================================================
if "gdf_pts" in globals() and gdf_pts is not None and len(gdf_pts) > 0:
    # nos quedamos solo con lo que necesitamos
    gdf_dens = gdf_pts[["id_nodo", "densidad_pob_km2", "pob_buffer"]].copy()
    # por si acaso viene como float
    gdf_dens["id_nodo"] = gdf_dens["id_nodo"].astype(int)
    print("âœ… Densidad poblacional detectada desde CELDA 7 (gdf_pts).")
else:
    gdf_dens = None
    print("âš ï¸ No encuentro gdf_pts de CELDA 7. Se exportarÃ¡n clientes SIN densidad poblacional real.")

# =========================================================
# 1) CAPAS BASE (archivos separados)
# =========================================================
print("1) Generando capas base...")

# --- CALLES ---
gdf_nodos, gdf_aristas = ox.graph_to_gdfs(G)
gdf_aristas.to_file("base_calles.gpkg", driver="GPKG")
print("  -> Guardado: base_calles.gpkg")

# --- CLIENTES (basura + densidad real + distancias) ---
data_clientes = []
for n in nodos_clientes:
    n_int = int(n)
    demanda = float(dict_demandas.get(n, 0.0))

    data_clientes.append({
        "id_nodo": n_int,
        "demanda_kg": round(demanda, 2),
        "dist_a_estacion_m": dist_ruteada_m(G_RUTEO, id_estacion, n),
        "dist_a_relleno_m": dist_ruteada_m(G_RUTEO, n, id_relleno),
        "geometry": Point(G.nodes[n]['x'], G.nodes[n]['y'])
    })

gdf_clientes = gpd.GeoDataFrame(data_clientes, crs="EPSG:4326")

# ðŸ‘‰ Join con densidad poblacional real si existe
if gdf_dens is not None:
    # merge por id_nodo
    gdf_clientes = gdf_clientes.merge(gdf_dens, on="id_nodo", how="left")
    # opcional: marca de calidad
    gdf_clientes["densidad_src"] = "Raster"
    # para reporte
    n_nan = int(gdf_clientes["densidad_pob_km2"].isna().sum())
    print(f"  -> Join densidad: OK. Nodos con densidad NaN: {n_nan}")
else:
    gdf_clientes["densidad_pob_km2"] = np.nan
    gdf_clientes["pob_buffer"] = np.nan
    gdf_clientes["densidad_src"] = "N/A"

gdf_clientes.to_file("base_clientes.gpkg", driver="GPKG")
print(f"  -> Guardado: base_clientes.gpkg ({len(gdf_clientes)} puntos)")

# --- PUNTOS CLAVE ---
gdf_clave = gpd.GeoDataFrame([
    {"tipo": "Estacion", "geometry": Point(x_est, y_est)},
    {"tipo": "Relleno",  "geometry": Point(x_rel, y_rel)}
], crs="EPSG:4326")
gdf_clave.to_file("base_puntos_clave.gpkg", driver="GPKG")
print("  -> Guardado: base_puntos_clave.gpkg")

# =========================================================
# 2) TRAMOS POR CAMIÃ“N (1 archivo GPKG por camiÃ³n)
# =========================================================
print("\n2) Generando tramos por camiÃ³n/viaje (un GPKG por camiÃ³n)...")

for camion in camiones:
    c_id = camion["id"]
    features = []
    orden_local = 1
    usa_tramos_operativos = any(
        bool(v.get("tramos_operativos"))
        for v in camion.get("viajes", [])
    )

    for i, viaje in enumerate(camion["viajes"], start=1):
        nodos_ruta = viaje["nodos"]
        if not nodos_ruta:
            continue

        if viaje.get("tramos_operativos"):
            for tramo_op in viaje["tramos_operativos"]:
                tipo = tramo_op.get("tipo", "Tramo")
                try:
                    if tipo == "Recol":
                        geom_line = routed_sequence_to_linestring(G_RUTEO, nodos_ruta)
                    else:
                        path = shortest_path_sin_retroceso(
                            G_RUTEO,
                            int(tramo_op["nodo_de"]),
                            int(tramo_op["nodo_a"]),
                            weight="travel_time"
                        )
                        geom_line = path_to_linestring(G_RUTEO, path)

                    if geom_line is not None:
                        features.append({
                            "Camion": c_id,
                            "Vehiculo": int(camion.get("vehiculo_id", c_id)),
                            "Operacion": camion.get("descripcion_operacion", "Estacion -> Recoleccion -> Relleno"),
                            "Viaje": i,
                            "Tramo": tipo,
                            "De": tramo_op.get("de", ""),
                            "A": tramo_op.get("a", ""),
                            "dur_s": float(tramo_op.get("dur_s", 0.0)),
                            "dist_m": float(tramo_op.get("dist_m", 0.0)),
                            "orden": orden_local,
                            "geometry": geom_line
                        })
                        orden_local += 1
                except Exception:
                    pass
            continue

        primer = nodos_ruta[0]
        ultimo = nodos_ruta[-1]

        # Origen del viaje segÃºn CELDA 6
        if viaje["origen"] == "EstaciÃ³n":
            origen_nodo = id_estacion
            de_aprox = "EstaciÃ³n"
        else:
            origen_nodo = id_relleno
            de_aprox = "Relleno"

        # TRAMO 1: APROXIMACIÃ“N
        if "origen_nodo" in viaje:
            origen_nodo = int(viaje["origen_nodo"])
            de_aprox = "Estacion" if origen_nodo == id_estacion else "Relleno"

        try:
            path = shortest_path_sin_retroceso(G_RUTEO, origen_nodo, primer, weight="travel_time")
            geom_line = path_to_linestring(G_RUTEO, path)
            if geom_line is not None:
                features.append({
                    "Camion": c_id,
                    "Viaje": i,
                    "Tramo": "Aprox",
                    "De": de_aprox,
                    "A": "RecolecciÃ³n",
                    "dur_s": float(viaje["costos"]["aprox_s"]),
                    "dist_m": path_dist_m(G_RUTEO, path),
                    "orden": orden_local,
                    "geometry": geom_line
                })
                orden_local += 1
        except:
            pass

        # TRAMO 2: RECOLECCIÃ“N
        try:
            geom_recol = routed_sequence_to_linestring(G_RUTEO, nodos_ruta)
            if geom_recol is not None:
                dist_recol = dist_recoleccion_m(G_RUTEO, nodos_ruta)

                features.append({
                    "Camion": c_id,
                    "Viaje": i,
                    "Tramo": "Recol",
                    "De": "RecolecciÃ³n",
                    "A": "RecolecciÃ³n",
                    "dur_s": float(viaje["costos"]["interno_s"]),
                    "dist_m": dist_recol,
                    "orden": orden_local,
                    "geometry": geom_recol
                })
                orden_local += 1
        except:
            pass

        # TRAMO 3: DESCARGA
        try:
            path = shortest_path_sin_retroceso(G_RUTEO, ultimo, id_relleno, weight="travel_time")
            geom_line = path_to_linestring(G_RUTEO, path)
            if geom_line is not None:
                features.append({
                    "Camion": c_id,
                    "Viaje": i,
                    "Tramo": "Desc",
                    "De": "RecolecciÃ³n",
                    "A": "Relleno",
                    "dur_s": float(viaje["costos"]["descarga_s"]),
                    "dist_m": path_dist_m(G_RUTEO, path),
                    "orden": orden_local,
                    "geometry": geom_line
                })
                orden_local += 1
        except:
            pass

    # Cierre generico solo para el modelo anterior sin tramos_operativos.
    if not usa_tramos_operativos:
        try:
            path = shortest_path_sin_retroceso(G_RUTEO, id_relleno, id_estacion, weight="travel_time")
            geom_line = path_to_linestring(G_RUTEO, path)
            if geom_line is not None:
                dur_fin = float(globals().get("t_retorno_casa", path_time_s(G_RUTEO, path)))

                features.append({
                    "Camion": c_id,
                    "Viaje": "FIN",
                    "Tramo": "Fin",
                    "De": "Relleno",
                    "A": "EstaciÃ³n",
                    "dur_s": dur_fin,
                    "dist_m": path_dist_m(G_RUTEO, path),
                    "orden": orden_local,
                    "geometry": geom_line
                })
                orden_local += 1
        except:
            pass

    out_gpkg = f"rutas_tramos_Camion_{c_id}.gpkg"
    if os.path.exists(out_gpkg):
        os.remove(out_gpkg)

    if features:
        gdf_tramos = gpd.GeoDataFrame(features, crs="EPSG:4326")
        gdf_tramos.to_file(out_gpkg, layer="tramos", driver="GPKG")
        print(f"  âœ… CamiÃ³n {c_id}: Guardado {out_gpkg} (layer='tramos', {len(gdf_tramos)} tramos)")
    else:
        print(f"  âš ï¸ CamiÃ³n {c_id}: No se generaron tramos (features vacÃ­o). Revisa viajes.")

print("\nâœ… Â¡PROCESO TERMINADO! Archivos generados:")
print("  - base_calles.gpkg")
print("  - base_clientes.gpkg  (incluye demanda_kg + densidad_pob_km2 + pob_buffer + dist_a_* )")
print("  - base_puntos_clave.gpkg")
print("  - rutas_tramos_Camion_X.gpkg (uno por camiÃ³n)")

# CELDA 9 (V3.2): BitÃ¡cora MACRO por TRAMOS + CSV (con distancias en todos los tramos)
import pandas as pd
import numpy as np
import networkx as nx

print("Generando bitÃ¡cora MACRO por TRAMOS (EstaciÃ³n/RecolecciÃ³n/Relleno/Fin)...")

filas = []

# -------------------------------
# Helpers MultiDiGraph safe (idÃ©nticos a CELDA 8)
# -------------------------------
def best_edge_attr(G, u, v, attr, default=0.0):
    data = G.get_edge_data(u, v)
    if data is None:
        return default
    if isinstance(data, dict):  # MultiDiGraph
        if not all(isinstance(attrs, dict) for attrs in data.values()):
            return float(data.get(attr, default))
        best = None
        for _, attrs in data.items():
            val = float(attrs.get(attr, default))
            if best is None or val < best:
                best = val
        return float(best if best is not None else default)
    return float(data.get(attr, default))

def path_dist_m(G, path):
    if not path or len(path) < 2:
        return 0.0
    dist = 0.0
    for u, v in zip(path[:-1], path[1:]):
        dist += best_edge_attr(G, u, v, "length", 0.0)
    return float(dist)

def dist_km_ruteada(G, u, v):
    """Distancia (km) del camino mÃ¡s corto ruteado por travel_time."""
    try:
        path = nx.shortest_path(G, u, v, weight="travel_time")
        return path_dist_m(G, path) / 1000.0
    except Exception:
        return np.nan

def dist_km_recoleccion(G, nodos_ruta):
    """
    Distancia (km) de la ruta interna de recolecciÃ³n:
    suma de caminos (cliente_k -> cliente_{k+1}) ruteados por travel_time.
    """
    if not nodos_ruta or len(nodos_ruta) < 2:
        return 0.0
    total_m = 0.0
    for a, b in zip(nodos_ruta[:-1], nodos_ruta[1:]):
        try:
            seg = nx.shortest_path(G, a, b, weight="travel_time")
            total_m += path_dist_m(G, seg)
        except Exception:
            return np.nan
    return total_m / 1000.0

t_fin_s = float(globals().get("t_retorno_casa", np.nan))

# -------------------------------
# BitÃ¡cora por camiÃ³n (macro-tramos)
# -------------------------------
for camion in camiones:
    c_id = camion["id"]
    usa_tramos_operativos = any(
        bool(v.get("tramos_operativos"))
        for v in camion.get("viajes", [])
    )

    for v_num, viaje in enumerate(camion["viajes"], start=1):
        nodos = viaje["nodos"]
        if not nodos:
            continue

        if viaje.get("tramos_operativos"):
            for t_idx, tramo in enumerate(viaje["tramos_operativos"], start=1):
                tipo = tramo.get("tipo", "Tramo")
                es_recol = tipo == "Recol"
                filas.append({
                    "CamiÃ³n": c_id,
                    "Paso": f"V{v_num}-{t_idx}",
                    "Tramo": tipo,
                    "De": tramo.get("de", ""),
                    "A": tramo.get("a", ""),
                    "Nodo_De": int(tramo.get("nodo_de", 0)),
                    "Nodo_A": int(tramo.get("nodo_a", 0)),
                    "Paradas_en_recolecciÃ³n": int(len(nodos)) if es_recol else 0,
                    "Carga_kg": float(viaje["carga"]) if es_recol else 0.0,
                    "Dist_km": float(tramo.get("dist_m", 0.0)) / 1000.0,
                    "Min": float(tramo.get("dur_s", 0.0)) / 60.0,
                    "Vehiculo": int(camion.get("vehiculo_id", c_id)),
                    "Operacion": camion.get("descripcion_operacion", "Estacion -> Recoleccion -> Relleno"),
                })
            balance_s = float((viaje.get("costos", {}) or {}).get("balance_turno_s", 0.0))
            if balance_s > 0:
                filas.append({
                    "CamiÃ³n": c_id,
                    "Paso": f"V{v_num}-B",
                    "Tramo": "Holgura operativa",
                    "De": "Operacion",
                    "A": "Operacion",
                    "Nodo_De": 0,
                    "Nodo_A": 0,
                    "Paradas_en_recolecciÃ³n": 0,
                    "Carga_kg": 0.0,
                    "Dist_km": 0.0,
                    "Min": balance_s / 60.0,
                    "Vehiculo": int(camion.get("vehiculo_id", c_id)),
                    "Operacion": camion.get("descripcion_operacion", "Estacion -> Recoleccion -> Relleno"),
                })
            continue

        primer = nodos[0]
        ultimo = nodos[-1]

        # TRAMO A: Origen -> RecolecciÃ³n
        if viaje["origen"] == "EstaciÃ³n":
            origen_nodo = id_estacion
            origen_tipo = "EstaciÃ³n"
        else:
            origen_nodo = id_relleno
            origen_tipo = "Relleno"

        if "origen_nodo" in viaje:
            origen_nodo = int(viaje["origen_nodo"])
            origen_tipo = "Estacion" if origen_nodo == id_estacion else "Relleno"

        t_aprox_s = float(viaje["costos"]["aprox_s"])
        d_aprox_km = dist_km_ruteada(G_RUTEO, origen_nodo, primer)

        filas.append({
            "CamiÃ³n": c_id,
            "Paso": f"V{v_num}-A",
            "Tramo": "Origenâ†’RecolecciÃ³n",
            "De": origen_tipo,
            "A": "RecolecciÃ³n",
            "Nodo_De": int(origen_nodo),
            "Nodo_A": int(primer),
            "Paradas_en_recolecciÃ³n": 0,
            "Carga_kg": 0.0,
            "Dist_km": d_aprox_km,
            "Min": t_aprox_s / 60.0
        })

        # TRAMO B: RecolecciÃ³n (operaciÃ³n) + distancia interna
        t_int_s = float(viaje["costos"]["interno_s"])
        d_recol_km = dist_km_recoleccion(G_RUTEO, nodos)

        filas.append({
            "CamiÃ³n": c_id,
            "Paso": f"V{v_num}-B",
            "Tramo": "RecolecciÃ³n (operaciÃ³n)",
            "De": "RecolecciÃ³n",
            "A": "RecolecciÃ³n",
            "Nodo_De": int(primer),
            "Nodo_A": int(ultimo),
            "Paradas_en_recolecciÃ³n": int(len(nodos)),
            "Carga_kg": float(viaje["carga"]),   # âœ… la carga se reporta SOLO aquÃ­
            "Dist_km": d_recol_km,
            "Min": t_int_s / 60.0
        })

        # TRAMO C: RecolecciÃ³n -> Relleno
        t_desc_s = float(viaje["costos"]["descarga_s"])
        d_desc_km = dist_km_ruteada(G_RUTEO, ultimo, id_relleno)

        filas.append({
            "CamiÃ³n": c_id,
            "Paso": f"V{v_num}-C",
            "Tramo": "RecolecciÃ³nâ†’Relleno",
            "De": "RecolecciÃ³n",
            "A": "Relleno",
            "Nodo_De": int(ultimo),
            "Nodo_A": int(id_relleno),
            "Paradas_en_recolecciÃ³n": 0,
            "Carga_kg": 0.0,                   # âœ… NO repetir carga (evita duplicar en resumen)
            "Dist_km": d_desc_km,
            "Min": t_desc_s / 60.0
        })

    if usa_tramos_operativos:
        continue

    # Cierre generico: Relleno -> Estacion
    d_fin_km = dist_km_ruteada(G_RUTEO, id_relleno, id_estacion)

    filas.append({
        "CamiÃ³n": c_id,
        "Paso": "FIN",
        "Tramo": "Rellenoâ†’Estacion (cierre)",
        "De": "Relleno",
        "A": "EstaciÃ³n",
        "Nodo_De": int(id_relleno),
        "Nodo_A": int(id_estacion),
        "Paradas_en_recolecciÃ³n": 0,
        "Carga_kg": 0.0,
        "Dist_km": d_fin_km,
        "Min": (t_fin_s / 60.0) if np.isfinite(t_fin_s) else np.nan
    })

df = pd.DataFrame(filas)

# -------------------------------
# Vista bonita (consola)
# -------------------------------
df_print = df.copy()
df_print["Dist_km"] = df_print["Dist_km"].round(2)
df_print["Min"] = df_print["Min"].round(1)
df_print["Carga_kg"] = df_print["Carga_kg"].round(2)

cols = [
    "CamiÃ³n","Paso","Tramo","De","A",
    "Paradas_en_recolecciÃ³n","Carga_kg","Dist_km","Min",
    "Nodo_De","Nodo_A"
]
df_print = df_print[cols]

print("\n=== BITÃCORA MACRO (vista previa, 30 filas) ===")
print(df_print.head(30).to_string(index=False))

# CSV completo
df.to_csv("bitacora_macro_tramos.csv", index=False)
print("\nâœ… Guardado completo: 'bitacora_macro_tramos.csv'")

# -------------------------------
# Resumen por camiÃ³n (macro)
# -------------------------------
res = df.groupby("CamiÃ³n").agg({
    "Carga_kg": "sum",
    "Dist_km": "sum",
    "Min": "sum",
    "Paradas_en_recolecciÃ³n": "sum"
}).reset_index()

res["Horas"] = (res["Min"] / 60.0).round(2)
res["Dist_km"] = res["Dist_km"].round(2)
res["Min"] = res["Min"].round(1)
res["Carga_kg"] = res["Carga_kg"].round(2)

print("\n=== RESUMEN POR CAMIÃ“N (MACRO) ===")
print(res[["CamiÃ³n","Carga_kg","Dist_km","Min","Horas","Paradas_en_recolecciÃ³n"]].to_string(index=False))

# -------------------------------
# Resumen GLOBAL (estilo PDF)
# -------------------------------
total_camiones = len(set(c.get("vehiculo_id", c.get("id", None)) for c in camiones))
total_servicios = int(res["CamiÃ³n"].nunique())
total_ton = float(res["Carga_kg"].sum() / 1000.0)
total_km = float(res["Dist_km"].sum())
total_h = float(res["Horas"].sum())
total_paradas = int(res["Paradas_en_recolecciÃ³n"].sum())

print("\n=== RESUMEN GLOBAL (FLOTA) ===")
print(f"Camiones usados: {total_camiones}")
print(f"Rutas asignadas: {total_servicios}")
print(f"Basura total: {total_ton:.2f} ton")
print(f"Distancia total: {total_km:.2f} km")
print(f"Tiempo total flota: {total_h:.2f} h")
print(f"Paradas totales (recolecciÃ³n): {total_paradas}")

# Opcional: consumo/costo como en el PDF (ajusta a tu supuesto)
KM_POR_GALON = RENDIMIENTO_KM_GAL
COSTO_POR_GALON = PRECIO_DIESEL_USD_GAL
if total_km > 0 and KM_POR_GALON > 0:
    gal = total_km / KM_POR_GALON
    costo = gal * COSTO_POR_GALON
    print(f"Consumo estimado: {gal:.2f} gal")
    print(f"Costo estimado: ${costo:.2f}")
    print(f"Eficiencia: {(total_ton/total_km):.4f} ton/km")

BASE_BRYAN_HISTORICO = {
    "escenario": "Base Bryan historico",
    "camiones_usados": 3,
    "viajes_asignados": 12,
    "distancia_total_km": 402.21,
    "tiempo_total_h": 21.12,
}
HIBRIDO_ACTUAL_MACRO = {
    "escenario": "Hibrido actual",
    "camiones_usados": total_camiones,
    "viajes_asignados": int(sum(len(c.get("viajes", [])) for c in camiones)),
    "distancia_total_km": total_km,
    "tiempo_total_h": total_h,
}
df_comparacion_operativa = pd.DataFrame([BASE_BRYAN_HISTORICO, HIBRIDO_ACTUAL_MACRO])
for col in ["camiones_usados", "viajes_asignados", "distancia_total_km", "tiempo_total_h"]:
    base_val = float(df_comparacion_operativa.loc[0, col])
    actual_val = float(df_comparacion_operativa.loc[1, col])
    df_comparacion_operativa[f"mejora_{col}_pct"] = np.nan
    if base_val > 0:
        df_comparacion_operativa.loc[1, f"mejora_{col}_pct"] = 100 * (base_val - actual_val) / base_val
df_comparacion_operativa.to_csv("comparacion_operativa.csv", index=False, encoding="utf-8-sig")

print("\n=== COMPARACION OPERATIVA VS BASE BRYAN ===")
display(df_comparacion_operativa.round(2))

# CELDA 9 (FIX): HTML Leaflet animado (capas + camiones ðŸšš + velocidad) SIN f-string
import geopandas as gpd
import json
import os

# -----------------------------
# Archivos esperados
# -----------------------------
CLIENTES_GPKG = "base_clientes.gpkg"
PUNTOS_CLAVE_GPKG = "base_puntos_clave.gpkg"
CALLES_GPKG = "base_calles.gpkg"      # opcional (puede ser pesado)
INCLUIR_CALLES = True                # Muestra la red vial base en el HTML

CAMIONES = [int(c["id"]) for c in camiones] if "camiones" in globals() and camiones else [1, 2, 3]
RUTA_GPKG_FMT = "rutas_tramos_Camion_{}.gpkg"
LAYER_TRAMOS = "tramos"

OUT_HTML = "rutas_animadas.html"


# -----------------------------
# Helpers
# -----------------------------
def gdf_to_geojson_dict(gdf):
    if gdf is None or len(gdf) == 0:
        return {"type": "FeatureCollection", "features": []}
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:4326")
    else:
        gdf = gdf.to_crs("EPSG:4326")
    return json.loads(gdf.to_json())

def leer_capa_gpkg(path, layer=None):
    if not os.path.exists(path):
        return None
    try:
        return gpd.read_file(path, layer=layer) if layer else gpd.read_file(path)
    except Exception as e:
        print(f"âš ï¸ No pude leer {path} ({e})")
        return None


# -----------------------------
# 1) Leer capas base
# -----------------------------
gdf_clientes = leer_capa_gpkg(CLIENTES_GPKG)
gdf_clave    = leer_capa_gpkg(PUNTOS_CLAVE_GPKG)

gdf_calles = None
if INCLUIR_CALLES:
    gdf_calles = leer_capa_gpkg(CALLES_GPKG)

# Centro del mapa
if gdf_clientes is not None and len(gdf_clientes) > 0:
    tmp = gdf_clientes.to_crs("EPSG:4326")
    centro_lat = float(tmp.geometry.y.mean())
    centro_lon = float(tmp.geometry.x.mean())
elif gdf_clave is not None and len(gdf_clave) > 0:
    tmp = gdf_clave.to_crs("EPSG:4326")
    centro_lat = float(tmp.geometry.y.mean())
    centro_lon = float(tmp.geometry.x.mean())
else:
    centro_lat, centro_lon = -2.9, -79.0  # fallback

clientes_geojson = gdf_to_geojson_dict(gdf_clientes)
clave_geojson    = gdf_to_geojson_dict(gdf_clave)
calles_geojson   = gdf_to_geojson_dict(gdf_calles) if INCLUIR_CALLES else {"type":"FeatureCollection","features":[]}

def construir_poligonos_zonas_no_superpuestos(zonas, grafo):
    if not zonas:
        return {}

    puntos_por_zona = {}
    centroides = []
    zona_ids = []
    todos = []
    for zona_id, nodos_zona in sorted(zonas.items()):
        pts = [
            geom.Point(float(grafo.nodes[n]["x"]), float(grafo.nodes[n]["y"]))
            for n in nodos_zona
            if n in grafo.nodes and "x" in grafo.nodes[n] and "y" in grafo.nodes[n]
        ]
        if not pts:
            continue
        puntos_por_zona[int(zona_id)] = pts
        todos.extend(pts)
        centroides.append(geom.MultiPoint(pts).centroid)
        zona_ids.append(int(zona_id))

    if not centroides:
        return {}
    if len(centroides) == 1:
        return {zona_ids[0]: geom.MultiPoint(todos).convex_hull.buffer(0.001)}

    limite = geom.MultiPoint(todos).convex_hull.buffer(0.003)
    geoms = {}
    try:
        from shapely.ops import voronoi_diagram
        celdas = voronoi_diagram(geom.MultiPoint(centroides), envelope=limite, edges=False)
        for celda in celdas.geoms:
            punto_ref = celda.representative_point()
            idx_centro = int(np.argmin([punto_ref.distance(c) for c in centroides]))
            zona_id = zona_ids[idx_centro]
            recortada = celda.intersection(limite)
            geoms[zona_id] = recortada if zona_id not in geoms else geoms[zona_id].union(recortada)
    except Exception:
        geoms = {}

    for zona_id, pts in puntos_por_zona.items():
        if zona_id not in geoms or geoms[zona_id].is_empty:
            base = geom.MultiPoint(pts).convex_hull
            geoms[zona_id] = base.buffer(0.00025 if base.geom_type in ("Point", "LineString") else 0.00008)

    return geoms

sectores_features = []
if "zonas_hibridas" in globals() and zonas_hibridas:
    geometrias_zonas = construir_poligonos_zonas_no_superpuestos(zonas_hibridas, G)
    for zona_id, nodos_zona in sorted(zonas_hibridas.items()):
        geom_zona = geometrias_zonas.get(int(zona_id))
        if geom_zona is None or geom_zona.is_empty:
            continue
        sectores_features.append({
            "type": "Feature",
            "properties": {
                "zona": int(zona_id),
                "clientes": int(len(nodos_zona)),
                "carga_kg": float(sum(float(dict_demandas.get(n, 0.0)) for n in nodos_zona)),
            },
            "geometry": mapping(geom_zona)
        })

sectores_geojson = {"type": "FeatureCollection", "features": sectores_features}


# -----------------------------
# 2) Leer rutas por camiÃ³n y convertir a lista de [lat, lon]
# -----------------------------
rutas_camiones = {}

for c in CAMIONES:
    path = RUTA_GPKG_FMT.format(c)
    gdf_tramos = leer_capa_gpkg(path, layer=LAYER_TRAMOS)

    if gdf_tramos is None or len(gdf_tramos) == 0:
        print(f"âš ï¸ CamiÃ³n {c}: sin tramos")
        rutas_camiones[c] = []
        continue

    gdf_tramos = gdf_tramos.to_crs("EPSG:4326").copy()
    if "orden" in gdf_tramos.columns:
        gdf_tramos = gdf_tramos.sort_values("orden")

    coords = []
    for geom in gdf_tramos.geometry:
        if geom is None:
            continue

        if geom.geom_type == "LineString":
            pts = list(geom.coords)
        elif geom.geom_type == "MultiLineString":
            pts = []
            for ls in geom.geoms:
                pts += list(ls.coords)
        else:
            continue

        latlon = [[float(y), float(x)] for (x, y) in pts]
        if coords and latlon and coords[-1] == latlon[0]:
            coords += latlon[1:]
        else:
            coords += latlon

    rutas_camiones[c] = coords
    print(f"âœ… CamiÃ³n {c}: {len(coords)} puntos de ruta")


# -----------------------------
# 3) Datos resumidos para el tablero HTML
# -----------------------------
carga_total_html_kg = float(sum(
    sum(float(v.get("carga", 0.0)) for v in c.get("viajes", []))
    for c in camiones
))
distancia_total_html_m = float(sum(
    sum(
        sum(float(x or 0.0) for x in (v.get("distancias_m", {}) or {}).values())
        for v in c.get("viajes", [])
    )
    for c in camiones
))
distancia_total_html_km = distancia_total_html_m / 1000.0
tiempo_total_html_h = float(sum(float(c.get("tiempo_total_h", 0.0)) for c in camiones))
costo_diesel_html_usd = (
    distancia_total_html_km / RENDIMIENTO_KM_GAL * PRECIO_DIESEL_USD_GAL
    if distancia_total_html_km > 0 and RENDIMIENTO_KM_GAL > 0
    else 0.0
)
eficiencia_html_ton_km = (
    (carga_total_html_kg / 1000.0) / distancia_total_html_km
    if distancia_total_html_km > 0
    else 0.0
)

metricas_html = {
    "global": {
        "camiones_usados": len(set(c.get("vehiculo_id", c.get("id", None)) for c in camiones)),
        "camiones_maximos": NUM_VEHICULOS,
        "servicios_asignados": len(camiones),
        "viajes_asignados": int(sum(len(c.get("viajes", [])) for c in camiones)),
        "clientes": int(len(nodos_clientes)) if "nodos_clientes" in globals() else 0,
        "carga_total_kg": carga_total_html_kg,
        "capacidad_camion_kg": float(CAPACIDAD_MAXIMA_KG),
        "distancia_total_km": distancia_total_html_km,
        "eficiencia_ton_km": eficiencia_html_ton_km,
        "tiempo_total_h": tiempo_total_html_h,
        "costo_diesel_usd": costo_diesel_html_usd,
    },
    "camiones": [],
    "viajes": [],
}

for c in camiones:
    c_id = int(c.get("id", 0))
    viajes = c.get("viajes", []) or []
    carga = float(sum(float(v.get("carga", 0.0)) for v in viajes))
    distancia_m = float(sum(
        sum(float(x or 0.0) for x in (v.get("distancias_m", {}) or {}).values())
        for v in viajes
    ))
    tiempo_viajes_s = float(sum(
        sum(float(x or 0.0) for x in (v.get("costos", {}) or {}).values())
        for v in viajes
        ))
    metricas_html["camiones"].append({
        "id": c_id,
        "vehiculo": int(c.get("vehiculo_id", c_id)),
        "descarga": c.get("descarga", ""),
        "operacion": c.get("descripcion_operacion", "Estacion -> Recoleccion -> Relleno"),
        "viajes": len(viajes),
        "carga_kg": carga,
        "carga_max_viaje_kg": float(max([float(v.get("carga", 0.0)) for v in viajes] + [0.0])),
        "capacidad_kg": float(CAPACIDAD_MAXIMA_KG),
        "distancia_km": distancia_m / 1000.0,
        "tiempo_h": float(c.get("tiempo_total_h", 0.0)),
        "tiempo_viajes_min": tiempo_viajes_s / 60.0,
        "uso_jornada_pct": 100.0 * float(c.get("tiempo_total_h", 0.0)) / 8.0,
    })
    for idx_v, v in enumerate(viajes, start=1):
        dist = v.get("distancias_m", {}) or {}
        costos = v.get("costos", {}) or {}
        metricas_html["viajes"].append({
            "camion": c_id,
            "vehiculo": int(c.get("vehiculo_id", c_id)),
            "descarga": v.get("modalidad_descarga", c.get("descarga", "")),
            "viaje": idx_v,
            "origen": v.get("origen", "N/A"),
            "carga_kg": float(v.get("carga", 0.0)),
            "capacidad_kg": float(CAPACIDAD_MAXIMA_KG),
            "aprox_km": float(dist.get("aprox_m", 0.0)) / 1000.0,
            "recoleccion_km": float(dist.get("recoleccion_m", 0.0)) / 1000.0,
            "descarga_km": float(dist.get("descarga_m", 0.0)) / 1000.0,
            "cierre_km": float(dist.get("cierre_m", 0.0)) / 1000.0,
            "aprox_min": float(costos.get("aprox_s", 0.0)) / 60.0,
            "recoleccion_min": float(costos.get("interno_s", 0.0)) / 60.0,
            "espera_desalojo_min": float(costos.get("espera_desalojo_s", 0.0)) / 60.0,
            "descarga_min": float(costos.get("descarga_s", 0.0)) / 60.0,
            "cierre_min": float(costos.get("cierre_s", 0.0)) / 60.0,
            "balance_turno_min": float(costos.get("balance_turno_s", 0.0)) / 60.0,
            "ventana_desalojo": v.get("ventana_desalojo", "N/A"),
        })

# -----------------------------
# 4) Template HTML (sin f-string)
# -----------------------------
html = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>Rutas animadas de recoleccion</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  />
  <style>
    :root {
      color-scheme: light;
      --ink: #172033;
      --muted: #637083;
      --line: #d9e0ea;
      --surface: rgba(255,255,255,0.94);
      --surface-solid: #ffffff;
      --soft: #f5f7fa;
      --accent: #0f766e;
      --accent-2: #2563eb;
      --shadow: 0 18px 48px rgba(15, 23, 42, 0.16);
    }
    * { box-sizing: border-box; }
    html, body { height: 100%; margin: 0; overflow: hidden; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Arial; color: var(--ink); }
    #map { width: 100%; height: 100%; background: #edf1f6; }
    .glass { pointer-events: auto; background: var(--surface); border: 1px solid rgba(217,224,234,0.92); box-shadow: var(--shadow); backdrop-filter: blur(16px); }
    .topbar { position: absolute; top: 14px; left: 14px; right: 14px; z-index: 9999; height: 60px; border-radius: 8px; display: grid; grid-template-columns: minmax(260px, 1fr) auto auto; align-items: center; gap: 12px; padding: 10px 12px 10px 16px; }
    .brand { min-width: 0; }
    .eyebrow { margin: 0; color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
    .headline { margin: 2px 0 0; font-size: 20px; line-height: 1.1; font-weight: 850; letter-spacing: 0; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .top-actions, .panel-actions, .row { display: flex; gap: 8px; align-items: center; }
    .btn { cursor: pointer; border: 1px solid #172033; padding: 9px 11px; border-radius: 6px; background: #172033; color: white; font-weight: 800; font-size: 13px; line-height: 1; }
    .btn.secondary { background: #fff; color: #172033; border-color: #cbd5e1; }
    .btn.accent { background: var(--accent); border-color: var(--accent); }
    .btn.icon { width: 36px; height: 36px; display: grid; place-items: center; padding: 0; }
    .btn.filter.active { background: #0f172a; color: #fff; border-color: #0f172a; }
    .btn:active { transform: translateY(1px); }
    .shell { position: absolute; top: 88px; left: 14px; right: 14px; bottom: 14px; z-index: 9998; pointer-events: none; display: grid; grid-template-columns: 340px minmax(0, 1fr) 420px; gap: 14px; align-items: start; }
    .panel { border-radius: 8px; overflow: hidden; transition: transform .22s ease, opacity .22s ease; max-height: calc(100vh - 102px); }
    .panel.hidden-left { transform: translateX(calc(-100% - 18px)); opacity: 0; pointer-events: none; }
    .panel.hidden-right { transform: translateX(calc(100% + 18px)); opacity: 0; pointer-events: none; }
    .panel-head { min-height: 50px; padding: 12px 14px; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; align-items: center; gap: 10px; }
    .panel-title { margin: 0; font-size: 12px; font-weight: 850; letter-spacing: .08em; text-transform: uppercase; color: var(--muted); }
    .panel-body { padding: 12px 14px 14px; overflow: auto; max-height: calc(100vh - 166px); }
    .section { border: 1px solid var(--line); border-radius: 8px; background: #fff; margin-bottom: 10px; overflow: hidden; }
    .section summary { cursor: pointer; list-style: none; padding: 11px 12px; display: flex; justify-content: space-between; align-items: center; font-size: 13px; font-weight: 850; }
    .section summary::-webkit-details-marker { display: none; }
    .section summary::after { content: "Ocultar"; color: var(--muted); font-size: 11px; font-weight: 750; }
    .section:not([open]) summary::after { content: "Mostrar"; }
    .section-content { border-top: 1px solid var(--line); padding: 10px 12px 12px; }
    .small { font-size: 12px; color: var(--muted); line-height: 1.35; }
    .metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .metric { border: 1px solid var(--line); border-radius: 7px; padding: 10px; background: var(--surface-solid); min-height: 64px; }
    .metric .label { display: block; color: var(--muted); font-size: 10px; font-weight: 800; text-transform: uppercase; letter-spacing: .05em; }
    .metric .value { display: block; margin-top: 6px; font-size: 21px; line-height: 1; font-weight: 900; }
    .slider-row { display: grid; grid-template-columns: 66px 1fr 44px; gap: 10px; align-items: center; margin-top: 8px; }
    input[type="range"] { width: 100%; accent-color: var(--accent); }
    .truck-icon { width: 30px; height: 30px; border-radius: 999px; display: grid; place-items: center; background: #fff; border: 2px solid currentColor; box-shadow: 0 6px 16px rgba(15,23,42,.25); font-size: 11px; font-weight: 900; }
    .truck-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fff; margin-bottom: 8px; }
    .truck-card.active { border-color: currentColor; box-shadow: inset 4px 0 0 currentColor; }
    .truck-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-bottom: 10px; }
    .truck-name { font-weight: 900; font-size: 15px; }
    .swatch { width: 11px; height: 11px; border-radius: 99px; display: inline-block; margin-right: 8px; vertical-align: -1px; }
    .pill { border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; font-size: 11px; color: var(--muted); font-weight: 800; white-space: nowrap; }
    .stat-line { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; }
    .stat-line div { background: var(--soft); border-radius: 6px; padding: 8px; min-width: 0; }
    .stat-line b { display: block; font-size: 13px; }
    .stat-line span { color: var(--muted); font-size: 11px; }
    .progress { margin-top: 10px; height: 7px; background: #e2e8f0; border-radius: 99px; overflow: hidden; }
    .progress i { display: block; height: 100%; width: var(--p); background: currentColor; }
    .route-table-wrap { overflow: auto; max-height: 43vh; border: 1px solid var(--line); border-radius: 8px; }
    .route-table { width: 100%; border-collapse: collapse; font-size: 12px; background: #fff; }
    .route-table th { position: sticky; top: 0; background: #fff; text-align: left; color: var(--muted); font-size: 10px; text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--line); padding: 8px 6px; }
    .route-table td { border-bottom: 1px solid #eef2f7; padding: 8px 6px; vertical-align: top; }
    .leaflet-control-layers { border-radius: 8px !important; box-shadow: var(--shadow) !important; border: 1px solid var(--line) !important; }
    .leaflet-top.leaflet-right { right: 14px; top: 88px; }
    body.focus-mode .shell, body.focus-mode .topbar { display: none; }
    .restore-ui { display: none; position: absolute; top: 14px; left: 14px; z-index: 10000; }
    body.focus-mode .restore-ui { display: block; }
    .control-panel, .summary-panel { display: none !important; }
    @media (max-width: 980px) {
      .topbar { grid-template-columns: 1fr auto; height: auto; }
      .top-actions { grid-column: 1 / -1; flex-wrap: wrap; }
      .shell { top: 126px; grid-template-columns: 1fr; overflow: auto; align-items: stretch; }
      .panel { max-height: 42vh; }
      .panel-body { max-height: calc(42vh - 50px); }
      .panel.hidden-left, .panel.hidden-right { display: none; }
      .leaflet-top.leaflet-right { top: 126px; }
    }
  </style>
</head>
<body>
<div id="map"></div>

<button id="btnRestoreUiPremium" class="btn restore-ui">Mostrar tablero</button>

<header class="glass topbar">
  <div class="brand">
    <p class="eyebrow">Operacion urbana</p>
    <h1 class="headline">Rutas de recoleccion optimizadas</h1>
  </div>
  <div class="top-actions">
    <button id="btnPlayPremium" class="btn accent">Play</button>
    <button id="btnPausePremium" class="btn secondary">Pausa</button>
    <button id="btnResetPremium" class="btn secondary">Reiniciar</button>
  </div>
  <div class="top-actions">
    <button id="btnToggleLeftPremium" class="btn secondary">Operacion</button>
    <button id="btnToggleRightPremium" class="btn secondary">Analisis</button>
    <button id="btnFocusPremium" class="btn">Solo mapa</button>
  </div>
</header>

<main class="shell">
  <aside id="leftPanelPremium" class="glass panel">
    <div class="panel-head">
      <p class="panel-title">Control</p>
      <button id="btnHideLeftPremium" class="btn icon secondary" title="Ocultar panel">-</button>
    </div>
    <div class="panel-body">
      <details class="section" open>
        <summary>Animacion</summary>
        <div class="section-content">
          <div class="slider-row">
            <b class="small">Velocidad</b>
            <input id="speedPremium" type="range" min="0.25" max="6" step="0.25" value="1.5">
            <span id="speedValPremium" class="small">1.5x</span>
          </div>
        </div>
      </details>

      <details class="section" open>
        <summary>Indicadores globales</summary>
        <div class="section-content">
          <div class="metric-grid" id="globalMetricsPremium"></div>
        </div>
      </details>

      <details class="section" open>
        <summary>Capas</summary>
        <div class="section-content">
          <p class="small">Cada ruta visible corresponde a un camion asignado. Todas las rutas respetan capacidad maxima, flujo Estacion -> Recoleccion -> Relleno y sentidos del grafo vial.</p>
        </div>
      </details>
    </div>
  </aside>

  <div></div>

  <section id="rightPanelPremium" class="glass panel">
    <div class="panel-head">
      <p class="panel-title">Analisis operativo</p>
      <button id="btnHideRightPremium" class="btn icon secondary" title="Ocultar panel">-</button>
    </div>
    <div class="panel-body">
      <details class="section" open>
        <summary>Rutas asignadas</summary>
        <div class="section-content">
          <div id="truckCardsPremium"></div>
        </div>
      </details>

      <details class="section">
        <summary>Detalle de viajes</summary>
        <div class="section-content">
          <div class="route-table-wrap">
            <table class="route-table">
              <thead>
                <tr><th>Ruta</th><th>Camion</th><th>Operacion</th><th>Km</th><th>Tiempo</th></tr>
              </thead>
              <tbody id="routeRowsPremium"></tbody>
            </table>
          </div>
        </div>
      </details>
    </div>
  </section>
</main>

<div class="control-panel">
  <p class="panel-title">Operacion urbana</p>
  <h1 class="headline">Rutas de recoleccion optimizadas</h1>
  <div class="row">
    <button id="btnPlay" class="btn">â–¶ Reproducir</button>
    <button id="btnPause" class="btn" style="background:#6b7280;">â¸ Pausa</button>
    <button id="btnReset" class="btn" style="background:#0ea5e9;">â†º Reiniciar</button>
  </div>

  <div class="row">
    <label><b>Velocidad</b>:</label>
    <input id="speed" type="range" min="0.25" max="6" step="0.25" value="1.5">
    <span id="speedVal" class="small">1.5Ã—</span>
  </div>

  <div class="metric-grid" id="globalMetrics"></div>

  <div class="small">
    Tip: Activa/desactiva capas desde el control (arriba derecha).
  </div>
</div>

<section class="panel summary-panel">
  <div class="summary-head">
    <p class="panel-title">Resumen operativo</p>
    <h2 class="headline" style="font-size:18px;margin-bottom:0;">Rutas y tramos</h2>
  </div>
  <div class="summary-body">
    <div id="truckCards"></div>
    <div class="routes-title">Detalle de rutas</div>
    <table class="route-table">
      <thead>
        <tr><th>Ruta</th><th>Camion</th><th>Operacion</th><th>Km</th><th>Tiempo</th></tr>
      </thead>
      <tbody id="routeRows"></tbody>
    </table>
  </div>
</section>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  // Datos embebidos (GeoJSON / rutas)
  const CLIENTES = __CLIENTES__;
  const CLAVE    = __CLAVE__;
  const CALLES   = __CALLES__;
  const SECTORES = __SECTORES__;
  const RUTAS    = __RUTAS__;
  const METRICAS = __METRICAS__;

  // Mapa base
  const map = L.map('map', {
    center: [__CENTRO_LAT__, __CENTRO_LON__],
    zoom: 14
  });

  const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }).addTo(map);

  // Capas overlay
  function styleClientes(feature) {
    const p = feature.properties || {};
    const d = (p.demanda_kg !== undefined && p.demanda_kg !== null) ? p.demanda_kg : 0;
    const r = Math.max(2, Math.min(10, 2 + d/200));
    return {
      radius: r,
      color: "#111827",
      weight: 1,
      fillColor: "#f97316",
      fillOpacity: 0.85
    };
  }

  const layerClientes = L.geoJSON(CLIENTES, {
    pointToLayer: (f, latlng) => L.circleMarker(latlng, styleClientes(f)),
    onEachFeature: (f, layer) => {
      const p = f.properties || {};
      const dens = (p.densidad_pob_km2 !== undefined && p.densidad_pob_km2 !== null) ? p.densidad_pob_km2 : "-";
      layer.bindPopup(
        `<b>Cliente</b><br>` +
        `Nodo: ${(p.id_nodo !== undefined && p.id_nodo !== null) ? p.id_nodo : "-"}<br>` +
        `Demanda: ${(p.demanda_kg !== undefined && p.demanda_kg !== null) ? p.demanda_kg : "-"} kg<br>` +
        `Densidad: ${dens} hab/kmÂ²`
      );
    }
  });

  const layerClave = L.geoJSON(CLAVE, {
    pointToLayer: (f, latlng) => {
      const tipo = (f.properties && f.properties.tipo) ? f.properties.tipo : "Punto";
      return L.marker(latlng).bindPopup(`<b>${tipo}</b>`);
    }
  });

  const layerCalles = L.geoJSON(CALLES, {
    style: { color: "#22c55e", weight: 2, opacity: 0.55 }
  });

  // Rutas por camion (lineas)
  const coloresSectores = ["#0f766e", "#2563eb", "#ca8a04", "#7c3aed", "#dc2626", "#0891b2", "#16a34a", "#be185d", "#475569", "#ea580c"];
  const layerSectores = L.geoJSON(SECTORES, {
    style: f => {
      const z = Number((f.properties || {}).zona || 1);
      const color = coloresSectores[(z - 1) % coloresSectores.length];
      return { color, weight: 2, opacity: 0.75, fillColor: color, fillOpacity: 0.11, dashArray: "7 5" };
    },
    onEachFeature: (f, layer) => {
      const p = f.properties || {};
      layer.bindPopup(
        `<b>Sector inicial ${p.zona || "-"}</b><br>` +
        `Clientes: ${p.clientes || 0}<br>` +
        `Carga estimada: ${Number((p.carga_kg || 0) / 1000).toFixed(1)} t`
      );
    }
  });

  function polylineFromRuta(rutaLatLon, color) {
    if (!rutaLatLon || rutaLatLon.length < 2) return null;
    return L.polyline(rutaLatLon, { color, weight: 5, opacity: 0.9 });
  }

  const servicioMeta = {};
  (METRICAS.camiones || []).forEach(c => { servicioMeta[String(c.id)] = c; });

  function colorForService(id) {
    const n = Number(id) || 1;
    const hue = (n * 137.508) % 360;
    return `hsl(${hue.toFixed(1)} 72% 42%)`;
  }

  const colores = {};
  Object.keys(RUTAS).forEach(k => { colores[k] = colorForService(k); });
  const layerRutas = {};
  Object.keys(RUTAS).forEach(k => {
    const poly = polylineFromRuta(RUTAS[k], colores[k] || "#111827");
    if (poly) layerRutas[k] = poly;
  });

  const fmt = new Intl.NumberFormat("es-EC", { maximumFractionDigits: 1 });
  const fmt0 = new Intl.NumberFormat("es-EC", { maximumFractionDigits: 0 });

  function metric(label, value) {
    return `<div class="metric"><span class="label">${label}</span><span class="value">${value}</span></div>`;
  }

  function formatHours(totalHours) {
    const totalMin = Math.round(Number(totalHours || 0) * 60);
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return `${h}h ${String(m).padStart(2, "0")}m`;
  }

  function formatMinutes(totalMinutes) {
    const totalMin = Math.round(Number(totalMinutes || 0));
    const h = Math.floor(totalMin / 60);
    const m = totalMin % 60;
    return `${h}h ${String(m).padStart(2, "0")}m`;
  }

  function capacidadTon(item) {
    return Number((item && item.capacidad_kg) || (METRICAS.global && METRICAS.global.capacidad_camion_kg) || 12000) / 1000;
  }

  function cargaTon(item) {
    const carga = Number((item && item.carga_kg) || 0) / 1000;
    return Math.min(carga, capacidadTon(item));
  }

  function renderDashboard() {
    const global = METRICAS.global || {};
    const totalKm = (METRICAS.camiones || []).reduce((acc, c) => acc + (c.distancia_km || 0), 0);
    const cargaTotalTon = Number(global.carga_total_kg || 0) / 1000;
    const distanciaTotalKm = Number(global.distancia_total_km || totalKm || 0);
    const eficienciaTonKm = Number(global.eficiencia_ton_km || (distanciaTotalKm > 0 ? cargaTotalTon / distanciaTotalKm : 0));
    const costoDiesel = Number(global.costo_diesel_usd || (distanciaTotalKm > 0 ? distanciaTotalKm / 4.5 * 2.99 : 0));
    const globalBox = document.getElementById("globalMetricsPremium");
    if (globalBox) {
      globalBox.innerHTML = [
        metric("Viajes", fmt0.format(global.viajes_asignados || 0)),
        metric("Camiones", `${fmt0.format(global.camiones_usados || 0)} / ${fmt0.format(global.camiones_maximos || 0)}`),
        metric("Carga", `${fmt.format(cargaTotalTon)} t`),
        metric("Distancia", `${fmt.format(distanciaTotalKm)} km`),
        metric("Eficiencia", `${eficienciaTonKm.toFixed(4)} ton/km`),
        metric("Jornada", formatHours(global.tiempo_total_h || 0)),
        metric("Costo", `$${fmt.format(costoDiesel)}`)
      ].join("");
    }

    const cards = document.getElementById("truckCardsPremium");
    if (cards) {
      cards.innerHTML = (METRICAS.camiones || []).map(c => {
        const color = colores[String(c.id)] || "#111827";
        const capacidad = capacidadTon(c);
        const cargaTotal = Number(c.carga_kg || 0) / 1000;
        const cargaMaxViaje = Number(c.carga_max_viaje_kg || 0) / 1000;
        const cargaPct = capacidad > 0 ? Math.min(100, (cargaMaxViaje / capacidad) * 100) : 0;
        return `
          <article class="truck-card" id="truckCard-${c.id}" style="color:${color}">
            <div class="truck-top">
              <div class="truck-name"><span class="swatch" style="background:${color}"></span>Camion ${c.vehiculo || c.id}</div>
              <span class="pill">${fmt0.format(c.viajes || 0)} viajes</span>
            </div>
            <div class="small" style="margin:-4px 0 8px;">${c.operacion || "Estacion -> Recoleccion -> Relleno"}</div>
            <div class="stat-line">
              <div><b>${formatHours(c.tiempo_h || 0)}</b><span>jornada</span></div>
              <div><b>${fmt0.format(c.viajes || 0)}</b><span>viajes</span></div>
              <div><b>${fmt.format(c.distancia_km || 0)}</b><span>km</span></div>
            </div>
            <div class="progress" style="--p:${cargaPct}%"><i></i></div>
            <div class="small" style="margin-top:7px;">Carga jornada: ${fmt.format(cargaTotal)} t - Mayor viaje: ${fmt.format(cargaMaxViaje)} / ${fmt.format(capacidad)} t</div>
          </article>
        `;
      }).join("");
    }

    const rows = document.getElementById("routeRowsPremium");
    if (rows) {
      rows.innerHTML = (METRICAS.viajes || []).flatMap(v => {
        const c = String(v.camion);
        const color = colores[c] || "#111827";
        const base = `<td><span class="swatch" style="background:${color}"></span>${v.camion}</td><td>${v.vehiculo || "-"}</td>`;
        const out = [];
        out.push(`<tr data-camion="${c}">${base}<td>Aproximacion desde ${v.origen}</td><td>${fmt.format(v.aprox_km || 0)}</td><td>${formatMinutes(v.aprox_min || 0)}</td></tr>`);
        const cargaTxt = `${fmt.format(cargaTon(v))} / ${fmt.format(capacidadTon(v))} t`;
        out.push(`<tr data-camion="${c}">${base}<td>Recoleccion (${cargaTxt})</td><td>${fmt.format(v.recoleccion_km || 0)}</td><td>${formatMinutes(v.recoleccion_min || 0)}</td></tr>`);
        if ((v.descarga_km || 0) > 0 || (v.descarga_min || 0) > 0) {
          out.push(`<tr data-camion="${c}">${base}<td>Descarga final en relleno</td><td>${fmt.format(v.descarga_km || 0)}</td><td>${formatMinutes(v.descarga_min || 0)}</td></tr>`);
        }
        if ((v.cierre_km || 0) > 0 || (v.cierre_min || 0) > 0) {
          out.push(`<tr data-camion="${c}">${base}<td>Cierre: regreso al punto de inicio</td><td>${fmt.format(v.cierre_km || 0)}</td><td>${formatMinutes(v.cierre_min || 0)}</td></tr>`);
        }
        return out;
      }).join("");
    }
  }

  renderDashboard();

  // Control de capas
  const overlays = {
    "Sectores iniciales": layerSectores,
    "Clientes (puntos)": layerClientes,
    "Puntos clave": layerClave
  };
  if (CALLES.features && CALLES.features.length > 0) overlays["Calles (base)"] = layerCalles;

  Object.keys(layerRutas).forEach(k => {
    overlays[`Ruta ${k}`] = layerRutas[k];
  });

  L.control.layers({ "OSM": osm }, overlays, { collapsed: true }).addTo(map);

  // Mostrar por defecto
  layerSectores.addTo(map);
  layerClave.addTo(map);
  layerClientes.addTo(map);
  Object.keys(layerRutas).forEach(k => layerRutas[k].addTo(map));

  // Fit a rutas
  const allPolys = Object.values(layerRutas);
  if (allPolys.length > 0) {
    const group = L.featureGroup(allPolys);
    map.fitBounds(group.getBounds().pad(0.08));
  }

  // -----------------------
  // AnimaciÃ³n ðŸšš
  // -----------------------
  function haversineMeters(a, b) {
    const R = 6371000;
    const toRad = x => x * Math.PI / 180;
    const dLat = toRad(b[0]-a[0]);
    const dLon = toRad(b[1]-a[1]);
    const lat1 = toRad(a[0]);
    const lat2 = toRad(b[0]);
    const s1 = Math.sin(dLat/2), s2 = Math.sin(dLon/2);
    const h = s1*s1 + Math.cos(lat1)*Math.cos(lat2)*s2*s2;
    return 2*R*Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function buildCumulativeDistances(coords) {
    const cum = [0];
    for (let i=1; i<coords.length; i++) {
      cum.push(cum[i-1] + haversineMeters(coords[i-1], coords[i]));
    }
    return cum;
  }

  function interpolateAlong(coords, cumDist, dist) {
    if (coords.length < 2) return coords[0] || null;
    const total = cumDist[cumDist.length-1];
    if (dist <= 0) return coords[0];
    if (dist >= total) return coords[coords.length-1];

    let i = 1;
    while (i < cumDist.length && cumDist[i] < dist) i++;
    const d0 = cumDist[i-1], d1 = cumDist[i];
    const t = (dist - d0) / (d1 - d0 + 1e-9);

    const a = coords[i-1], b = coords[i];
    return [a[0] + (b[0]-a[0]) * t, a[1] + (b[1]-a[1]) * t];
  }

  // Crear un camiÃ³n por ruta
  const trucks = [];
  const truckByRoute = {};
  Object.keys(RUTAS).forEach(k => {
    const coords = RUTAS[k];
    if (!coords || coords.length < 2) return;

    const icon = L.divIcon({
      className: '',
      html: `<div class="truck-icon">R${k}</div>`,
      iconSize: [22,22],
      iconAnchor: [11,11]
    });

    const marker = L.marker(coords[0], { icon }).addTo(map);

    trucks.push({
      id: k,
      coords,
      cum: buildCumulativeDistances(coords),
      dist: 0
    });
    trucks[trucks.length-1].marker = marker;
    truckByRoute[k] = marker;
  });

  function camionIdFromLayerName(name) {
    const match = String(name || "").match(/(\\d+)$/);
    return match ? match[1] : null;
  }

  function setRouteUiState(id, visible) {
    const card = document.getElementById(`truckCard-${id}`);
    if (card) card.classList.toggle("active", visible);
    document.querySelectorAll(`[data-camion="${id}"]`).forEach(row => {
      row.style.display = visible ? "" : "none";
    });
  }

  function setServiceVisible(id, visible) {
    const key = String(id);
    const route = layerRutas[key];
    const marker = truckByRoute[key];
    if (route) {
      if (visible && !map.hasLayer(route)) route.addTo(map);
      if (!visible && map.hasLayer(route)) map.removeLayer(route);
    }
    if (marker) {
      if (visible && !map.hasLayer(marker)) marker.addTo(map);
      if (!visible && map.hasLayer(marker)) map.removeLayer(marker);
    }
    setRouteUiState(key, visible);
  }

  Object.keys(truckByRoute).forEach(id => setRouteUiState(id, true));
  map.on("overlayremove", e => {
    const id = camionIdFromLayerName(e.name);
    if (id && truckByRoute[id] && map.hasLayer(truckByRoute[id])) {
      map.removeLayer(truckByRoute[id]);
      setRouteUiState(id, false);
    }
  });
  map.on("overlayadd", e => {
    const id = camionIdFromLayerName(e.name);
    if (id && truckByRoute[id] && !map.hasLayer(truckByRoute[id])) {
      truckByRoute[id].addTo(map);
      setRouteUiState(id, true);
    }
  });

  let running = false;
  let lastT = null;

  function getSpeedFactor() {
    return parseFloat(document.getElementById("speedPremium").value || "1");
  }

  // velocidad base de animaciÃ³n (m/s)
  const BASE_MPS = 40.0;

  function tick(ts) {
    if (!running) return;
    if (!lastT) lastT = ts;
    const dt = (ts - lastT) / 1000.0;
    lastT = ts;

    const factor = getSpeedFactor();
    const step = BASE_MPS * factor * dt;

    trucks.forEach(t => {
      t.dist += step;
      const total = t.cum[t.cum.length-1];
      if (t.dist > total) t.dist = total;
      const pos = interpolateAlong(t.coords, t.cum, t.dist);
      if (pos) t.marker.setLatLng(pos);
    });

    requestAnimationFrame(tick);
  }

  // Controles
  const speed = document.getElementById("speedPremium");
  const speedVal = document.getElementById("speedValPremium");
  speed.addEventListener("input", () => {
    speedVal.textContent = `${speed.value}x`;
    return;
    speedVal.textContent = `${speed.value}Ã—`;
  });

  const leftPanel = document.getElementById("leftPanelPremium");
  const rightPanel = document.getElementById("rightPanelPremium");
  const toggleLeftPanel = () => leftPanel.classList.toggle("hidden-left");
  const toggleRightPanel = () => rightPanel.classList.toggle("hidden-right");
  document.getElementById("btnToggleLeftPremium").addEventListener("click", toggleLeftPanel);
  document.getElementById("btnHideLeftPremium").addEventListener("click", toggleLeftPanel);
  document.getElementById("btnToggleRightPremium").addEventListener("click", toggleRightPanel);
  document.getElementById("btnHideRightPremium").addEventListener("click", toggleRightPanel);
  document.getElementById("btnFocusPremium").addEventListener("click", () => document.body.classList.add("focus-mode"));
  document.getElementById("btnRestoreUiPremium").addEventListener("click", () => document.body.classList.remove("focus-mode"));

  document.getElementById("btnPlayPremium").addEventListener("click", () => {
    if (!running) {
      running = true;
      lastT = null;
      requestAnimationFrame(tick);
    }
  });

  document.getElementById("btnPausePremium").addEventListener("click", () => {
    running = false;
  });

  document.getElementById("btnResetPremium").addEventListener("click", () => {
    running = false;
    lastT = null;
    trucks.forEach(t => {
      t.dist = 0;
      t.marker.setLatLng(t.coords[0]);
    });
  });
</script>
</body>
</html>
"""

# Inyectar datos en el template
html = html.replace("__CLIENTES__", json.dumps(clientes_geojson))
html = html.replace("__CLAVE__", json.dumps(clave_geojson))
html = html.replace("__CALLES__", json.dumps(calles_geojson))
html = html.replace("__SECTORES__", json.dumps(sectores_geojson))
html = html.replace("__RUTAS__", json.dumps(rutas_camiones))
html = html.replace("__METRICAS__", json.dumps(metricas_html))
html = html.replace("__CENTRO_LAT__", str(centro_lat))
html = html.replace("__CENTRO_LON__", str(centro_lon))

with open(OUT_HTML, "w", encoding="utf-8") as f:
    f.write(html)

print(f"âœ… HTML generado: {OUT_HTML}")
print("   Ãbrelo en tu navegador (doble click).")

# CELDA KPI (SOLO COLAB): EstadÃ­sticas + KPIs (por viaje / por camiÃ³n / global) mostrando tablas
import pandas as pd
import numpy as np

CAPACIDAD_MAXIMA_KG = float(globals().get("CAPACIDAD_MAXIMA_KG", CAPACIDAD_MAXIMA_CAMION_KG))
HORAS_TRABAJO = HORAS_TRABAJO_H  # horas

def safe_float(x):
    try:
        return float(x)
    except:
        return np.nan

def gini_coefficient(x):
    """Gini: 0=uniforme, 1=concentrado."""
    arr = np.array([v for v in x if np.isfinite(v) and v >= 0], dtype=float)
    if len(arr) == 0:
        return np.nan
    if np.all(arr == 0):
        return 0.0
    arr = np.sort(arr)
    n = len(arr)
    cum = np.cumsum(arr)
    g = (n + 1 - 2 * np.sum(cum) / cum[-1]) / n
    return float(g)

print("ðŸ“Š Generando KPIs (modo Colab)...")

# =========================================================
# 0) Dataframe por NODO (basura + densidad si existe CELDA 7)
# =========================================================
df_nodos = pd.DataFrame({
    "id_nodo": [int(n) for n in nodos_clientes],
    "demanda_kg": [safe_float(dict_demandas.get(n, 0.0)) for n in nodos_clientes]
})

hay_densidad = False
if "gdf_pts" in globals() and gdf_pts is not None and len(gdf_pts) > 0 and "densidad_pob_km2" in gdf_pts.columns:
    df_dens = gdf_pts[["id_nodo", "densidad_pob_km2", "pob_buffer"]].copy()
    df_dens["id_nodo"] = df_dens["id_nodo"].astype(int)
    df_nodos = df_nodos.merge(df_dens, on="id_nodo", how="left")
    hay_densidad = True
else:
    df_nodos["densidad_pob_km2"] = np.nan
    df_nodos["pob_buffer"] = np.nan

total_demanda = float(df_nodos["demanda_kg"].sum())
gini_demanda = gini_coefficient(df_nodos["demanda_kg"].values)

# =========================================================
# 1) Desglose por VIAJE desde camiones (CELDA 6)
# =========================================================
filas_viajes = []
for c in camiones:
    c_id = c.get("id", None)
    viajes = c.get("viajes", [])
    for v_idx, v in enumerate(viajes, start=1):
        nodos = v.get("nodos", []) or []
        carga = safe_float(v.get("carga", 0.0))
        origen = v.get("origen", "N/A")

        costos = v.get("costos", {}) or {}
        dist   = v.get("distancias_m", {}) or {}

        t_aprox = safe_float(costos.get("aprox_s", np.nan))
        t_int   = safe_float(costos.get("interno_s", np.nan))
        t_espera = safe_float(costos.get("espera_desalojo_s", 0.0))
        t_desc  = safe_float(costos.get("descarga_s", np.nan))
        t_cierre = safe_float(costos.get("cierre_s", 0.0))
        t_balance = safe_float(costos.get("balance_turno_s", 0.0))
        t_productivo = np.nansum([t_aprox, t_int, t_espera, t_desc, t_cierre])
        t_total = np.nansum([t_productivo, t_balance])

        d_aprox = safe_float(dist.get("aprox_m", np.nan))
        d_recol = safe_float(dist.get("recoleccion_m", np.nan))
        d_descm = safe_float(dist.get("descarga_m", np.nan))
        d_cierre = safe_float(dist.get("cierre_m", 0.0))
        d_total = np.nansum([d_aprox, d_recol, d_descm, d_cierre])

        filas_viajes.append({
            "camion": c_id,
            "viaje": v_idx,
            "origen": origen,
            "paradas": len(nodos),
            "carga_kg": carga,

            "t_aprox_min": t_aprox/60 if np.isfinite(t_aprox) else np.nan,
            "t_recol_min": t_int/60   if np.isfinite(t_int)   else np.nan,
            "t_espera_desalojo_min": t_espera/60 if np.isfinite(t_espera) else np.nan,
            "t_desc_min":  t_desc/60  if np.isfinite(t_desc)  else np.nan,
            "t_cierre_min": t_cierre/60 if np.isfinite(t_cierre) else np.nan,
            "t_holgura_operativa_min": t_balance/60 if np.isfinite(t_balance) else np.nan,
            "t_productivo_min": t_productivo/60 if np.isfinite(t_productivo) else np.nan,
            "t_total_min": t_total/60 if np.isfinite(t_total) else np.nan,

            "d_aprox_km": d_aprox/1000 if np.isfinite(d_aprox) else np.nan,
            "d_recol_km": d_recol/1000 if np.isfinite(d_recol) else np.nan,
            "d_desc_km":  d_descm/1000 if np.isfinite(d_descm) else np.nan,
            "d_cierre_km": d_cierre/1000 if np.isfinite(d_cierre) else np.nan,
            "d_total_km": d_total/1000 if np.isfinite(d_total) else np.nan,

            "kg_por_km": (carga / (d_total/1000)) if (np.isfinite(d_total) and d_total > 0) else np.nan,
            "kg_por_h":  (carga / (t_total/3600)) if (np.isfinite(t_total) and t_total > 0) else np.nan,

            "util_carga_pct": (100*carga/CAPACIDAD_MAXIMA_KG) if CAPACIDAD_MAXIMA_KG > 0 else np.nan
        })

df_viajes = pd.DataFrame(filas_viajes)

# =========================================================
# 2) KPIs por CAMIÃ“N
# =========================================================
df_camiones = pd.DataFrame([{
    "camion": c.get("id", None),
    "vehiculo": c.get("vehiculo_id", c.get("id", None)),
    "viajes_asignados": len(c.get("viajes", [])),
    "tiempo_ruta_h": safe_float(c.get("tiempo_total_h", np.nan)),
    "tiempo_productivo_h": safe_float(c.get("tiempo_productivo_h", np.nan)),
    "tiempo_ruta_min": safe_float(c.get("tiempo_total_s", np.nan))/60 if np.isfinite(safe_float(c.get("tiempo_total_s", np.nan))) else np.nan,
} for c in camiones])

if len(df_viajes) > 0:
    agg = df_viajes.groupby("camion").agg(
        carga_total_kg=("carga_kg", "sum"),
        paradas_total=("paradas", "sum"),
        dist_total_km=("d_total_km", "sum"),
        tiempo_viajes_min=("t_total_min", "sum"),
        kg_por_km_prom=("kg_por_km", "mean"),
        kg_por_h_prom=("kg_por_h", "mean"),
        util_carga_prom=("util_carga_pct", "mean"),
    ).reset_index()
    df_camiones = df_camiones.merge(agg, on="camion", how="left")

if "dist_total_km" not in df_camiones.columns:
    df_camiones["dist_total_km"] = np.nan

df_camiones["uso_jornada_pct"] = 100 * (df_camiones["tiempo_ruta_h"] / HORAS_TRABAJO)
df_camiones["holgura_min"] = (HORAS_TRABAJO - df_camiones["tiempo_ruta_h"]) * 60
df_camiones["galones_estimados"] = df_camiones["dist_total_km"] / RENDIMIENTO_KM_GAL
df_camiones["costo_diesel_usd"] = df_camiones["galones_estimados"] * PRECIO_DIESEL_USD_GAL
df_camiones["costo_nomina_mensual_usd"] = (
    NUMERO_RECOLECTORES_CAMION * SUELDO_RECOLECTORES_USD
    + NUMERO_CHOFER_CAMION * SUELDO_CHOFER_USD
)

df_viajes.to_csv("kpi_viajes.csv", index=False, encoding="utf-8-sig")
df_camiones.sort_values("camion").to_csv("kpi_camiones.csv", index=False, encoding="utf-8-sig")

# =========================================================
# 3) KPIs GLOBALES
# =========================================================
n_servicios = len(camiones)
n_camiones = len(set(c.get("vehiculo_id", c.get("id", None)) for c in camiones))
n_viajes = len(df_viajes)
carga_total_asignada = float(df_viajes["carga_kg"].sum()) if n_viajes > 0 else 0.0
dist_total_km = float(df_viajes["d_total_km"].sum()) if n_viajes > 0 else np.nan
tiempo_total_h_rutas = float(df_camiones["tiempo_ruta_h"].sum()) if len(df_camiones) > 0 else np.nan
galones_estimados = dist_total_km / RENDIMIENTO_KM_GAL if np.isfinite(dist_total_km) and RENDIMIENTO_KM_GAL > 0 else np.nan
costo_diesel_usd = galones_estimados * PRECIO_DIESEL_USD_GAL if np.isfinite(galones_estimados) else np.nan
costo_nomina_mensual_usd = n_camiones * (
    NUMERO_RECOLECTORES_CAMION * SUELDO_RECOLECTORES_USD
    + NUMERO_CHOFER_CAMION * SUELDO_CHOFER_USD
)

error_kg = carga_total_asignada - total_demanda
error_rel_pct = (100*error_kg/total_demanda) if total_demanda > 0 else np.nan

corr_dens_dem = np.nan
if hay_densidad:
    tmp = df_nodos.dropna(subset=["densidad_pob_km2", "demanda_kg"])
    if len(tmp) >= 3:
        corr_dens_dem = float(tmp["densidad_pob_km2"].corr(tmp["demanda_kg"]))

# =========================================================
# 4) Mostrar (Colab)
# =========================================================
print("\n======================")
print("âœ… KPI GLOBAL")
print("======================")
print(f"Camiones usados: {n_camiones}")
print(f"Rutas asignadas: {n_servicios}")
print(f"Viajes asignados: {n_viajes}")
print(f"Nodos clientes: {len(nodos_clientes)}")
print(f"Demanda total (kg): {total_demanda:,.2f}")
print(f"Carga total asignada (kg): {carga_total_asignada:,.2f}")
print(f"Error carga vs demanda: {error_kg:,.2f} kg  ({error_rel_pct:.3f}%)")
print(f"Distancia total (km): {dist_total_km:,.2f}" if np.isfinite(dist_total_km) else "Distancia total: N/A")
print(f"Tiempo total sumado de rutas (h): {tiempo_total_h_rutas:,.2f}" if np.isfinite(tiempo_total_h_rutas) else "Tiempo total: N/A")
print(f"Diesel estimado: {galones_estimados:,.2f} gal | Costo: ${costo_diesel_usd:,.2f}" if np.isfinite(costo_diesel_usd) else "Diesel estimado: N/A")
print(f"Costo nomina mensual flota: ${costo_nomina_mensual_usd:,.2f}")
print(f"Gini de basura: {gini_demanda:.3f}")
if hay_densidad:
    print(f"CorrelaciÃ³n basura vs densidad poblacional: {corr_dens_dem:.3f}")
else:
    print("Densidad poblacional: no detectada (gdf_pts no estÃ¡ o no tiene densidad_pob_km2).")

print("\n======================")
print("ðŸš› KPI POR CAMIÃ“N")
print("======================")
display(
    df_camiones.sort_values("camion").round(2)
)

print("\n======================")
print("ðŸ§¾ KPI POR VIAJE (top 20 mÃ¡s largos por tiempo)")
print("======================")
if len(df_viajes) > 0:
    display(
        df_viajes.sort_values("t_total_min", ascending=False).head(20).round(2)
    )
else:
    print("No hay viajes en df_viajes.")

print("\n======================")
print("ðŸ”¥ Hotspots por basura (top 15 nodos)")
print("======================")
display(df_nodos.sort_values("demanda_kg", ascending=False).head(15))

if hay_densidad:
    print("\n======================")
    print("ðŸ™ï¸ Hotspots por densidad poblacional (top 15 nodos)")
    print("======================")
    display(df_nodos.sort_values("densidad_pob_km2", ascending=False).head(15))

html_salida = Path("rutas_animadas.html").resolve()
if html_salida.exists():
    print(f"HTML listo para abrir en local: {html_salida}")
else:
    print("âš ï¸ No se encontrÃ³ rutas_animadas.html al final del proceso.")
