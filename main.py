# CELDA 1 (DISTANCIA): Carga grafo + obtiene clientes (por etiqueta o fallback polígono) + estación/relleno
import osmnx as ox
import networkx as nx
import numpy as np
import geopandas as gpd
import shapely.geometry as geom
import os
import sys
from shapely.validation import explain_validity
from pyproj import CRS, Transformer

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

print("1) Cargando grafo...")
G = ox.load_graphml("grafo_cuenca.graphml")
print("   -> OK grafo cargado.")

def utm_epsg_from_lonlat(lon, lat):
    zone = int(np.floor((lon + 180) / 6) + 1)
    return 32700 + zone if lat < 0 else 32600 + zone

def preparar_busqueda_nodo_cercano(G, lon_ref, lat_ref):
    """
    Prepara una búsqueda robusta del nodo más cercano sin depender de
    scikit-learn cuando el grafo está en EPSG:4326.
    """
    crs_grafo = CRS.from_user_input(G.graph.get("crs", "EPSG:4326"))
    node_ids = np.array(list(G.nodes()))
    xs = np.array([float(G.nodes[n]["x"]) for n in node_ids], dtype=float)
    ys = np.array([float(G.nodes[n]["y"]) for n in node_ids], dtype=float)

    if crs_grafo.is_geographic:
        utm_crs = CRS.from_epsg(utm_epsg_from_lonlat(lon_ref, lat_ref))
        transformer = Transformer.from_crs(crs_grafo, utm_crs, always_xy=True)
        xs, ys = transformer.transform(xs, ys)
        point_transformer = transformer
    else:
        point_transformer = None

    return {
        "node_ids": node_ids,
        "xs": xs,
        "ys": ys,
        "point_transformer": point_transformer,
    }

def nearest_node_robusto(busqueda, lon, lat):
    if busqueda["point_transformer"] is not None:
        lon, lat = busqueda["point_transformer"].transform(lon, lat)

    dx = busqueda["xs"] - lon
    dy = busqueda["ys"] - lat
    idx_min = int(np.argmin(dx * dx + dy * dy))
    return busqueda["node_ids"][idx_min]

def nombres_arista(attrs):
    name = attrs.get("name")
    if isinstance(name, list):
        return [str(x) for x in name if x is not None]
    if name is None:
        return []
    return [str(name)]

def crear_subgrafo_por_patron_nombre(G, patron):
    patron = patron.lower()
    H = nx.MultiDiGraph()
    H.graph.update(G.graph)
    for u, v, k, d in G.edges(keys=True, data=True):
        nombres = nombres_arista(d)
        if any(patron in n.lower() for n in nombres):
            if not H.has_node(u):
                H.add_node(u, **G.nodes[u])
            if not H.has_node(v):
                H.add_node(v, **G.nodes[v])
            H.add_edge(u, v, key=k, **d)
    return H

def nodo_mas_cercano_en_conjunto(G, target_node, candidate_nodes):
    tx, ty = G.nodes[target_node]["x"], G.nodes[target_node]["y"]
    best = None
    for n in candidate_nodes:
        dx = float(G.nodes[n]["x"]) - float(tx)
        dy = float(G.nodes[n]["y"]) - float(ty)
        d2 = dx * dx + dy * dy
        if best is None or d2 < best[0]:
            best = (d2, int(n))
    return None if best is None else best[1]

busqueda_nodo_cercano = preparar_busqueda_nodo_cercano(G, -78.9814250, -2.8758464)

# 0) Validar que exista 'length' (distancia en metros)
u0, v0, d0 = next(iter(G.edges(data=True)))
if "length" not in d0:
    raise ValueError("❌ El grafo no tiene atributo 'length' en aristas. No se puede trabajar por distancia.")

# 1) Coordenadas clave
loc_estacion = (-2.8758464, -78.9814250)  # (lat, lon)
loc_relleno  = (-2.965480,  -78.930210)   # (lat, lon)

# 2) Intentar leer clientes/estación/relleno por etiquetas si existen
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
    print("2) Detecté 'tipo_nodo' en el grafo. Leyendo clientes etiquetados...")
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

# 3) Si no detectó estación/relleno por etiqueta, usar nearest_nodes
if id_estacion is None:
    id_estacion = nearest_node_robusto(busqueda_nodo_cercano, loc_estacion[1], loc_estacion[0])
if id_relleno is None:
    id_relleno = nearest_node_robusto(busqueda_nodo_cercano, loc_relleno[1],  loc_relleno[0])

# Corredor operativo obligatorio hacia el relleno: Vía al Valle
subgrafo_via_valle = crear_subgrafo_por_patron_nombre(G, "via al valle")
if len(subgrafo_via_valle.nodes) > 0:
    via_valle_nodes = list(subgrafo_via_valle.nodes)
    nodo_valle_ciudad = nodo_mas_cercano_en_conjunto(G, id_estacion, via_valle_nodes)
    nodo_valle_relleno = nodo_mas_cercano_en_conjunto(G, id_relleno, via_valle_nodes)
    try:
        path_valle_central = nx.shortest_path(
            subgrafo_via_valle,
            nodo_valle_ciudad,
            nodo_valle_relleno,
            weight="travel_time"
        )
    except Exception:
        path_valle_central = nx.shortest_path(
            G,
            nodo_valle_ciudad,
            nodo_valle_relleno,
            weight="travel_time"
        )
else:
    via_valle_nodes = []
    nodo_valle_ciudad = None
    nodo_valle_relleno = None
    path_valle_central = []

# 4) Fallback: si no hay clientes etiquetados, usar polígono + buffer (para acercarte a 307)
if len(nodos_clientes) == 0:
    print("⚠️ No hay clientes etiquetados. Uso fallback: polígono detallado + buffer para aproximar 307.")

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
        print("   Polígono inválido:", explain_validity(poligono))
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

print("\n✅ DATOS LISTOS:")
print(f"   -> Clientes a visitar: {len(nodos_clientes)}")
print(f"   -> Nodo Estación: {id_estacion}")
print(f"   -> Nodo Relleno:  {id_relleno}")

# Si no tienes demandas aquí, lo normal es calcularlas en la CELDA 2 (POIs o distribución base)
if len(dict_demandas) > 0:
    print(f"   -> Demanda Total (si aplica): {sum(dict_demandas.values()):.2f} kg")
else:
    print("   -> Demanda: se definirá en CELDA 2 (recomendado).")


# CELDA 2 (ROBUSTA): POIs + demandas (sirve con o sin poligono_zona)
import pandas as pd
import numpy as np
import shapely.geometry as geom

TOTAL_BASURA_KG = 57590.0
print("1) Descargando Puntos de Interés (POIs) de OSM...")

tags = {
    'amenity': ['restaurant', 'cafe', 'fast_food', 'bar', 'pub', 'marketplace', 'school'],
    'shop': True,
    'tourism': ['hotel', 'hostel'],
    'building': ['apartments', 'retail', 'commercial']
}

# ---------------------------------------------------------
# A) Asegurar un polígono para consultar POIs
# ---------------------------------------------------------
if "poligono_zona" in globals() and poligono_zona is not None:
    poly_query = poligono_zona
    print("   -> Usando polígono definido (poligono_zona).")
else:
    print("   -> No existe poligono_zona. Creando polígono desde nodos_clientes (convex hull)...")
    pts = [(G.nodes[n]['x'], G.nodes[n]['y']) for n in nodos_clientes]
    poly_query = geom.MultiPoint(pts).convex_hull.buffer(0.0005)  # ~50m aprox (ojo: aprox)

# ---------------------------------------------------------
# B) Descargar POIs
# ---------------------------------------------------------
try:
    pois = ox.features_from_polygon(poly_query, tags)
    print(f"   -> Se encontraron {len(pois)} POIs relevantes.")
except Exception as e:
    print(f"   -> No se pudieron obtener POIs ({e}). Usaremos distribución base.")
    pois = pd.DataFrame()

# ---------------------------------------------------------
# C) Pesos base por nodo (residencial)
# ---------------------------------------------------------
pesos_nodos = {nodo: 1.0 for nodo in nodos_clientes}

# Ponderaciones
w_comida  = 8.0
w_tienda  = 3.0
w_hotel   = 5.0
w_escuela = 4.0
w_normal  = 2.0

# ---------------------------------------------------------
# D) Aumentar peso si hay negocio cerca
# ---------------------------------------------------------
if not pois.empty:
    print("2) Asignando basura comercial a nodos cercanos...")

    pois = pois.copy()
    pois["pt"] = pois.geometry.representative_point()

    for _, row in pois.iterrows():
        nearest_node = nearest_node_robusto(busqueda_nodo_cercano, row["pt"].x, row["pt"].y)
        if nearest_node not in pesos_nodos:
            continue

        amenity = row.get("amenity", None)
        tourism = row.get("tourism", None)
        shop    = row.get("shop", None)

        if isinstance(amenity, str) and amenity in ["restaurant","fast_food","marketplace","cafe","bar","pub"]:
            pesos_nodos[nearest_node] += w_comida
        elif isinstance(amenity, str) and amenity == "school":
            pesos_nodos[nearest_node] += w_escuela
        elif isinstance(tourism, str) and tourism in ["hotel","hostel"]:
            pesos_nodos[nearest_node] += w_hotel
        elif (shop is not None) and (not pd.isna(shop)):
            pesos_nodos[nearest_node] += w_tienda
        else:
            pesos_nodos[nearest_node] += w_normal

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
    # sobra basura: resto repartiendo desde los que más tienen
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
        print(f"⚠️ Aviso: no se pudo ajustar todo el exceso ({exceso} kg).")

# (Opcional) micro-ajuste final por redondeos (ya debería ser 0.00 casi siempre)
residual = round(TOTAL_BASURA_KG - sum(dict_demandas.values()), 2)
if residual != 0:
    n0 = nodos_clientes[0]
    dict_demandas[n0] = max(0.0, round(dict_demandas[n0] + residual, 2))
    G.nodes[n0]["demanda_kg"] = dict_demandas[n0]

# ---------------------------------------------------------
# G) Estadísticas
# ---------------------------------------------------------
print("\n--- ESTADÍSTICAS DE GENERACIÓN DE BASURA ---")
print(f"Total Basura: {sum(dict_demandas.values()):.2f} kg (Objetivo: {TOTAL_BASURA_KG})")
print(f"Nodo con MENOS basura: {min(dict_demandas.values()):.2f} kg (Residencial)")
print(f"Nodo con MÁS basura:   {max(dict_demandas.values()):.2f} kg (Hotspot)")
print(f"Promedio: {np.mean(list(dict_demandas.values())):.2f} kg")

top_3 = sorted(dict_demandas.items(), key=lambda x: x[1], reverse=True)[:3]
print(f"\nTop 3 Hotspots: {top_3}")

# CELDA 3 (COINCIDE CON CELDA 6): Matriz OD DISTANCIAS (m) + helpers de TIEMPO por tramo
import numpy as np
import networkx as nx

# -----------------------------
# Velocidades del escenario (km/h)
# -----------------------------
V_ESTACION_A_PRIMERO = 40.0
V_RECOLECCION        = 10.0
V_ULTIMO_A_DEPOSITO  = 30.0
V_DEPOSITO_A_EST     = 40.0

# (Debe coincidir con CELDA 6)
TIEMPO_RECOLECCION_POR_NODO = 60  # segundos

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

print(f"Calculando matriz de DISTANCIAS por calles entre {n} puntos (weight='length')...")

# -----------------------------
# 2) Matriz de distancias mínimas (m) por OSM
# -----------------------------
dist_m = np.full((n, n), np.inf, dtype=float)

for k, origen in enumerate(lista_lugares, 1):
    d = nx.single_source_dijkstra_path_length(G, origen, weight="length")
    i = idx[origen]
    for destino, j in idx.items():
        dist_m[i, j] = d.get(destino, np.inf)

    if k % 50 == 0:
        print(f"  procesados {k}/{n} orígenes...")

print("✅ Matriz de distancias lista.")

# -----------------------------
# 3) Helpers D() y T() (esto es lo que usa CELDA 6)
# -----------------------------
def D(a, b):
    """Distancia mínima (m) entre nodos a y b."""
    return dist_m[idx[a], idx[b]]

def T(a, b, vel_kmh):
    """Tiempo (s) entre a y b aplicando velocidad por tramo."""
    return tiempo_segundos(D(a, b), vel_kmh)

# -----------------------------
# 4) Funciones de tiempo por viaje (COINCIDE con la lógica de CELDA 6)
# -----------------------------
def tiempo_viaje_s(ruta_clientes, origen_es_estacion=True,
                   incluir_recoleccion=True,
                   estacion=estacion, deposito=deposito):
    """
    Tiempo de un viaje (SIN retorno final a estación), exactamente como CELDA 6:
    - Aproximación (origen->primer cliente) a 40 km/h
    - Entre clientes a 10 km/h
    - Recolección por nodo (opcional): 60s por parada (igual que CELDA 6)
    - Último cliente -> depósito a 30 km/h
    """
    if not ruta_clientes:
        return np.inf, {"error": "Ruta vacía"}

    primer = ruta_clientes[0]
    ultimo = ruta_clientes[-1]

    detalle = {}

    # 1) Aproximación (40)
    origen_nodo = estacion if origen_es_estacion else deposito
    t_aprox = T(origen_nodo, primer, V_ESTACION_A_PRIMERO)

    # 2) Interno (10) + recolección
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
    """Retorno final depósito -> estación (40 km/h)."""
    return T(deposito, estacion, V_DEPOSITO_A_EST)

# -----------------------------
# 5) Prueba rápida (solo viaje + retorno final aparte)
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
print(f"\nRetorno final (Depósito->Estación, 40): {t_fin/60:.2f} min")

# CELDA 4: Clarke & Wright usando DISTANCIAS por calles (metros) + tiempos compatibles con CELDA 6
import numpy as np
from sklearn.cluster import AgglomerativeClustering

# (Debe coincidir con CELDA 3 / CELDA 6)
V_ESTACION_A_PRIMERO = 40.0
V_RECOLECCION        = 10.0
V_ULTIMO_A_DEPOSITO  = 30.0
V_DEPOSITO_A_EST     = 40.0
TIEMPO_RECOLECCION_POR_NODO = 60  # s

def tiempo_segundos(dist_m, vel_kmh):
    if dist_m is None or not np.isfinite(dist_m):
        return np.inf
    vel_mps = vel_kmh * 1000.0 / 3600.0
    return dist_m / vel_mps if vel_mps > 0 else np.inf

def D(dist_matriz, idx, a, b):
    """Distancia mínima (m) entre a y b desde dist_m."""
    return dist_matriz[idx[a], idx[b]]

def construir_gdf_clientes_utm(G, nodos_clientes, lon_ref, lat_ref):
    epsg_utm = utm_epsg_from_lonlat(lon_ref, lat_ref)
    utm_crs = CRS.from_epsg(epsg_utm)

    gdf_clientes = gpd.GeoDataFrame(
        {"node": [int(n) for n in nodos_clientes]},
        geometry=[geom.Point(G.nodes[n]["x"], G.nodes[n]["y"]) for n in nodos_clientes],
        crs="EPSG:4326"
    )
    return gdf_clientes.to_crs(utm_crs)

def estimar_num_clusters(nodos_clientes, dict_demanda, max_capacidad):
    total_demanda = sum(float(dict_demanda.get(n, 0.0)) for n in nodos_clientes)
    if max_capacidad <= 0:
        return 1
    # Las zonas deben representar territorios operativos, no viajes unitarios.
    # Permitimos que cada zona agrupe varias cargas de camión antes del balanceo final.
    carga_objetivo_zona = max_capacidad * 1.9
    n_clusters = int(np.ceil(total_demanda / carga_objetivo_zona))
    return max(2, min(len(nodos_clientes), n_clusters))

def construir_matriz_cluster_red_vial(nodos_clientes, dist_matriz, idx, deposito_id=None, dist_hasta_valle=None):
    """
    Matriz simétrica para clustering usando distancia real sobre la red vial.
    Incluye una pequeña componente asociada al depósito para favorecer zonas operativas coherentes.
    """
    nodos = [int(n) for n in nodos_clientes]
    n = len(nodos)
    M = np.zeros((n, n), dtype=float)
    vals_finitos = []

    for i, ni in enumerate(nodos):
        for j in range(i + 1, n):
            nj = nodos[j]
            dij = D(dist_matriz, idx, ni, nj)
            dji = D(dist_matriz, idx, nj, ni)
            candidatos = [d for d in (dij, dji) if np.isfinite(d)]
            if not candidatos:
                val = np.inf
            else:
                val = float(np.mean(candidatos))
                if deposito_id is not None:
                    di_dep = D(dist_matriz, idx, ni, deposito_id)
                    dj_dep = D(dist_matriz, idx, nj, deposito_id)
                    if np.isfinite(di_dep) and np.isfinite(dj_dep):
                        val += 0.15 * abs(float(di_dep) - float(dj_dep))
                if dist_hasta_valle is not None:
                    di_valle = dist_hasta_valle.get(int(ni), np.inf)
                    dj_valle = dist_hasta_valle.get(int(nj), np.inf)
                    if np.isfinite(di_valle) and np.isfinite(dj_valle):
                        val += 0.35 * abs(float(di_valle) - float(dj_valle))
            M[i, j] = M[j, i] = val
            if np.isfinite(val):
                vals_finitos.append(val)

    if vals_finitos:
        reemplazo = float(np.percentile(vals_finitos, 95) * 3.0)
    else:
        reemplazo = 1e6

    M[~np.isfinite(M)] = reemplazo
    np.fill_diagonal(M, 0.0)
    return nodos, M

def clusterizar_clientes_red_vial(G, nodos_clientes, dict_demanda, max_capacidad, lon_ref, lat_ref,
                                  dist_matriz=None, idx=None, deposito_id=None, dist_hasta_valle=None):
    if len(nodos_clientes) <= 1:
        return {int(nodos_clientes[0]): 0} if nodos_clientes else {}

    if dist_matriz is None or idx is None:
        raise ValueError("Se requiere dist_matriz e idx para clusterizar por red vial.")

    n_clusters = estimar_num_clusters(nodos_clientes, dict_demanda, max_capacidad)
    nodos_ordenados, M = construir_matriz_cluster_red_vial(
        nodos_clientes=nodos_clientes,
        dist_matriz=dist_matriz,
        idx=idx,
        deposito_id=deposito_id,
        dist_hasta_valle=dist_hasta_valle
    )

    model = AgglomerativeClustering(
        n_clusters=n_clusters,
        metric="precomputed",
        linkage="average"
    )
    labels = model.fit_predict(M)
    return {int(node): int(label) for node, label in zip(nodos_ordenados, labels)}

def estimar_umbral_salto_cluster(nodos_cluster, dist_matriz, idx, factor=8.0):
    if len(nodos_cluster) <= 2:
        return np.inf

    nearest = []
    for i in nodos_cluster:
        vecinos = [
            D(dist_matriz, idx, i, j)
            for j in nodos_cluster
            if i != j and np.isfinite(D(dist_matriz, idx, i, j))
        ]
        if vecinos:
            nearest.append(min(vecinos))

    if not nearest:
        return np.inf

    return float(np.median(nearest) * factor)

def validar_asignacion_unica(lista_viajes, nodos_esperados):
    esperados = {int(n) for n in nodos_esperados}
    vistos = []

    for viaje in lista_viajes:
        ruta = viaje.get("camino", [])
        if len(ruta) != len(set(int(n) for n in ruta)):
            raise ValueError(f"Ruta con nodos repetidos detectada: {ruta}")
        vistos.extend(int(n) for n in ruta)

    vistos_set = set(vistos)
    repetidos = sorted(n for n in vistos_set if vistos.count(n) > 1)
    faltantes = sorted(esperados - vistos_set)
    extras = sorted(vistos_set - esperados)

    if repetidos or faltantes or extras:
        raise ValueError(
            f"Asignación inválida. Repetidos={repetidos[:10]}, "
            f"faltantes={faltantes[:10]}, extras={extras[:10]}"
        )

# =========================================================
# 1) AHORROS Clarke & Wright (distancia)
# =========================================================
def calcular_ahorros_dist(nodos, dist_matriz, idx, deposito_id):
    """
    Savings clásico:
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

def costo_ruta_clientes_dist(camino, dist_matriz, idx, deposito_id):
    if not camino:
        return np.inf
    total = D(dist_matriz, idx, deposito_id, camino[0])
    for a, b in zip(camino[:-1], camino[1:]):
        total += D(dist_matriz, idx, a, b)
    total += D(dist_matriz, idx, camino[-1], deposito_id)
    return float(total)

def mejorar_ruta_2opt(camino, dist_matriz, idx, deposito_id, max_iter=60):
    """
    Mejora local simple sobre el orden de clientes.
    Reduce cruces y secuencias poco compactas sin cambiar capacidad.
    """
    if not camino or len(camino) < 4:
        return list(camino)

    mejor = list(camino)
    mejor_costo = costo_ruta_clientes_dist(mejor, dist_matriz, idx, deposito_id)
    mejorado = True
    iter_count = 0

    while mejorado and iter_count < max_iter:
        mejorado = False
        iter_count += 1
        for i in range(1, len(mejor) - 2):
            for j in range(i + 1, len(mejor)):
                candidato = mejor[:i] + list(reversed(mejor[i:j])) + mejor[j:]
                costo = costo_ruta_clientes_dist(candidato, dist_matriz, idx, deposito_id)
                if costo + 1e-9 < mejor_costo:
                    mejor = candidato
                    mejor_costo = costo
                    mejorado = True
                    break
            if mejorado:
                break
    return mejor

def dist_descarga_operativa_m(G, nodo_origen, nodo_relleno):
    try:
        path = shortest_path_obligando_via_valle(
            G, nodo_origen, nodo_relleno, prev_node=None, weight="travel_time",
            edge_usage=None, reuse_penalty_factor=0.0
        )
        return path_dist_m(G, path)
    except Exception:
        return np.nan

# =========================================================
# 2) EJECUTAR Clarke & Wright (distancia) con restricción de CAPACIDAD
# =========================================================
def ejecutar_clarke_wright_dist(nodos_clientes, dict_demanda, dist_matriz, idx, deposito_id, max_capacidad,
                                max_link_distance_m=np.inf, cluster_id=None):
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

        # i debe ser FINAL de su ruta, j debe ser INICIO de su ruta (C&W clásico)
        for r_id, datos in rutas.items():
            if datos['camino'][-1] == i:
                ruta_i_id = r_id
            if datos['camino'][0] == j:
                ruta_j_id = r_id

        if ruta_i_id and ruta_j_id and (ruta_i_id != ruta_j_id):
            d_union = D(dist_matriz, idx, i, j)
            if np.isfinite(max_link_distance_m) and d_union > max_link_distance_m:
                continue

            carga_total = rutas[ruta_i_id]['carga'] + rutas[ruta_j_id]['carga']
            if carga_total <= max_capacidad:
                rutas[ruta_i_id]['camino'] = rutas[ruta_i_id]['camino'] + rutas[ruta_j_id]['camino']
                rutas[ruta_i_id]['carga']  = carga_total
                del rutas[ruta_j_id]

    rutas_finales = list(rutas.values())
    for ruta in rutas_finales:
        ruta["camino"] = mejorar_ruta_2opt(ruta["camino"], dist_matriz, idx, deposito_id)
    if cluster_id is not None:
        for ruta in rutas_finales:
            ruta["cluster_id"] = int(cluster_id)
    return rutas_finales

def ejecutar_clarke_wright_por_clusters(G, nodos_clientes, dict_demanda, dist_matriz, idx, deposito_id,
                                        max_capacidad, lon_ref, lat_ref):
    if nodo_valle_ciudad is not None:
        G_rev = G.reverse(copy=False)
        dist_hasta_valle = nx.single_source_dijkstra_path_length(G_rev, nodo_valle_ciudad, weight="length")
    else:
        dist_hasta_valle = None

    mapa_clusters = clusterizar_clientes_red_vial(
        G=G,
        nodos_clientes=nodos_clientes,
        dict_demanda=dict_demanda,
        max_capacidad=max_capacidad,
        lon_ref=lon_ref,
        lat_ref=lat_ref,
        dist_matriz=dist_matriz,
        idx=idx,
        deposito_id=deposito_id,
        dist_hasta_valle=dist_hasta_valle
    )

    clusters = {}
    for nodo in nodos_clientes:
        cluster_id = mapa_clusters[int(nodo)]
        clusters.setdefault(cluster_id, []).append(nodo)

    lista_viajes = []
    print(f"Zonas detectadas para ruteo por red vial: {len(clusters)}")

    for cluster_id, nodos_cluster in sorted(clusters.items()):
        umbral_salto = estimar_umbral_salto_cluster(nodos_cluster, dist_matriz, idx)
        print(
            f"  -> Cluster {cluster_id}: {len(nodos_cluster)} nodos | "
            f"umbral salto {umbral_salto/1000.0:.2f} km"
        )
        viajes_cluster = ejecutar_clarke_wright_dist(
            nodos_clientes=nodos_cluster,
            dict_demanda=dict_demanda,
            dist_matriz=dist_matriz,
            idx=idx,
            deposito_id=deposito_id,
            max_capacidad=max_capacidad,
            max_link_distance_m=umbral_salto,
            cluster_id=cluster_id
        )
        lista_viajes.extend(viajes_cluster)

    validar_asignacion_unica(lista_viajes, nodos_clientes)
    return lista_viajes, mapa_clusters

# =========================================================
# 3) TIEMPOS (COMPATIBLES CON CELDA 6)
# =========================================================
def tiempo_viaje_desde_dist_s(ruta_clientes, dist_matriz, idx, estacion_id, deposito_id,
                             origen_es_estacion=True,
                             incluir_recoleccion=True):
    """
    Tiempo de UN VIAJE (sin retorno final a estación), igual que CELDA 6:
      - Origen (estación si primer viaje, depósito si no) -> primer cliente: 40
      - Entre clientes: 10 + 60s por parada (opcional)
      - Último cliente -> depósito: 30
    """
    if not ruta_clientes:
        return np.inf

    total = 0.0

    # 1) Aproximación (40)
    origen = estacion_id if origen_es_estacion else deposito_id
    total += tiempo_segundos(D(dist_matriz, idx, origen, ruta_clientes[0]), V_ESTACION_A_PRIMERO)

    # 2) Interno (10) + recolección
    if incluir_recoleccion:
        total += TIEMPO_RECOLECCION_POR_NODO  # primera parada

    for a, b in zip(ruta_clientes[:-1], ruta_clientes[1:]):
        total += tiempo_segundos(D(dist_matriz, idx, a, b), V_RECOLECCION)
        if incluir_recoleccion:
            total += TIEMPO_RECOLECCION_POR_NODO

    # 3) Descarga (30)
    dist_descarga = dist_descarga_operativa_m(G, ruta_clientes[-1], deposito_id)
    if not np.isfinite(dist_descarga):
        dist_descarga = D(dist_matriz, idx, ruta_clientes[-1], deposito_id)
    total += tiempo_segundos(dist_descarga, V_ULTIMO_A_DEPOSITO)

    return total

def tiempo_fin_turno_s(dist_matriz, idx, deposito_id, estacion_id):
    """Retorno final depósito -> estación (40)."""
    return tiempo_segundos(D(dist_matriz, idx, deposito_id, estacion_id), V_DEPOSITO_A_EST)

print("Funciones C&W (distancia) compiladas y tiempos alineados con CELDA 6 ✅")

# CELDA 5: Generación de Rutas Optimizadas (Viajes) + métricas compatibles con CELDA 6

CAPACIDAD_MAXIMA_KG = 9000.0

print("Optimizando rutas de recolección (Clarke & Wright con DISTANCIAS)...")

# 1) Ejecutar Clarke & Wright por clusters espaciales
lista_viajes, mapa_clusteres = ejecutar_clarke_wright_por_clusters(
    G=G,
    nodos_clientes=nodos_clientes,
    dict_demanda=dict_demandas,
    dist_matriz=dist_m,
    idx=idx,
    deposito_id=id_relleno,
    max_capacidad=CAPACIDAD_MAXIMA_KG,
    lon_ref=loc_estacion[1],
    lat_ref=loc_estacion[0]
)

print(f"\n✅ RESULTADO: Se han generado {len(lista_viajes)} viajes (rutas de clientes) para recoger toda la basura.\n")

# Helpers de distancia por matriz
def dist_ab_m(a, b):
    return dist_m[idx[a], idx[b]]

# 2) Enriquecer cada viaje con:
#    - distancias por tramos (Aprox, Recol, Desc)
#    - tiempos por tramos (desde Estación y desde Relleno)
#    - (NO incluye retorno final Relleno->Estación, eso es CELDA 6)
for k, viaje in enumerate(lista_viajes, 1):
    ruta = viaje["camino"]
    if not ruta:
        viaje["valido"] = False
        continue

    primer = ruta[0]
    ultimo = ruta[-1]

    # -------------------------
    # Distancias (m) por tramos
    # -------------------------
    # Aproximación desde estación y desde relleno (porque CELDA 6 decide)
    d_aprox_est_m = dist_ab_m(id_estacion, primer)
    d_aprox_rel_m = dist_ab_m(id_relleno,  primer)

    # Recolección (solo entre clientes consecutivos)
    d_recol_m = 0.0
    ok_recol = True
    for a, b in zip(ruta[:-1], ruta[1:]):
        dab = dist_ab_m(a, b)
        if not np.isfinite(dab):
            ok_recol = False
            break
        d_recol_m += dab
    if not ok_recol:
        d_recol_m = np.inf

    # Descarga (último -> relleno)
    d_desc_m = dist_ab_m(ultimo, id_relleno)

    # Total viaje (sin fin de turno)
    d_total_est_m = d_aprox_est_m + d_recol_m + d_desc_m
    d_total_rel_m = d_aprox_rel_m + d_recol_m + d_desc_m

    # -------------------------
    # Tiempos (s) por viaje (compatibles con CELDA 6)
    # -------------------------
    # OJO: esta función YA incluye TIEMPO_RECOLECCION_POR_NODO (60s/parada)
    t_desde_est_s = tiempo_viaje_desde_dist_s(
        ruta_clientes=ruta,
        dist_matriz=dist_m,
        idx=idx,
        estacion_id=id_estacion,
        deposito_id=id_relleno,
        origen_es_estacion=True,
        incluir_recoleccion=True
    )

    t_desde_rel_s = tiempo_viaje_desde_dist_s(
        ruta_clientes=ruta,
        dist_matriz=dist_m,
        idx=idx,
        estacion_id=id_estacion,
        deposito_id=id_relleno,
        origen_es_estacion=False,
        incluir_recoleccion=True
    )

    # Marcar validez (si algo es infinito, ese viaje es problemático)
    valido = all(np.isfinite(x) for x in [d_aprox_est_m, d_aprox_rel_m, d_recol_m, d_desc_m, t_desde_est_s, t_desde_rel_s])
    viaje["valido"] = bool(valido)

    # Guardar métricas en el viaje
    viaje["paradas"] = len(ruta)
    viaje["cluster_id"] = int(viaje.get("cluster_id", -1))

    viaje["dist_tramos_m"] = {
        "aprox_desde_estacion": float(d_aprox_est_m),
        "aprox_desde_relleno":  float(d_aprox_rel_m),
        "recoleccion":          float(d_recol_m),
        "descarga":             float(d_desc_m),
    }

    viaje["dist_total_km"] = {
        "si_sale_estacion": float(d_total_est_m / 1000.0),
        "si_sale_relleno":  float(d_total_rel_m / 1000.0),
    }

    viaje["tiempo_s"] = {
        "si_sale_estacion": float(t_desde_est_s),
        "si_sale_relleno":  float(t_desde_rel_s),
    }

    viaje["tiempo_min"] = {
        "si_sale_estacion": float(t_desde_est_s / 60.0),
        "si_sale_relleno":  float(t_desde_rel_s / 60.0),
    }

    # Impresión resumida (para que sea legible)
    print(
        f"Viaje {k:>3} | Zona {viaje['cluster_id']:>2}: {len(ruta):>3} paradas | "
        f"Carga: {viaje['carga']:.2f} kg | "
        f"Dist(km) Est:{viaje['dist_total_km']['si_sale_estacion']:.2f} / Rel:{viaje['dist_total_km']['si_sale_relleno']:.2f} | "
        f"Tiempo(min) Est:{viaje['tiempo_min']['si_sale_estacion']:.1f} / Rel:{viaje['tiempo_min']['si_sale_relleno']:.1f} | "
        f"OK:{viaje['valido']}"
    )

# Nota útil: el retorno final del turno (relleno -> estación) se calcula en CELDA 6:
# t_retorno_casa = tiempo_fin_turno_s(dist_m, idx, id_relleno, id_estacion)

# CELDA 6 (V2.2): Asignación de Viajes BALANCEADA (Best-Fit Decreasing)
import numpy as np

HORAS_TRABAJO = 8 * 3600  # 8 horas (s)

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

V_DEPOSITO_A_EST = 40.0
t_retorno_casa = T(id_relleno, id_estacion, V_DEPOSITO_A_EST)
print(f"Tiempo de seguridad (Relleno -> Estación): {t_retorno_casa/60:.2f} min")

if not np.isfinite(t_retorno_casa):
    print("⚠️ No hay camino Relleno -> Estación en la matriz de distancias.")
    print("   Solución típica: recalcular dist_m con un grafo no dirigido (nx.Graph(G)).")

# ---------------------------------------------------------
# 1) Lista de viajes válidos
# ---------------------------------------------------------
viajes_pendientes = [v for v in lista_viajes if v.get("valido", True) and v.get("camino", [])]

# Ordenar “más largos primero” (clave para balancear)
# Usamos el peor caso entre salir estación o relleno como criterio de tamaño.
viajes_pendientes.sort(
    key=lambda v: max(v["tiempo_s"]["si_sale_estacion"], v["tiempo_s"]["si_sale_relleno"]),
    reverse=True
)

# ---------------------------------------------------------
# 2) Estructura de camiones (sin retorno aún)
# ---------------------------------------------------------
camiones = []  # cada camión: {"id", "viajes", "tiempo_s_sin_retorno"}
id_camion = 1

def tiempo_viaje_para_camion(viaje, camion):
    """
    Si camion aún no tiene viajes => sale estación
    Si ya tiene => sale relleno
    """
    es_primer = (len(camion["viajes"]) == 0)
    if es_primer:
        return "Estación", viaje["tiempo_s"]["si_sale_estacion"], viaje["dist_tramos_m"]["aprox_desde_estacion"]
    else:
        return "Relleno",  viaje["tiempo_s"]["si_sale_relleno"],  viaje["dist_tramos_m"]["aprox_desde_relleno"]

def cabe_en_camion(viaje, camion):
    origen, t_viaje_s, _ = tiempo_viaje_para_camion(viaje, camion)
    if not np.isfinite(t_viaje_s):
        return False
    # regla estricta: tiempo actual + viaje + retorno <= 8h
    return (camion["tiempo_s_sin_retorno"] + t_viaje_s + t_retorno_casa) <= HORAS_TRABAJO

def score_best_fit(viaje, camion):
    """
    Queremos el camión que quede MÁS lleno (proyectado) pero sin pasarse.
    Score = tiempo proyectado sin retorno (mientras más alto, mejor).
    """
    _, t_viaje_s, _ = tiempo_viaje_para_camion(viaje, camion)
    return camion["tiempo_s_sin_retorno"] + t_viaje_s

# ---------------------------------------------------------
# 3) Asignación Best-Fit Decreasing
# ---------------------------------------------------------
for viaje in viajes_pendientes:
    mejor_idx = None
    mejor_score = -np.inf

    # intentar meterlo en un camión existente
    for k, cam in enumerate(camiones):
        if cabe_en_camion(viaje, cam):
            sc = score_best_fit(viaje, cam)
            if sc > mejor_score:
                mejor_score = sc
                mejor_idx = k

    # si no cabe en ninguno, crear camión nuevo
    if mejor_idx is None:
        camiones.append({
            "id": id_camion,
            "viajes": [],
            "tiempo_s_sin_retorno": 0.0
        })
        mejor_idx = len(camiones) - 1
        id_camion += 1

        # si ni como primer viaje cabe, es un viaje imposible en 8h
        if not cabe_en_camion(viaje, camiones[mejor_idx]):
            print("⚠️ Viaje no cabe ni como primer viaje con retorno. Revisa parámetros/velocidades/zona.")
            continue

    cam = camiones[mejor_idx]
    origen, t_viaje_s, d_aprox_m = tiempo_viaje_para_camion(viaje, cam)

    # distancias del viaje
    ruta = viaje["camino"]
    d_recol_m = viaje["dist_tramos_m"]["recoleccion"]
    d_desc_m  = viaje["dist_tramos_m"]["descarga"]

    # tiempos por tramos (aprox/desc por velocidad fija, interno = resto)
    t_aprox_s = tiempo_segundos(d_aprox_m, 40.0)
    t_desc_s  = tiempo_segundos(d_desc_m, 30.0)
    t_int_s   = t_viaje_s - t_aprox_s - t_desc_s

    cam["viajes"].append({
        "nodos": ruta,
        "carga": float(viaje["carga"]),
        "cluster_id": int(viaje.get("cluster_id", -1)),
        "origen": origen,
        "costos": {
            "aprox_s": float(t_aprox_s),
            "interno_s": float(max(0.0, t_int_s)),
            "descarga_s": float(t_desc_s),
        },
        "distancias_m": {
            "aprox_m": float(d_aprox_m),
            "recoleccion_m": float(d_recol_m),
            "descarga_m": float(d_desc_m),
        }
    })

    cam["tiempo_s_sin_retorno"] += float(t_viaje_s)

# ---------------------------------------------------------
# 4) Cerrar turnos (agregar retorno)
# ---------------------------------------------------------
camiones_final = []
for cam in camiones:
    tiempo_total = cam["tiempo_s_sin_retorno"] + t_retorno_casa

    camiones_final.append({
        "id": cam["id"],
        "viajes": cam["viajes"],
        "tiempo_total_s": float(tiempo_total),
        "tiempo_total_h": float(tiempo_total / 3600.0),
        "retorno_final": True
    })

# imprimir resumen
for c in camiones_final:
    print(f"\n--- Camión {c['id']} ---")
    print(f"Viajes asignados: {len(c['viajes'])}")
    print(f"Tiempo turno: {c['tiempo_total_h']:.2f} horas (incluye retorno)")

camiones = camiones_final
print(f"\n✅ RESUMEN FINAL (balanceado): Se necesitan {len(camiones)} camiones.")

# CELDA 7 (COMPLETA): Densidad poblacional real (hab/km²) por nodo usando raster de densidad + fallback vecindario
import geopandas as gpd
import pandas as pd
import numpy as np
from shapely.geometry import Point
from shapely.geometry import mapping

try:
    import rasterio
    from rasterio.mask import mask
    from rasterio.windows import Window
except ImportError:
    rasterio = None
    mask = None
    Window = None

POP_RASTER_PATH = "ecu_pd_2020_1km.tif"
RADIO_M = 500  # buffer en metros (ajusta 200-800 según zona)

print("Calculando densidad poblacional (hab/km²) por nodo...")

# ---------------------------------------------------------
# A) Construir GeoDataFrame de puntos clientes (WGS84)
# ---------------------------------------------------------
gdf_pts = gpd.GeoDataFrame(
    [{
        "id_nodo": int(n),
        "demanda_kg": float(dict_demandas.get(n, 0.0)),
        "geometry": Point(G.nodes[n]['x'], G.nodes[n]['y'])
    } for n in nodos_clientes],
    crs="EPSG:4326"
)

print("  -> Puntos clientes:", len(gdf_pts))

# ---------------------------------------------------------
# B) Buffer en metros: reproyectar a UTM para área real
# ---------------------------------------------------------
utm_crs = gdf_pts.estimate_utm_crs()
gdf_m = gdf_pts.to_crs(utm_crs)
gdf_m["buffer"] = gdf_m.geometry.buffer(RADIO_M)

# Área confiable (km²) desde UTM
area_km2 = (gdf_m["buffer"].area / 1e6).values  # km²

# ---------------------------------------------------------
# C) Helpers: promedio en buffer + fallback vecindario
# ---------------------------------------------------------
def nanmean_from_mask(src, geom, nodata):
    """Promedio de valores válidos dentro de un polígono (buffer)."""
    out_img, _ = mask(src, [mapping(geom)], crop=True)
    band = out_img[0].astype(float)
    if nodata is not None:
        band[band == nodata] = np.nan
    if np.all(np.isnan(band)):
        return np.nan
    return float(np.nanmean(band))

def densidad_vecindario(src, x, y, nodata, half_windows_px=(0, 1, 2, 3, 5, 8, 12, 20)):
    """
    Fallback: busca densidad válida alrededor del punto (x,y) en ventanas crecientes.
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
# D) Leer raster y calcular densidad/población por nodo
# ---------------------------------------------------------
densidades = []
poblaciones = []

if rasterio is None:
    print("⚠️ rasterio no está instalado. Se omitirá la densidad poblacional real.")
    densidades = [np.nan] * len(gdf_pts)
    poblaciones = [np.nan] * len(gdf_pts)
elif not os.path.exists(POP_RASTER_PATH):
    print(f"⚠️ No se encontró el raster de población: {POP_RASTER_PATH}. Se omitirá esta capa.")
    densidades = [np.nan] * len(gdf_pts)
    poblaciones = [np.nan] * len(gdf_pts)
else:
    with rasterio.open(POP_RASTER_PATH) as src:
        nodata = src.nodata

    # buffers al CRS del raster
        gdf_buf = gdf_m.set_geometry("buffer").to_crs(src.crs)
    # puntos al CRS del raster (para fallback vecindario)
        gdf_pts_r = gdf_pts.to_crs(src.crs)

        for geom_buf, pt, a_km2 in zip(gdf_buf.geometry, gdf_pts_r.geometry, area_km2):
        # 1) intento con buffer (promedio dentro del área)
            dens = np.nan
            try:
                dens = nanmean_from_mask(src, geom_buf, nodata)
            except Exception:
                dens = np.nan

        # 2) si buffer es NaN -> fallback vecindario (pixel cercano válido)
            if not np.isfinite(dens):
                dens = densidad_vecindario(src, pt.x, pt.y, nodata)

        # 3) población estimada (densidad hab/km² * área km²)
            pop = float(dens * a_km2) if np.isfinite(dens) else np.nan

            densidades.append(dens)
            poblaciones.append(pop)

# Guardar resultados en gdf_pts (WGS84)
gdf_pts["densidad_pob_km2"] = np.array(densidades, dtype=float)
gdf_pts["pob_buffer"] = np.array(poblaciones, dtype=float)

# ---------------------------------------------------------
# E) Diagnóstico
# ---------------------------------------------------------
n_total = len(gdf_pts)
n_nan = int(np.isnan(gdf_pts["densidad_pob_km2"]).sum())

print("\n✅ Resultado CELDA 7")
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

# CELDA 8 (V2.1.2): Exportación QGIS (Base + Tramos con De/A) -> varios archivos + densidad poblacional real en clientes
import geopandas as gpd
from shapely.geometry import Point, LineString
import numpy as np
import networkx as nx
import osmnx as ox
import os

print("--- INICIANDO EXPORTACIÓN A QGIS (V2.1.2) ---")

# =========================================================
# Helpers (MultiDiGraph safe)
# =========================================================
def best_edge_attr(G, u, v, attr, default=0.0):
    data = G.get_edge_data(u, v)
    if data is None:
        return default
    if isinstance(data, dict):  # MultiDiGraph
        best = None
        for _, attrs in data.items():
            val = float(attrs.get(attr, default))
            if best is None or val < best:
                best = val
        return float(best if best is not None else default)
    return float(data.get(attr, default))

def best_edge_data_dict(G, u, v):
    data = G.get_edge_data(u, v)
    if data is None:
        return {}
    if isinstance(data, dict):
        best_attrs = None
        best_length = np.inf
        for _, attrs in data.items():
            length = float(attrs.get("length", np.inf))
            if best_attrs is None or length < best_length:
                best_attrs = attrs
                best_length = length
        return best_attrs or {}
    return data

def path_street_summary(G, path, max_names=6):
    nombres = []
    for u, v in zip(path[:-1], path[1:]):
        attrs = best_edge_data_dict(G, u, v)
        nombre = attrs.get("name", "Sin nombre")
        if isinstance(nombre, list):
            nombre = " / ".join(str(x) for x in nombre[:2])
        nombre = str(nombre)
        if not nombres or nombres[-1] != nombre:
            nombres.append(nombre)
    if len(nombres) > max_names:
        nombres = nombres[:max_names] + ["..."]
    return " -> ".join(nombres)

def path_oneway_pct(G, path):
    total = 0
    oneway = 0
    for u, v in zip(path[:-1], path[1:]):
        attrs = best_edge_data_dict(G, u, v)
        total += 1
        val = attrs.get("oneway", False)
        if isinstance(val, str):
            val = val.lower() in {"yes", "true", "1", "-1"}
        if bool(val):
            oneway += 1
    return float((100.0 * oneway / total) if total > 0 else 0.0)

def edge_usage_key(u, v):
    """Clave no dirigida para penalizar reuso del mismo tramo vial en cualquier sentido."""
    a, b = int(u), int(v)
    return (a, b) if a <= b else (b, a)

def registrar_uso_aristas(path, edge_usage):
    if edge_usage is None or not path or len(path) < 2:
        return
    for u, v in zip(path[:-1], path[1:]):
        k = edge_usage_key(u, v)
        edge_usage[k] = edge_usage.get(k, 0) + 1

def unir_paths(*paths):
    salida = []
    for path in paths:
        if not path:
            continue
        if not salida:
            salida.extend(path)
        else:
            salida.extend(path[1:] if salida[-1] == path[0] else path)
    return salida

def shortest_path_sin_retorno_inmediato(G, origen, destino, prev_node=None, weight="travel_time",
                                        edge_usage=None, reuse_penalty_factor=3.0):
    """
    Evita un U-giro inmediato al salir del nodo origen hacia el nodo del que se acaba de llegar.
    Además penaliza calles ya usadas para preferir tramos no recorridos si existe alternativa razonable.
    """
    G_search = G
    if prev_node is not None and G.has_edge(origen, prev_node):
        G_search = G.copy()
        G_search.remove_edges_from([(origen, prev_node, k) for k in list(G_search[origen][prev_node].keys())])

    def peso_penalizado(u, v, d):
        if isinstance(d, dict) and d and all(isinstance(val, dict) for val in d.values()):
            attrs_iter = d.values()
        else:
            attrs_iter = [d]

        mejor = np.inf
        uso = edge_usage.get(edge_usage_key(u, v), 0) if edge_usage else 0
        for attrs in attrs_iter:
            base = float(attrs.get(weight, np.inf))
            if not np.isfinite(base):
                continue
            penalizado = base * (1.0 + reuse_penalty_factor * uso)
            if penalizado < mejor:
                mejor = penalizado
        return mejor

    try:
        return nx.shortest_path(G_search, origen, destino, weight=peso_penalizado)
    except Exception:
        return nx.shortest_path(G, origen, destino, weight=weight)

def shortest_path_obligando_via_valle(G, origen, destino, prev_node=None, weight="travel_time",
                                      edge_usage=None, reuse_penalty_factor=3.0):
    """
    Fuerza el tránsito hacia el relleno pasando por el corredor operativo de Vía al Valle.
    """
    if not path_valle_central or nodo_valle_ciudad is None or nodo_valle_relleno is None:
        return shortest_path_sin_retorno_inmediato(
            G, origen, destino, prev_node=prev_node, weight=weight,
            edge_usage=edge_usage, reuse_penalty_factor=reuse_penalty_factor
        )

    path_1 = shortest_path_sin_retorno_inmediato(
        G, origen, nodo_valle_ciudad, prev_node=prev_node, weight=weight,
        edge_usage=edge_usage, reuse_penalty_factor=reuse_penalty_factor
    )
    path_2 = path_valle_central
    path_3 = shortest_path_sin_retorno_inmediato(
        G, nodo_valle_relleno, destino, prev_node=None, weight=weight,
        edge_usage=edge_usage, reuse_penalty_factor=reuse_penalty_factor
    )
    return unir_paths(path_1, path_2, path_3)

def path_to_linestring(G, path):
    coords = [(G.nodes[n]['x'], G.nodes[n]['y']) for n in path]
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
    """Distancia (m) del camino más corto ruteado por travel_time (usa length)."""
    try:
        path = nx.shortest_path(G, u, v, weight="travel_time")
        return path_dist_m(G, path)
    except Exception:
        return np.nan

def dist_recoleccion_m(G, nodos_ruta):
    """Distancia (m) ruta interna recolección (cliente->cliente ruteado por travel_time)."""
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
    print("✅ Densidad poblacional detectada desde CELDA 7 (gdf_pts).")
else:
    gdf_dens = None
    print("⚠️ No encuentro gdf_pts de CELDA 7. Se exportarán clientes SIN densidad poblacional real.")

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
        "cluster_id": int(mapa_clusteres.get(n_int, -1)),
        "demanda_kg": round(demanda, 2),
        "dist_a_estacion_m": dist_ruteada_m(G, id_estacion, n),
        "dist_a_relleno_m": dist_ruteada_m(G, n, id_relleno),
        "geometry": Point(G.nodes[n]['x'], G.nodes[n]['y'])
    })

gdf_clientes = gpd.GeoDataFrame(data_clientes, crs="EPSG:4326")

# 👉 Join con densidad poblacional real si existe
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
# 2) TRAMOS POR CAMIÓN (1 archivo GPKG por camión)
# =========================================================
print("\n2) Generando tramos por camión/viaje (un GPKG por camión)...")

# Heurística global: penaliza reusar calles ya recorridas por la flota
# mientras existan alternativas razonables en la red.
edge_usage_global = {}

for camion in camiones:
    c_id = camion["id"]
    features = []
    orden_local = 1

    for i, viaje in enumerate(camion["viajes"], start=1):
        nodos_ruta = viaje["nodos"]
        if not nodos_ruta:
            continue

        primer = nodos_ruta[0]
        ultimo = nodos_ruta[-1]
        cluster_id = int(viaje.get("cluster_id", -1))

        # Origen del viaje según CELDA 6
        if viaje["origen"] == "Estación":
            origen_nodo = id_estacion
            de_aprox = "Estación"
        else:
            origen_nodo = id_relleno
            de_aprox = "Relleno"

        # TRAMO 1: APROXIMACIÓN
        prev_incoming_node = None
        try:
            path = shortest_path_sin_retorno_inmediato(
                G,
                origen_nodo,
                primer,
                prev_node=None,
                weight="travel_time",
                edge_usage=edge_usage_global
            )
            geom_line = path_to_linestring(G, path)
            if geom_line is not None:
                if len(path) >= 2:
                    prev_incoming_node = path[-2]
                registrar_uso_aristas(path, edge_usage_global)
                features.append({
                    "Camion": c_id,
                    "Viaje": i,
                    "Cluster": cluster_id,
                    "Tramo": "Aprox",
                    "De": de_aprox,
                    "A": "Recolección",
                    "Sentido": f"{de_aprox} -> Recolección",
                    "Nodo_Inicio": int(origen_nodo),
                    "Nodo_Fin": int(primer),
                    "Paradas": 0,
                    "Carga_kg": 0.0,
                    "Calles": path_street_summary(G, path),
                    "OneWayPct": round(path_oneway_pct(G, path), 2),
                    "dur_s": float(viaje["costos"]["aprox_s"]),
                    "dist_m": path_dist_m(G, path),
                    "orden": orden_local,
                    "geometry": geom_line
                })
                orden_local += 1
        except:
            pass

        # TRAMO 2: RECOLECCIÓN
        coords_recol = []
        path_recol_nodos = []
        try:
            for k in range(len(nodos_ruta) - 1):
                seg = shortest_path_sin_retorno_inmediato(
                    G,
                    nodos_ruta[k],
                    nodos_ruta[k+1],
                    prev_node=prev_incoming_node,
                    weight="travel_time",
                    edge_usage=edge_usage_global
                )
                if k == 0:
                    coords_recol += [(G.nodes[n]['x'], G.nodes[n]['y']) for n in seg]
                    path_recol_nodos += seg
                else:
                    coords_recol += [(G.nodes[n]['x'], G.nodes[n]['y']) for n in seg[1:]]
                    path_recol_nodos += seg[1:]
                registrar_uso_aristas(seg, edge_usage_global)
                if len(seg) >= 2:
                    prev_incoming_node = seg[-2]

            if len(coords_recol) >= 2:
                dist_recol = path_dist_m(G, path_recol_nodos)

                features.append({
                    "Camion": c_id,
                    "Viaje": i,
                    "Cluster": cluster_id,
                    "Tramo": "Recol",
                    "De": "Recolección",
                    "A": "Recolección",
                    "Sentido": "Recolección -> Recolección",
                    "Nodo_Inicio": int(primer),
                    "Nodo_Fin": int(ultimo),
                    "Paradas": int(len(nodos_ruta)),
                    "Carga_kg": float(viaje["carga"]),
                    "Calles": path_street_summary(G, path_recol_nodos),
                    "OneWayPct": round(path_oneway_pct(G, path_recol_nodos), 2),
                    "dur_s": float(viaje["costos"]["interno_s"]),
                    "dist_m": dist_recol,
                    "orden": orden_local,
                    "geometry": LineString(coords_recol)
                })
                orden_local += 1
        except:
            pass

        # TRAMO 3: DESCARGA
        try:
            path = shortest_path_obligando_via_valle(
                G,
                ultimo,
                id_relleno,
                prev_node=prev_incoming_node,
                weight="travel_time",
                edge_usage=edge_usage_global
            )
            geom_line = path_to_linestring(G, path)
            if geom_line is not None:
                registrar_uso_aristas(path, edge_usage_global)
                features.append({
                    "Camion": c_id,
                    "Viaje": i,
                    "Cluster": cluster_id,
                    "Tramo": "Desc",
                    "De": "Recolección",
                    "A": "Relleno",
                    "Sentido": "Recolección -> Relleno",
                    "Nodo_Inicio": int(ultimo),
                    "Nodo_Fin": int(id_relleno),
                    "Paradas": 0,
                    "Carga_kg": 0.0,
                    "Calles": path_street_summary(G, path),
                    "OneWayPct": round(path_oneway_pct(G, path), 2),
                    "dur_s": float(viaje["costos"]["descarga_s"]),
                    "dist_m": path_dist_m(G, path),
                    "orden": orden_local,
                    "geometry": geom_line
                })
                orden_local += 1
        except:
            pass

    # FIN DEL TURNO
    try:
        path = shortest_path_sin_retorno_inmediato(
            G,
            id_relleno,
            id_estacion,
            prev_node=None,
            weight="travel_time",
            edge_usage=edge_usage_global
        )
        geom_line = path_to_linestring(G, path)
        if geom_line is not None:
            dur_fin = float(globals().get("t_retorno_casa", path_time_s(G, path)))
            registrar_uso_aristas(path, edge_usage_global)

            features.append({
                "Camion": c_id,
                "Viaje": "FIN",
                "Cluster": -1,
                "Tramo": "Fin",
                "De": "Relleno",
                "A": "Estación",
                "Sentido": "Relleno -> Estación",
                "Nodo_Inicio": int(id_relleno),
                "Nodo_Fin": int(id_estacion),
                "Paradas": 0,
                "Carga_kg": 0.0,
                "Calles": path_street_summary(G, path),
                "OneWayPct": round(path_oneway_pct(G, path), 2),
                "dur_s": dur_fin,
                "dist_m": path_dist_m(G, path),
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
        print(f"  ✅ Camión {c_id}: Guardado {out_gpkg} (layer='tramos', {len(gdf_tramos)} tramos)")
    else:
        print(f"  ⚠️ Camión {c_id}: No se generaron tramos (features vacío). Revisa viajes.")

print("\n✅ ¡PROCESO TERMINADO! Archivos generados:")
print("  - base_calles.gpkg")
print("  - base_clientes.gpkg  (incluye demanda_kg + densidad_pob_km2 + pob_buffer + dist_a_* )")
print("  - base_puntos_clave.gpkg")
print("  - rutas_tramos_Camion_X.gpkg (uno por camión)")

# CELDA 9 (V3.2): Bitácora MACRO por TRAMOS + CSV (con distancias en todos los tramos)
import pandas as pd
import numpy as np
import networkx as nx

print("Generando bitácora MACRO por TRAMOS (Estación/Recolección/Relleno/Fin)...")

filas = []

# -------------------------------
# Helpers MultiDiGraph safe (idénticos a CELDA 8)
# -------------------------------
def best_edge_attr(G, u, v, attr, default=0.0):
    data = G.get_edge_data(u, v)
    if data is None:
        return default
    if isinstance(data, dict):  # MultiDiGraph
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
    """Distancia (km) del camino más corto ruteado por travel_time."""
    try:
        path = nx.shortest_path(G, u, v, weight="travel_time")
        return path_dist_m(G, path) / 1000.0
    except Exception:
        return np.nan

def dist_km_recoleccion(G, nodos_ruta):
    """
    Distancia (km) de la ruta interna de recolección:
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
# Bitácora por camión (macro-tramos)
# -------------------------------
for camion in camiones:
    c_id = camion["id"]

    for v_num, viaje in enumerate(camion["viajes"], start=1):
        nodos = viaje["nodos"]
        if not nodos:
            continue

        primer = nodos[0]
        ultimo = nodos[-1]

        # TRAMO A: Origen -> Recolección
        if viaje["origen"] == "Estación":
            origen_nodo = id_estacion
            origen_tipo = "Estación"
        else:
            origen_nodo = id_relleno
            origen_tipo = "Relleno"

        t_aprox_s = float(viaje["costos"]["aprox_s"])
        d_aprox_km = dist_km_ruteada(G, origen_nodo, primer)

        filas.append({
            "Camión": c_id,
            "Paso": f"V{v_num}-A",
            "Tramo": "Origen→Recolección",
            "De": origen_tipo,
            "A": "Recolección",
            "Nodo_De": int(origen_nodo),
            "Nodo_A": int(primer),
            "Paradas_en_recolección": 0,
            "Carga_kg": 0.0,
            "Dist_km": d_aprox_km,
            "Min": t_aprox_s / 60.0
        })

        # TRAMO B: Recolección (operación) + distancia interna
        t_int_s = float(viaje["costos"]["interno_s"])
        d_recol_km = dist_km_recoleccion(G, nodos)

        filas.append({
            "Camión": c_id,
            "Paso": f"V{v_num}-B",
            "Tramo": "Recolección (operación)",
            "De": "Recolección",
            "A": "Recolección",
            "Nodo_De": int(primer),
            "Nodo_A": int(ultimo),
            "Paradas_en_recolección": int(len(nodos)),
            "Carga_kg": float(viaje["carga"]),   # ✅ la carga se reporta SOLO aquí
            "Dist_km": d_recol_km,
            "Min": t_int_s / 60.0
        })

        # TRAMO C: Recolección -> Relleno
        t_desc_s = float(viaje["costos"]["descarga_s"])
        d_desc_km = dist_km_ruteada(G, ultimo, id_relleno)

        filas.append({
            "Camión": c_id,
            "Paso": f"V{v_num}-C",
            "Tramo": "Recolección→Relleno",
            "De": "Recolección",
            "A": "Relleno",
            "Nodo_De": int(ultimo),
            "Nodo_A": int(id_relleno),
            "Paradas_en_recolección": 0,
            "Carga_kg": 0.0,                   # ✅ NO repetir carga (evita duplicar en resumen)
            "Dist_km": d_desc_km,
            "Min": t_desc_s / 60.0
        })

    # FIN DE TURNO: Relleno -> Estación
    d_fin_km = dist_km_ruteada(G, id_relleno, id_estacion)

    filas.append({
        "Camión": c_id,
        "Paso": "FIN",
        "Tramo": "Relleno→Estación (fin turno)",
        "De": "Relleno",
        "A": "Estación",
        "Nodo_De": int(id_relleno),
        "Nodo_A": int(id_estacion),
        "Paradas_en_recolección": 0,
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
    "Camión","Paso","Tramo","De","A",
    "Paradas_en_recolección","Carga_kg","Dist_km","Min",
    "Nodo_De","Nodo_A"
]
df_print = df_print[cols]

print("\n=== BITÁCORA MACRO (vista previa, 30 filas) ===")
print(df_print.head(30).to_string(index=False))

# CSV completo
df.to_csv("bitacora_macro_tramos.csv", index=False)
print("\n✅ Guardado completo: 'bitacora_macro_tramos.csv'")

# -------------------------------
# Resumen por camión (macro)
# -------------------------------
res = df.groupby("Camión").agg({
    "Carga_kg": "sum",
    "Dist_km": "sum",
    "Min": "sum",
    "Paradas_en_recolección": "sum"
}).reset_index()

res["Horas"] = (res["Min"] / 60.0).round(2)
res["Dist_km"] = res["Dist_km"].round(2)
res["Min"] = res["Min"].round(1)
res["Carga_kg"] = res["Carga_kg"].round(2)

print("\n=== RESUMEN POR CAMIÓN (MACRO) ===")
print(res[["Camión","Carga_kg","Dist_km","Min","Horas","Paradas_en_recolección"]].to_string(index=False))

# -------------------------------
# Resumen GLOBAL (estilo PDF)
# -------------------------------
total_camiones = int(res["Camión"].nunique())
total_ton = float(res["Carga_kg"].sum() / 1000.0)
total_km = float(res["Dist_km"].sum())
total_h = float(res["Horas"].sum())
total_paradas = int(res["Paradas_en_recolección"].sum())

print("\n=== RESUMEN GLOBAL (FLOTA) ===")
print(f"Camiones usados: {total_camiones}")
print(f"Basura total: {total_ton:.2f} ton")
print(f"Distancia total: {total_km:.2f} km")
print(f"Tiempo total flota: {total_h:.2f} h")
print(f"Paradas totales (recolección): {total_paradas}")

# Opcional: consumo/costo como en el PDF (ajusta a tu supuesto)
KM_POR_GALON = 5.0
COSTO_POR_GALON = 2.71
if total_km > 0 and KM_POR_GALON > 0:
    gal = total_km / KM_POR_GALON
    costo = gal * COSTO_POR_GALON
    print(f"Consumo estimado: {gal:.2f} gal")
    print(f"Costo estimado: ${costo:.2f}")
    print(f"Eficiencia: {(total_ton/total_km):.4f} ton/km")

# CELDA 9 (FIX): HTML Leaflet animado (capas + camiones 🚚 + velocidad) SIN f-string
import geopandas as gpd
import json
import os

# -----------------------------
# Archivos esperados
# -----------------------------
CLIENTES_GPKG = "base_clientes.gpkg"
PUNTOS_CLAVE_GPKG = "base_puntos_clave.gpkg"
CALLES_GPKG = "base_calles.gpkg"      # opcional (puede ser pesado)
INCLUIR_CALLES = False               # True si quieres calles en el HTML

CAMIONES = [int(c["id"]) for c in camiones]
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
        print(f"⚠️ No pude leer {path} ({e})")
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


# -----------------------------
# 2) Leer rutas por camión y convertir a lista de [lat, lon]
# -----------------------------
rutas_camiones = {}

for c in CAMIONES:
    path = RUTA_GPKG_FMT.format(c)
    gdf_tramos = leer_capa_gpkg(path, layer=LAYER_TRAMOS)

    if gdf_tramos is None or len(gdf_tramos) == 0:
        print(f"⚠️ Camión {c}: sin tramos")
        rutas_camiones[c] = {"coords": [], "tramos": [], "resumen": {"camion": c, "dist_km": 0.0, "dur_min": 0.0}}
        continue

    gdf_tramos = gdf_tramos.to_crs("EPSG:4326").copy()
    if "orden" in gdf_tramos.columns:
        gdf_tramos = gdf_tramos.sort_values("orden")

    coords = []
    tramos_payload = []
    for _, row in gdf_tramos.iterrows():
        geom = row.geometry
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

        tramos_payload.append({
            "viaje": str(row.get("Viaje", "")),
            "tramo": str(row.get("Tramo", "")),
            "de": str(row.get("De", "")),
            "a": str(row.get("A", "")),
            "sentido": str(row.get("Sentido", "")),
            "cluster": int(row.get("Cluster", -1)),
            "paradas": int(row.get("Paradas", 0)),
            "carga_kg": float(row.get("Carga_kg", 0.0)),
            "dist_km": float(row.get("dist_m", 0.0)) / 1000.0,
            "dur_min": float(row.get("dur_s", 0.0)) / 60.0,
            "calles": str(row.get("Calles", "")),
            "oneway_pct": float(row.get("OneWayPct", 0.0)),
            "coords": latlon
        })

    rutas_camiones[c] = {
        "coords": coords,
        "tramos": tramos_payload,
        "resumen": {
            "camion": int(c),
            "dist_km": float(gdf_tramos["dist_m"].fillna(0).sum() / 1000.0),
            "dur_min": float(gdf_tramos["dur_s"].fillna(0).sum() / 60.0),
            "n_tramos": int(len(tramos_payload))
        }
    }
    print(f"✅ Camión {c}: {len(coords)} puntos de ruta")


# -----------------------------
# 3) Template HTML (sin f-string)
# -----------------------------
html = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>Rutas animadas (Camiones)</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link
    rel="stylesheet"
    href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"
  />
  <style>
    html, body { height: 100%; margin: 0; }
    #map { width: 100%; height: 100%; }
    .control-panel {
      position: absolute;
      top: 12px; left: 12px;
      z-index: 9999;
      background: rgba(255,255,255,0.92);
      padding: 10px 12px;
      border-radius: 10px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.15);
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Arial;
      min-width: 260px;
    }
    .row { display: flex; gap: 8px; align-items: center; margin: 6px 0; }
    .row label { font-size: 13px; }
    .btn {
      cursor: pointer;
      border: 0;
      padding: 8px 10px;
      border-radius: 10px;
      background: #1f2937;
      color: white;
      font-weight: 600;
    }
    .btn:active { transform: translateY(1px); }
    .small { font-size: 12px; color: #374151; }
    .truck-icon {
      font-size: 22px;
      line-height: 22px;
      filter: drop-shadow(0 2px 2px rgba(0,0,0,0.25));
    }
    input[type="range"] { width: 170px; }
  </style>
</head>
<body>
<div id="map"></div>

<div class="control-panel">
  <div class="row">
    <button id="btnPlay" class="btn">▶ Reproducir</button>
    <button id="btnPause" class="btn" style="background:#6b7280;">⏸ Pausa</button>
    <button id="btnReset" class="btn" style="background:#0ea5e9;">↺ Reiniciar</button>
  </div>

  <div class="row">
    <label><b>Velocidad</b>:</label>
    <input id="speed" type="range" min="0.25" max="6" step="0.25" value="1.5">
    <span id="speedVal" class="small">1.5×</span>
  </div>

  <div class="small">
    Tip: Activa/desactiva capas desde el control (arriba derecha).
  </div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  // Datos embebidos (GeoJSON / rutas)
  const CLIENTES = __CLIENTES__;
  const CLAVE    = __CLAVE__;
  const CALLES   = __CALLES__;
  const RUTAS    = __RUTAS__;

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
        `Densidad: ${dens} hab/km²`
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

  // Rutas por camión (líneas)
  function polylineFromRuta(rutaLatLon, color) {
    if (!rutaLatLon || rutaLatLon.length < 2) return null;
    return L.polyline(rutaLatLon, { color, weight: 5, opacity: 0.9 });
  }

  const colores = { "1": "#2563eb", "2": "#ef4444", "3": "#a855f7" };
  const layerRutas = {};
  Object.keys(RUTAS).forEach(k => {
    const poly = polylineFromRuta(RUTAS[k], colores[k] || "#111827");
    if (poly) layerRutas[k] = poly;
  });

  // Control de capas
  const overlays = {
    "Clientes (puntos)": layerClientes,
    "Puntos clave": layerClave
  };
  if (CALLES.features && CALLES.features.length > 0) overlays["Calles (base)"] = layerCalles;

  Object.keys(layerRutas).forEach(k => {
    overlays[`Ruta Camión ${k}`] = layerRutas[k];
  });

  L.control.layers({ "OSM": osm }, overlays, { collapsed: false }).addTo(map);

  // Mostrar por defecto
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
  // Animación 🚚
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

  // Crear un camión por ruta
  const trucks = [];
  Object.keys(RUTAS).forEach(k => {
    const coords = RUTAS[k];
    if (!coords || coords.length < 2) return;

    const icon = L.divIcon({
      className: '',
      html: `<div class="truck-icon">🚚</div>`,
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
  });

  let running = false;
  let lastT = null;

  function getSpeedFactor() {
    return parseFloat(document.getElementById("speed").value || "1");
  }

  // velocidad base de animación (m/s)
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
  const speed = document.getElementById("speed");
  const speedVal = document.getElementById("speedVal");
  speed.addEventListener("input", () => {
    speedVal.textContent = `${speed.value}×`;
  });

  document.getElementById("btnPlay").addEventListener("click", () => {
    if (!running) {
      running = true;
      lastT = null;
      requestAnimationFrame(tick);
    }
  });

  document.getElementById("btnPause").addEventListener("click", () => {
    running = false;
  });

  document.getElementById("btnReset").addEventListener("click", () => {
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

html = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8" />
  <title>Rutas de Recoleccion</title>
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&display=swap');
    html, body { height: 100%; margin: 0; }
    body { font-family: 'IBM Plex Sans', sans-serif; background: #f3f0e8; }
    #map { width: 100%; height: 100%; }
    .control-panel {
      position: absolute;
      top: 12px; left: 12px;
      z-index: 9999;
      width: min(360px, calc(100vw - 24px));
      background: rgba(255,248,239,0.96);
      padding: 14px 16px;
      border-radius: 16px;
      box-shadow: 0 14px 28px rgba(32, 23, 12, 0.18);
      border: 1px solid rgba(129, 90, 43, 0.18);
    }
    .panel-title { font-size: 18px; font-weight: 700; color: #3f2d17; margin-bottom: 8px; }
    .panel-subtitle { font-size: 12px; color: #6b5a45; margin-bottom: 12px; }
    .row { display: flex; gap: 8px; align-items: center; margin: 8px 0; flex-wrap: wrap; }
    .row label { font-size: 13px; color: #47392a; }
    .btn {
      cursor: pointer;
      border: 0;
      padding: 8px 10px;
      border-radius: 12px;
      background: #3f2d17;
      color: white;
      font-weight: 600;
      font-family: inherit;
    }
    .btn:active { transform: translateY(1px); }
    .small { font-size: 12px; color: #5f5244; }
    .stats-grid {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
      margin: 12px 0;
    }
    .stat-card {
      background: #fffdf8;
      border-radius: 12px;
      padding: 10px;
      border: 1px solid rgba(129, 90, 43, 0.14);
    }
    .stat-label {
      font-size: 11px;
      color: #7c6c58;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }
    .stat-value {
      font-size: 18px;
      font-weight: 700;
      color: #2b241d;
      margin-top: 2px;
    }
    .legend { display: grid; gap: 6px; margin-top: 8px; }
    .legend-item { display: flex; align-items: center; gap: 8px; font-size: 12px; color: #48392b; }
    .legend-line { width: 22px; height: 5px; border-radius: 999px; }
    .quick-selector {
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 8px;
      margin-top: 10px;
    }
    .quick-actions {
      display: grid;
      grid-template-columns: 1fr;
      gap: 8px;
      margin-top: 10px;
    }
    .truck-chip {
      border: 1px solid rgba(129, 90, 43, 0.18);
      background: #fffdf8;
      color: #3f2d17;
      border-radius: 999px;
      padding: 8px 10px;
      font-size: 12px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s ease;
    }
    .truck-chip.active {
      color: white;
      border-color: transparent;
      box-shadow: 0 6px 16px rgba(31, 41, 55, 0.18);
    }
    .route-focus {
      margin-top: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: #fffdf8;
      border: 1px solid rgba(129, 90, 43, 0.12);
      font-size: 12px;
      color: #4b3c2c;
    }
    .status-bar {
      margin-top: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: #fffdf8;
      border: 1px solid rgba(129, 90, 43, 0.12);
      font-size: 12px;
      color: #4b3c2c;
    }
    .trip-list { margin-top: 10px; max-height: 220px; overflow: auto; padding-right: 4px; }
    .trip-item {
      padding: 8px 10px;
      margin-bottom: 6px;
      background: #fffdf8;
      border-radius: 10px;
      border: 1px solid rgba(129, 90, 43, 0.12);
      font-size: 12px;
      color: #44372a;
      cursor: pointer;
    }
    .trip-item.active {
      border-color: rgba(250, 204, 21, 0.85);
      box-shadow: 0 0 0 2px rgba(250, 204, 21, 0.20) inset;
    }
    .trip-item strong { color: #2d241c; }
    .truck-icon {
      font-size: 22px;
      line-height: 22px;
      filter: drop-shadow(0 2px 3px rgba(0,0,0,0.30));
    }
    .arrow-icon {
      color: #111827;
      font-size: 16px;
      font-weight: 700;
      text-shadow: 0 0 3px rgba(255,255,255,0.95);
      transform-origin: center center;
    }
    .sense-badge {
      background: rgba(17,24,39,0.92);
      color: #ffffff;
      border-radius: 999px;
      padding: 4px 8px;
      font-size: 11px;
      font-weight: 700;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.22);
      white-space: nowrap;
    }
    input[type="range"] { width: 170px; }
    .leaflet-popup-content { font-family: 'IBM Plex Sans', sans-serif; font-size: 12px; }
  </style>
</head>
<body>
<div id="map"></div>

<div class="control-panel">
  <div class="panel-title">Rutas de Recoleccion</div>
  <div class="panel-subtitle">Selecciona un camion para enfocar su recorrido.</div>
  <div class="row">
    <button id="btnPlay" class="btn">Reproducir</button>
    <button id="btnPause" class="btn" style="background:#7b6a58;">Pausa</button>
    <button id="btnReset" class="btn" style="background:#0f766e;">Reiniciar</button>
  </div>
  <div class="row">
    <label><b>Velocidad</b>:</label>
    <input id="speed" type="range" min="0.25" max="6" step="0.25" value="1.5">
    <span id="speedVal" class="small">1.5x</span>
  </div>
  <div class="stats-grid">
    <div class="stat-card"><div class="stat-label">Camiones</div><div id="statCamiones" class="stat-value">0</div></div>
    <div class="stat-card"><div class="stat-label">Tramos</div><div id="statTramos" class="stat-value">0</div></div>
    <div class="stat-card"><div class="stat-label">Distancia</div><div id="statKm" class="stat-value">0 km</div></div>
    <div class="stat-card"><div class="stat-label">Tiempo</div><div id="statHoras" class="stat-value">0 h</div></div>
  </div>
  <div class="small">Selecciona un camion para enfocarlo o usa mostrar todos para volver a la vista general.</div>
  <div class="quick-actions">
    <button id="btnShowAll" class="btn" style="background:#334155;">Mostrar todos</button>
  </div>
  <div class="quick-selector" id="quickSelector"></div>
  <div class="route-focus" id="routeFocus">
    Selecciona un camion para ver su ruta y sus viajes.
  </div>
  <div class="status-bar" id="statusBar">
    Animacion lista. Al seleccionar un camion, el mapa ocultara automaticamente los demas.
  </div>
  <div class="trip-list" id="tripList"></div>
</div>

<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
  const CLIENTES = __CLIENTES__;
  const CLAVE = __CLAVE__;
  const CALLES = __CALLES__;
  const RUTAS = __RUTAS__;
  const colores = { "1": "#2563eb", "2": "#ef4444", "3": "#a855f7" };
  const coloresCluster = ["#f97316", "#0ea5e9", "#84cc16", "#ef4444", "#8b5cf6", "#14b8a6", "#f59e0b", "#ec4899"];

  const map = L.map('map', { center: [__CENTRO_LAT__, __CENTRO_LON__], zoom: 14 });
  const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; OpenStreetMap'
  }).addTo(map);

  function styleClientes(feature) {
    const p = feature.properties || {};
    const d = (p.demanda_kg !== undefined && p.demanda_kg !== null) ? p.demanda_kg : 0;
    const cluster = (p.cluster_id !== undefined && p.cluster_id !== null) ? p.cluster_id : -1;
    const r = Math.max(2, Math.min(10, 2 + d / 200));
    const fill = cluster >= 0 ? coloresCluster[cluster % coloresCluster.length] : "#f97316";
    return { radius: r, color: "#111827", weight: 1, fillColor: fill, fillOpacity: 0.85 };
  }

  const layerClientes = L.geoJSON(CLIENTES, {
    pointToLayer: (f, latlng) => L.circleMarker(latlng, styleClientes(f)),
    onEachFeature: (f, layer) => {
      const p = f.properties || {};
      const dens = (p.densidad_pob_km2 !== undefined && p.densidad_pob_km2 !== null) ? p.densidad_pob_km2 : "-";
      const cluster = (p.cluster_id !== undefined && p.cluster_id !== null) ? p.cluster_id : "-";
      layer.bindPopup(
        `<b>Cliente</b><br>` +
        `Nodo: ${(p.id_nodo !== undefined && p.id_nodo !== null) ? p.id_nodo : "-"}<br>` +
        `Zona: ${cluster}<br>` +
        `Demanda: ${(p.demanda_kg !== undefined && p.demanda_kg !== null) ? p.demanda_kg : "-"} kg<br>` +
        `Densidad: ${dens} hab/km²`
      );
    }
  });

  const layerClave = L.geoJSON(CLAVE, {
    pointToLayer: (f, latlng) => {
      const tipo = (f.properties && f.properties.tipo) ? f.properties.tipo : "Punto";
      return L.marker(latlng).bindPopup(`<b>${tipo}</b>`);
    }
  });

  const layerCalles = L.geoJSON(CALLES, { style: { color: "#22c55e", weight: 2, opacity: 0.55 } });

  function tramoStyle(color, tramo) {
    const weight = tramo === "Recol" ? 6 : 4;
    const dashArray = tramo === "Fin" ? "8 8" : null;
    return { color, weight, opacity: 0.92, dashArray };
  }

  function formatHoursFromMinutes(minutes, decimals = 2) {
    return `${(minutes / 60.0).toFixed(decimals)} h`;
  }

  function hasValue(value) {
    return value !== null && value !== undefined && value !== "" && !Number.isNaN(value);
  }

  function pushIf(lines, label, value) {
    if (hasValue(value)) lines.push(`${label}: ${value}`);
  }

  function bearingDeg(a, b) {
    return Math.atan2(b[0] - a[0], b[1] - a[1]) * 180 / Math.PI;
  }

  function arrowMarker(latlng, angle, color) {
    const html = `<div class="arrow-icon" style="color:${color}; transform: rotate(${angle}deg);">▶</div>`;
    return L.marker(latlng, {
      icon: L.divIcon({ className: "", html, iconSize: [16, 16], iconAnchor: [8, 8] }),
      interactive: false
    });
  }

  function buildArrowGroup(coords, color) {
    const group = L.layerGroup();
    if (!coords || coords.length < 2) return group;
    const step = Math.max(2, Math.floor(coords.length / 5));
    for (let i = step; i < coords.length; i += step) {
      group.addLayer(arrowMarker(coords[i], bearingDeg(coords[i - 1], coords[i]), color));
    }
    return group;
  }

  function labelMarker(latlng, text, bgColor) {
    const html = `<div class="sense-badge" style="background:${bgColor};">${text}</div>`;
    return L.marker(latlng, {
      icon: L.divIcon({ className: "", html, iconSize: null, iconAnchor: [0, 0] }),
      interactive: false
    });
  }

  const layerRutas = {};
  const allPolys = [];
  const allTramos = [];
  const truckRouteCoords = {};
  let activeTruckId = null;
  let activeTripKey = null;
  const tripsByTruck = {};

  Object.keys(RUTAS).forEach(k => {
    const payload = RUTAS[k] || {};
    const tramos = payload.tramos || [];
    const color = colores[k] || "#111827";
    const group = L.layerGroup();

    tramos.forEach(tramo => {
      if (!tramo.coords || tramo.coords.length < 2) return;
      const poly = L.polyline(tramo.coords, tramoStyle(color, tramo.tramo));
      const popupLines = [`<b>Camion ${k} - Tramo ${tramo.tramo}</b>`];
      pushIf(popupLines, "Viaje", tramo.viaje);
      if (tramo.cluster >= 0) pushIf(popupLines, "Zona", tramo.cluster);
      if (tramo.sentido) pushIf(popupLines, "Recorrido", tramo.sentido);
      if (tramo.de && tramo.a) pushIf(popupLines, "Desde / Hacia", `${tramo.de} -> ${tramo.a}`);
      pushIf(popupLines, "Distancia", `${tramo.dist_km.toFixed(2)} km`);
      pushIf(popupLines, "Tiempo", formatHoursFromMinutes(tramo.dur_min));
      if ((tramo.paradas || 0) > 0) pushIf(popupLines, "Clientes atendidos", tramo.paradas);
      if ((tramo.carga_kg || 0) > 0) pushIf(popupLines, "Carga recolectada", `${tramo.carga_kg.toFixed(2)} kg`);
      if (tramo.calles) pushIf(popupLines, "Calles", tramo.calles);
      if ((tramo.oneway_pct || 0) > 0) pushIf(popupLines, "Calles unidireccionales", `${tramo.oneway_pct.toFixed(1)}%`);
      poly.bindPopup(popupLines.join("<br>"));
      poly.on("click", () => {
        selectTruck(String(k));
      });
      group.addLayer(poly);
      allPolys.push(poly);
      allTramos.push(Object.assign({ camion: k }, tramo));
      if (!truckRouteCoords[String(k)]) truckRouteCoords[String(k)] = [];
      truckRouteCoords[String(k)].push(tramo.coords);
      const viajeKey = String(tramo.viaje);
      if (!tripsByTruck[String(k)]) tripsByTruck[String(k)] = {};
      if (!tripsByTruck[String(k)][viajeKey]) {
        tripsByTruck[String(k)][viajeKey] = {
          viaje: viajeKey,
          camion: String(k),
          cluster: tramo.cluster,
          dist_km: 0,
          dur_min: 0,
          paradas: 0,
          carga_kg: 0,
          coords: []
        };
      }
      const trip = tripsByTruck[String(k)][viajeKey];
      trip.dist_km += tramo.dist_km || 0;
      trip.dur_min += tramo.dur_min || 0;
      trip.paradas = Math.max(trip.paradas, tramo.paradas || 0);
      trip.carga_kg = Math.max(trip.carga_kg || 0, tramo.carga_kg || 0);
      if (tramo.cluster >= 0) trip.cluster = tramo.cluster;
      if (tramo.coords && tramo.coords.length >= 2) trip.coords.push(tramo.coords);
    });

    layerRutas[k] = group;
  });

  const overlays = { "Clientes (puntos)": layerClientes, "Puntos clave": layerClave };
  if (CALLES.features && CALLES.features.length > 0) overlays["Calles (base)"] = layerCalles;
  L.control.layers({ "OSM": osm }, overlays, { collapsed: false }).addTo(map);

  layerClave.addTo(map);
  layerClientes.addTo(map);
  Object.keys(layerRutas).forEach(k => {
    layerRutas[k].addTo(map);
  });

  if (allPolys.length > 0) {
    const group = L.featureGroup(allPolys);
    map.fitBounds(group.getBounds().pad(0.08));
  }

  function setStats() {
    const resumenes = Object.values(RUTAS).map(v => v.resumen || {});
    const totalKm = resumenes.reduce((acc, r) => acc + (r.dist_km || 0), 0);
    const totalMin = resumenes.reduce((acc, r) => acc + (r.dur_min || 0), 0);
    const totalTramos = resumenes.reduce((acc, r) => acc + (r.n_tramos || 0), 0);
    document.getElementById("statCamiones").textContent = resumenes.length;
    document.getElementById("statTramos").textContent = totalTramos;
    document.getElementById("statKm").textContent = `${totalKm.toFixed(1)} km`;
    document.getElementById("statHoras").textContent = formatHoursFromMinutes(totalMin, 1);
  }

  function renderStepList() {
    const el = document.getElementById("stepList");
    const top = allTramos.slice().sort((a, b) => (b.dist_km || 0) - (a.dist_km || 0)).slice(0, 8);
    el.innerHTML = top.map(t => `
      <div class="step-item" data-truck-id="${t.camion}" style="cursor:pointer;">
        <strong>Camion ${t.camion}</strong> · ${t.tramo}<br>
        ${t.sentido}<br>
        ${t.dist_km.toFixed(2)} km · ${formatHoursFromMinutes(t.dur_min)}<br>
        <span class="small">${t.calles || "Sin detalle de calles"}</span>
      </div>
    `).join("");
    el.querySelectorAll("[data-truck-id]").forEach(node => {
      node.addEventListener("click", () => highlightTruck(node.getAttribute("data-truck-id")));
    });
  }

  function updateStatusBar(msg) {
    const el = document.getElementById("statusBar");
    if (el) el.textContent = msg;
  }

  function updateRouteFocus(msg) {
    const el = document.getElementById("routeFocus");
    if (el) el.innerHTML = msg;
  }

  function renderQuickSelector() {
    const el = document.getElementById("quickSelector");
    const ids = Object.keys(RUTAS).sort((a, b) => Number(a) - Number(b));
    el.innerHTML = ids.map(id => `
      <button class="truck-chip" data-truck-id="${id}" style="background:#fffdf8;">
        Camion ${id}
      </button>
    `).join("");
    el.querySelectorAll("[data-truck-id]").forEach(node => {
      const id = node.getAttribute("data-truck-id");
      node.style.borderColor = colores[id] || "#3f2d17";
      node.addEventListener("click", () => {
        selectTruck(id);
      });
    });
  }

  function refreshQuickSelector() {
    document.querySelectorAll(".truck-chip").forEach(node => {
      const id = node.getAttribute("data-truck-id");
      const visible = visibleRouteIds.has(id);
      const selected = activeTruckId === id;
      node.classList.toggle("active", selected);
      node.style.background = selected ? (colores[id] || "#3f2d17") : "#fffdf8";
      node.style.color = selected ? "white" : "#3f2d17";
      node.style.opacity = visible ? "1" : "0.45";
    });
  }

  function renderTripList(truckId) {
    const el = document.getElementById("tripList");
    const trips = truckId && tripsByTruck[truckId]
      ? Object.values(tripsByTruck[truckId]).sort((a, b) => {
          const va = a.viaje === "FIN" ? Number.POSITIVE_INFINITY : Number(a.viaje);
          const vb = b.viaje === "FIN" ? Number.POSITIVE_INFINITY : Number(b.viaje);
          return va - vb;
        })
      : [];

    if (!truckId || trips.length === 0) {
      el.innerHTML = `<div class="trip-item">Selecciona un camion para navegar visualmente viaje por viaje.</div>`;
      return;
    }

    el.innerHTML = trips.map(t => {
      const summary = [`${t.dist_km.toFixed(2)} km`, formatHoursFromMinutes(t.dur_min)];
      if ((t.paradas || 0) > 0) summary.push(`${t.paradas} clientes`);
      if ((t.carga_kg || 0) > 0) summary.push(`${t.carga_kg.toFixed(2)} kg`);
      const zoneLine = t.cluster >= 0 ? ` · Zona ${t.cluster}` : "";
      return `
      <div class="trip-item ${activeTripKey === `${truckId}:${t.viaje}` ? "active" : ""}" data-trip-key="${truckId}:${t.viaje}">
        <strong>Viaje ${t.viaje}</strong>${zoneLine}<br>
        ${summary.join(" · ")}
      </div>
    `;
    }).join("");

    el.querySelectorAll("[data-trip-key]").forEach(node => {
      node.addEventListener("click", () => {
        const key = node.getAttribute("data-trip-key");
        const [camionId, viajeId] = key.split(":");
        highlightTrip(camionId, viajeId);
      });
    });
  }

  setStats();
  renderTripList(null);
  renderQuickSelector();

  function haversineMeters(a, b) {
    const R = 6371000;
    const toRad = x => x * Math.PI / 180;
    const dLat = toRad(b[0] - a[0]);
    const dLon = toRad(b[1] - a[1]);
    const lat1 = toRad(a[0]);
    const lat2 = toRad(b[0]);
    const s1 = Math.sin(dLat / 2), s2 = Math.sin(dLon / 2);
    const h = s1 * s1 + Math.cos(lat1) * Math.cos(lat2) * s2 * s2;
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  }

  function buildCumulativeDistances(coords) {
    const cum = [0];
    for (let i = 1; i < coords.length; i++) {
      cum.push(cum[i - 1] + haversineMeters(coords[i - 1], coords[i]));
    }
    return cum;
  }

  function interpolateAlong(coords, cumDist, dist) {
    if (coords.length < 2) return coords[0] || null;
    const total = cumDist[cumDist.length - 1];
    if (dist <= 0) return coords[0];
    if (dist >= total) return coords[coords.length - 1];
    let i = 1;
    while (i < cumDist.length && cumDist[i] < dist) i++;
    const d0 = cumDist[i - 1], d1 = cumDist[i];
    const t = (dist - d0) / (d1 - d0 + 1e-9);
    const a = coords[i - 1], b = coords[i];
    return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  }

  const trucks = [];
  const truckById = {};
  const visibleRouteIds = new Set(Object.keys(RUTAS));
  const highlightLayer = L.layerGroup().addTo(map);
  const directionLayer = L.layerGroup().addTo(map);
  Object.keys(RUTAS).forEach(k => {
    const coords = (RUTAS[k] && RUTAS[k].coords) ? RUTAS[k].coords : [];
    if (!coords || coords.length < 2) return;
    const icon = L.divIcon({
      className: '',
      html: `<div class="truck-icon">🚚</div>`,
      iconSize: [24, 24],
      iconAnchor: [12, 12]
    });
    const marker = L.marker(coords[0], { icon }).addTo(map);
    marker.on("click", () => selectTruck(String(k)));
    const truck = { id: String(k), coords, cum: buildCumulativeDistances(coords), dist: 0, marker };
    trucks.push(truck);
    truckById[String(k)] = truck;
  });

  const tripHighlightLayer = L.layerGroup().addTo(map);

  function setTruckVisibility(truckId, visible) {
    const routeLayer = layerRutas[truckId];
    if (!routeLayer) return;
    if (visible) {
      visibleRouteIds.add(String(truckId));
      if (!map.hasLayer(routeLayer)) map.addLayer(routeLayer);
    } else {
      visibleRouteIds.delete(String(truckId));
      if (map.hasLayer(routeLayer)) map.removeLayer(routeLayer);
    }
    syncTruckVisibility();
  }

  function drawDirectionForTramos(tramos, color) {
    directionLayer.clearLayers();
  }

  function selectTruck(truckId) {
    const id = String(truckId);
    Object.keys(RUTAS).forEach(k => setTruckVisibility(k, String(k) === id));
    highlightTruck(id);
    updateStatusBar(`Mostrando solo Camion ${id}. Usa 'Mostrar todos' para volver a ver toda la flota.`);
  }

  function highlightTruck(truckId) {
    activeTruckId = String(truckId);
    activeTripKey = null;
    highlightLayer.clearLayers();
    tripHighlightLayer.clearLayers();
    directionLayer.clearLayers();
    const segmentos = truckRouteCoords[activeTruckId] || [];
    segmentos.forEach(coords => {
      if (coords && coords.length >= 2) {
        L.polyline(coords, {
          color: "#facc15",
          weight: 10,
          opacity: 0.40,
          lineCap: "round",
          lineJoin: "round"
        }).addTo(highlightLayer);
      }
    });
    const tramosActivos = allTramos.filter(t => String(t.camion) === activeTruckId);
    drawDirectionForTramos(tramosActivos, colores[activeTruckId] || "#111827");
    const resumen = (RUTAS[activeTruckId] && RUTAS[activeTruckId].resumen) ? RUTAS[activeTruckId].resumen : null;
    if (resumen) {
      updateRouteFocus(
        `<b>Camion ${activeTruckId} seleccionado</b><br>` +
        `Distancia total: ${resumen.dist_km.toFixed(1)} km<br>` +
        `Tiempo total: ${formatHoursFromMinutes(resumen.dur_min, 2)}<br>` +
        `Tramos: ${resumen.n_tramos}`
      );
    }
    refreshQuickSelector();
    renderTripList(activeTruckId);
  }

  function highlightTrip(truckId, viajeId) {
    selectTruck(truckId);
    activeTripKey = `${truckId}:${viajeId}`;
    tripHighlightLayer.clearLayers();
    directionLayer.clearLayers();
    const trip = tripsByTruck[String(truckId)] ? tripsByTruck[String(truckId)][String(viajeId)] : null;
    if (!trip) return;
    const tripTramos = allTramos.filter(t => String(t.camion) === String(truckId) && String(t.viaje) === String(viajeId));
    (trip.coords || []).forEach(coords => {
      if (coords && coords.length >= 2) {
        L.polyline(coords, {
          color: "#0f172a",
          weight: 7,
          opacity: 0.9,
          lineCap: "round",
          lineJoin: "round"
        }).addTo(tripHighlightLayer);
      }
    });
    drawDirectionForTramos(tripTramos, colores[String(truckId)] || "#111827");
    const tripFocus = [`<b>Camion ${truckId} · Viaje ${viajeId}</b>`];
    if (trip.cluster >= 0) tripFocus.push(`Zona: ${trip.cluster}`);
    tripFocus.push(`Distancia: ${trip.dist_km.toFixed(2)} km`);
    tripFocus.push(`Tiempo: ${formatHoursFromMinutes(trip.dur_min, 2)}`);
    if ((trip.paradas || 0) > 0) tripFocus.push(`Clientes atendidos: ${trip.paradas}`);
    if ((trip.carga_kg || 0) > 0) tripFocus.push(`Carga recolectada: ${trip.carga_kg.toFixed(2)} kg`);
    updateRouteFocus(tripFocus.join("<br>"));
    renderTripList(String(truckId));
  }

  function syncTruckVisibility() {
    trucks.forEach(t => {
      const visible = visibleRouteIds.has(String(t.id));
      if (visible) {
        if (!map.hasLayer(t.marker)) t.marker.addTo(map);
      } else if (map.hasLayer(t.marker)) {
        map.removeLayer(t.marker);
      }
    });
    const visibles = Array.from(visibleRouteIds).sort((a, b) => Number(a) - Number(b));
    updateStatusBar(
      visibles.length > 0
        ? `Camiones visibles en animacion: ${visibles.join(", ")}`
        : "No hay rutas visibles. Activa al menos una ruta para reproducir."
    );
    if (activeTruckId && !visibleRouteIds.has(activeTruckId)) {
      activeTruckId = null;
      activeTripKey = null;
      highlightLayer.clearLayers();
      tripHighlightLayer.clearLayers();
      directionLayer.clearLayers();
      updateRouteFocus("Selecciona un camion para ver solo su ruta y explorar sus viajes.");
      renderTripList(null);
    }
    refreshQuickSelector();
  }

  syncTruckVisibility();

  document.getElementById("btnShowAll").addEventListener("click", () => {
    Object.keys(RUTAS).forEach(k => setTruckVisibility(k, true));
    activeTruckId = null;
    activeTripKey = null;
    highlightLayer.clearLayers();
    tripHighlightLayer.clearLayers();
    directionLayer.clearLayers();
    updateRouteFocus("Vista general activa. Selecciona un camion para enfocarlo.");
    renderTripList(null);
    refreshQuickSelector();
    updateStatusBar("Mostrando todos los camiones.");
  });

  let running = false;
  let lastT = null;
  const BASE_MPS = 40.0;

  function getSpeedFactor() {
    return parseFloat(document.getElementById("speed").value || "1");
  }

  function tick(ts) {
    if (!running) return;
    if (!lastT) lastT = ts;
    const dt = (ts - lastT) / 1000.0;
    lastT = ts;
    const step = BASE_MPS * getSpeedFactor() * dt;
    trucks.forEach(t => {
      if (!visibleRouteIds.has(String(t.id))) return;
      t.dist += step;
      const total = t.cum[t.cum.length - 1];
      if (t.dist > total) t.dist = total;
      const pos = interpolateAlong(t.coords, t.cum, t.dist);
      if (pos) t.marker.setLatLng(pos);
    });
    requestAnimationFrame(tick);
  }

  const speed = document.getElementById("speed");
  const speedVal = document.getElementById("speedVal");
  speed.addEventListener("input", () => {
    speedVal.textContent = `${speed.value}x`;
  });

  document.getElementById("btnPlay").addEventListener("click", () => {
    if (visibleRouteIds.size === 0) {
      updateStatusBar("No hay rutas visibles. Usa 'Mostrar todos' o selecciona un camion para reproducir.");
      return;
    }
    if (!running) {
      running = true;
      lastT = null;
      syncTruckVisibility();
      updateStatusBar(`Reproduciendo camiones visibles: ${Array.from(visibleRouteIds).sort((a, b) => Number(a) - Number(b)).join(", ")}`);
      requestAnimationFrame(tick);
    }
  });
  document.getElementById("btnPause").addEventListener("click", () => {
    running = false;
    updateStatusBar("Animacion en pausa.");
  });
  document.getElementById("btnReset").addEventListener("click", () => {
    running = false;
    lastT = null;
    trucks.forEach(t => {
      t.dist = 0;
      t.marker.setLatLng(t.coords[0]);
    });
    syncTruckVisibility();
    updateStatusBar("Animacion reiniciada.");
  });
</script>
</body>
</html>
"""

# Inyectar datos en el template
html = html.replace("__CLIENTES__", json.dumps(clientes_geojson))
html = html.replace("__CLAVE__", json.dumps(clave_geojson))
html = html.replace("__CALLES__", json.dumps(calles_geojson))
html = html.replace("__RUTAS__", json.dumps(rutas_camiones))
html = html.replace("__CENTRO_LAT__", str(centro_lat))
html = html.replace("__CENTRO_LON__", str(centro_lon))

with open(OUT_HTML, "w", encoding="utf-8") as f:
    f.write(html)

print(f"✅ HTML generado: {OUT_HTML}")
print("   Ábrelo en tu navegador (doble click).")

# CELDA KPI (SOLO COLAB): Estadísticas + KPIs (por viaje / por camión / global) mostrando tablas
import pandas as pd
import numpy as np

CAPACIDAD_MAXIMA_KG = float(globals().get("CAPACIDAD_MAXIMA_KG", 9000.0))
HORAS_TRABAJO = 8.0  # horas

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

print("📊 Generando KPIs para ejecución local...")

# =========================================================
# 0) Dataframe por NODO (basura + densidad si existe CELDA 7)
# =========================================================
df_nodos = pd.DataFrame({
    "id_nodo": [int(n) for n in nodos_clientes],
    "cluster_id": [int(mapa_clusteres.get(int(n), -1)) for n in nodos_clientes],
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
        t_desc  = safe_float(costos.get("descarga_s", np.nan))
        t_total = np.nansum([t_aprox, t_int, t_desc])

        d_aprox = safe_float(dist.get("aprox_m", np.nan))
        d_recol = safe_float(dist.get("recoleccion_m", np.nan))
        d_descm = safe_float(dist.get("descarga_m", np.nan))
        d_total = np.nansum([d_aprox, d_recol, d_descm])

        filas_viajes.append({
            "camion": c_id,
            "viaje": v_idx,
            "origen": origen,
            "paradas": len(nodos),
            "carga_kg": carga,

            "t_aprox_min": t_aprox/60 if np.isfinite(t_aprox) else np.nan,
            "t_recol_min": t_int/60   if np.isfinite(t_int)   else np.nan,
            "t_desc_min":  t_desc/60  if np.isfinite(t_desc)  else np.nan,
            "t_total_min": t_total/60 if np.isfinite(t_total) else np.nan,

            "d_aprox_km": d_aprox/1000 if np.isfinite(d_aprox) else np.nan,
            "d_recol_km": d_recol/1000 if np.isfinite(d_recol) else np.nan,
            "d_desc_km":  d_descm/1000 if np.isfinite(d_descm) else np.nan,
            "d_total_km": d_total/1000 if np.isfinite(d_total) else np.nan,

            "kg_por_km": (carga / (d_total/1000)) if (np.isfinite(d_total) and d_total > 0) else np.nan,
            "kg_por_h":  (carga / (t_total/3600)) if (np.isfinite(t_total) and t_total > 0) else np.nan,

            "util_carga_pct": (100*carga/CAPACIDAD_MAXIMA_KG) if CAPACIDAD_MAXIMA_KG > 0 else np.nan
        })

df_viajes = pd.DataFrame(filas_viajes)

# =========================================================
# 2) KPIs por CAMIÓN
# =========================================================
df_camiones = pd.DataFrame([{
    "camion": c.get("id", None),
    "viajes_asignados": len(c.get("viajes", [])),
    "tiempo_turno_h": safe_float(c.get("tiempo_total_h", np.nan)),
    "tiempo_turno_min": safe_float(c.get("tiempo_total_s", np.nan))/60 if np.isfinite(safe_float(c.get("tiempo_total_s", np.nan))) else np.nan,
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

df_camiones["uso_jornada_pct"] = 100 * (df_camiones["tiempo_turno_h"] / HORAS_TRABAJO)
df_camiones["holgura_min"] = (HORAS_TRABAJO - df_camiones["tiempo_turno_h"]) * 60

# =========================================================
# 3) KPIs GLOBALES
# =========================================================
n_camiones = len(camiones)
n_viajes = len(df_viajes)
carga_total_asignada = float(df_viajes["carga_kg"].sum()) if n_viajes > 0 else 0.0
dist_total_km = float(df_viajes["d_total_km"].sum()) if n_viajes > 0 else np.nan
tiempo_total_h_turnos = float(df_camiones["tiempo_turno_h"].sum()) if len(df_camiones) > 0 else np.nan

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
print("✅ KPI GLOBAL")
print("======================")
print(f"Camiones usados: {n_camiones}")
print(f"Viajes asignados: {n_viajes}")
print(f"Nodos clientes: {len(nodos_clientes)}")
print(f"Demanda total (kg): {total_demanda:,.2f}")
print(f"Carga total asignada (kg): {carga_total_asignada:,.2f}")
print(f"Error carga vs demanda: {error_kg:,.2f} kg  ({error_rel_pct:.3f}%)")
print(f"Distancia total (km): {dist_total_km:,.2f}" if np.isfinite(dist_total_km) else "Distancia total: N/A")
print(f"Tiempo total sumado de turnos (h): {tiempo_total_h_turnos:,.2f}" if np.isfinite(tiempo_total_h_turnos) else "Tiempo total: N/A")
print(f"Gini de basura: {gini_demanda:.3f}")
if hay_densidad:
    print(f"Correlación basura vs densidad poblacional: {corr_dens_dem:.3f}")
else:
    print("Densidad poblacional: no detectada (gdf_pts no está o no tiene densidad_pob_km2).")

print("\n======================")
print("🚛 KPI POR CAMIÓN")
print("======================")
df_camiones_out = df_camiones.sort_values("camion").round(2)
print(df_camiones_out.to_string(index=False))

print("\n======================")
print("🧾 KPI POR VIAJE (top 20 más largos por tiempo)")
print("======================")
if len(df_viajes) > 0:
    df_viajes_out = df_viajes.sort_values("t_total_min", ascending=False).head(20).round(2)
    print(df_viajes_out.to_string(index=False))
else:
    print("No hay viajes en df_viajes.")
    df_viajes_out = df_viajes.copy()

print("\n======================")
print("🔥 Hotspots por basura (top 15 nodos)")
print("======================")
df_hotspots_basura = df_nodos.sort_values("demanda_kg", ascending=False).head(15).round(2)
print(df_hotspots_basura.to_string(index=False))

if hay_densidad:
    print("\n======================")
    print("🏙️ Hotspots por densidad poblacional (top 15 nodos)")
    print("======================")
    df_hotspots_densidad = df_nodos.sort_values("densidad_pob_km2", ascending=False).head(15).round(2)
    print(df_hotspots_densidad.to_string(index=False))
else:
    df_hotspots_densidad = pd.DataFrame()

KPI_CAMIONES_CSV = "kpi_camiones.csv"
KPI_VIAJES_CSV = "kpi_viajes.csv"
KPI_NODOS_CSV = "kpi_nodos.csv"

df_camiones_out.to_csv(KPI_CAMIONES_CSV, index=False, encoding="utf-8-sig")
df_viajes.to_csv(KPI_VIAJES_CSV, index=False, encoding="utf-8-sig")
df_nodos.to_csv(KPI_NODOS_CSV, index=False, encoding="utf-8-sig")

print("\n✅ KPIs exportados:")
print(f"  - {KPI_CAMIONES_CSV}")
print(f"  - {KPI_VIAJES_CSV}")
print(f"  - {KPI_NODOS_CSV}")
print(f"ℹ️ Visualización lista en local: abre {OUT_HTML} en tu navegador.")
