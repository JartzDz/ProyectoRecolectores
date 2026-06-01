# ============================================================
# CELDA 1: Importaciones y Carga del Grafo
# ============================================================
import osmnx as ox
from pyproj import Transformer
import networkx as nx
import pandas as pd
import numpy as np
from shapely.geometry import Point, LineString, MultiPoint
import geopandas as gpd
import random, copy, time, warnings
from collections import deque, defaultdict, Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading, json, zipfile, glob
warnings.filterwarnings('ignore')

N_WORKERS = min(4, __import__('os').cpu_count() or 4)

print("=" * 70)
print("  V8_PIPELINE â€” CompactaciÃ³n + C&WÃ—3 + GenÃ©tico + TabÃº [PARALELO]")
print(f"  Workers: {N_WORKERS}")
print("=" * 70)

try:
    G = ox.load_graphml("grafo_actualizado.graphml")
    print(f"  Grafo: {G.number_of_nodes()} nodos, {G.number_of_edges()} aristas")
except Exception as e:
    print(f"  ERROR: grafo_limpio.graphml no encontrado\n{e}")
    raise

# --- ReproyecciÃ³n a UTM y recÃ¡lculo de 'length' ---
G = ox.project_graph(G, to_crs='epsg:32717')
print("  Grafo reproyectado a EPSG:32717 (metros)")

n_con_geom = 0
n_sin_geom = 0
n_paralelas = 0
keys_vistos = set()

for u, v, key, data in G.edges(keys=True, data=True):

    # Detectar aristas paralelas
    par = (u, v)
    if par in keys_vistos:
        n_paralelas += 1
    keys_vistos.add(par)

    # Longitud
    if 'geometry' in data and data['geometry'] is not None:
        data['length'] = data['geometry'].length
        n_con_geom += 1
    else:
        x1, y1 = G.nodes[u]['x'], G.nodes[u]['y']
        x2, y2 = G.nodes[v]['x'], G.nodes[v]['y']
        data['length'] = ((x2-x1)**2 + (y2-y1)**2) ** 0.5
        n_sin_geom += 1

    # Velocidad y tiempo de viaje
    tipo = data.get('highway', '')
    if isinstance(tipo, list): tipo = tipo[0]
    vel = 50 if tipo in ['primary', 'secondary', 'trunk'] else 30
    data['speed_kph'] = vel
    data['travel_time'] = (data['length'] / 1000 / vel) * 3600

print(f"  Aristas con geometrÃ­a real : {n_con_geom}")
print(f"  Aristas con fallback euclidiano: {n_sin_geom}")
print(f"  Aristas paralelas detectadas   : {n_paralelas}")

# VerificaciÃ³n: muestrear 3 aristas y confirmar que tienen los 3 atributos
print("\n  Muestra de 3 aristas (verificaciÃ³n):")
for i, (u, v, key, data) in enumerate(G.edges(keys=True, data=True)):
    if i >= 3: break
    print(f"    ({u}â†’{v} key={key}) "
          f"length={data.get('length'):.2f}m  "
          f"speed={data.get('speed_kph')}km/h  "
          f"travel_time={data.get('travel_time'):.2f}s")

print("  Longitudes de aristas recalculadas en metros reales")

nodos_clientes = []; dict_demandas = {}
id_estacion = id_relleno = None
n_demanda_cero = 0; n_demanda_error = 0
lista_estaciones = []; lista_rellenos = []

for nodo, data in G.nodes(data=True):
    t = data.get('tipo_nodo', '')
    if t == 'cliente':
        nodos_clientes.append(nodo)
        raw = data.get('demanda_kg', None)
        try:
            valor = float(raw)
            dict_demandas[nodo] = valor
            if valor == 0.0:
                n_demanda_cero += 1
        except (TypeError, ValueError):
            dict_demandas[nodo] = 0.0
            n_demanda_error += 1
    elif t == 'estacion':
        lista_estaciones.append(nodo)
        id_estacion = nodo
    elif t == 'relleno':
        lista_rellenos.append(nodo)
        id_relleno = nodo

if len(lista_estaciones) == 0:
    print("  AVISO: ningÃºn nodo tiene tipo_nodo='estacion' â€” se usarÃ¡ fallback")
elif len(lista_estaciones) > 1:
    print(f"  ADVERTENCIA: {len(lista_estaciones)} nodos marcados como estaciÃ³n: {lista_estaciones}")
    print(f"  Se usarÃ¡ el Ãºltimo encontrado: {id_estacion}")
else:
    print(f"  EstaciÃ³n encontrada : nodo {id_estacion}")

if len(lista_rellenos) == 0:
    print("  AVISO: ningÃºn nodo tiene tipo_nodo='relleno' â€” se usarÃ¡ fallback")
elif len(lista_rellenos) > 1:
    print(f"  ADVERTENCIA: {len(lista_rellenos)} nodos marcados como relleno: {lista_rellenos}")
    print(f"  Se usarÃ¡ el Ãºltimo encontrado: {id_relleno}")
else:
    print(f"  Relleno sanitario encontrado: nodo {id_relleno}")

print(f"  Clientes con demanda_kg = 0  : {n_demanda_cero}")
print(f"  Clientes con demanda_kg invÃ¡lida (forzada a 0): {n_demanda_error}")
print(f"  Clientes con demanda vÃ¡lida  : {len(nodos_clientes) - n_demanda_cero - n_demanda_error}")
print(f"  Demanda total inicial (antes de Celda 2): {sum(dict_demandas.values()):.2f} kg")

if id_estacion is None:
    lon_est, lat_est = -78.9814250, -2.8758464
    id_estacion = ox.distance.nearest_nodes(G, lon_est, lat_est)
    print(f"  AVISO: estaciÃ³n no encontrada en grafo â€” usando fallback coordenadas")
    print(f"  Fallback estaciÃ³n â†’ nodo {id_estacion} (lon={lon_est}, lat={lat_est})")
else:
    print(f"  EstaciÃ³n confirmada por tipo_nodo: nodo {id_estacion}")

if id_relleno is None:
    lon_rel, lat_rel = -78.930210, -2.965480
    id_relleno = ox.distance.nearest_nodes(G, lon_rel, lat_rel)
    print(f"  AVISO: relleno no encontrado en grafo â€” usando fallback coordenadas")
    print(f"  Fallback relleno â†’ nodo {id_relleno} (lon={lon_rel}, lat={lat_rel})")
else:
    print(f"  Relleno confirmado por tipo_nodo: nodo {id_relleno}")
TOTAL_ARISTAS_GRAFO = G.number_of_edges()
print(f"  Clientes originales: {len(nodos_clientes)}")

print("Verificando accesibilidad de clientes en grafo dirigido...")
inalcanzables = []
razon_exclusion = {}

for c in nodos_clientes:
    motivos = []
    try:
        nx.shortest_path_length(G, id_relleno, c, weight='length')
    except nx.NetworkXNoPath:
        motivos.append("rellenoâ†’cliente sin ruta")
    except nx.NodeNotFound:
        motivos.append("nodo no existe en grafo")

    try:
        nx.shortest_path_length(G, c, id_relleno, weight='length')
    except nx.NetworkXNoPath:
        motivos.append("clienteâ†’relleno sin ruta")
    except nx.NodeNotFound:
        motivos.append("nodo no existe en grafo")

    try:
        nx.shortest_path_length(G, id_estacion, c, weight='length')
    except nx.NetworkXNoPath:
        motivos.append("estacionâ†’cliente sin ruta")
    except nx.NodeNotFound:
        motivos.append("nodo no existe en grafo")

    try:
        nx.shortest_path_length(G, c, id_estacion, weight='length')
    except nx.NetworkXNoPath:
        motivos.append("clienteâ†’estacion sin ruta")
    except nx.NodeNotFound:
        motivos.append("nodo no existe en grafo")

    if motivos:
        inalcanzables.append(c)
        razon_exclusion[c] = motivos

if inalcanzables:
    print(f"  ATENCIÃ“N: {len(inalcanzables)} clientes inalcanzables. SerÃ¡n excluidos.")
    print(f"  Desglose de motivos:")
    conteo_motivos = defaultdict(int)
    for motivos in razon_exclusion.values():
        for m in motivos:
            conteo_motivos[m] += 1
    for motivo, cnt in sorted(conteo_motivos.items(), key=lambda x: -x[1]):
        print(f"    {cnt:4d} clientes â€” {motivo}")
    nodos_clientes = [c for c in nodos_clientes if c not in inalcanzables]
    dict_demandas = {c: v for c, v in dict_demandas.items() if c not in inalcanzables}
else:
    print(f"  Todos los {len(nodos_clientes)} clientes son alcanzables desde estaciÃ³n y relleno")

print(f"  Clientes operativos tras filtro: {len(nodos_clientes)}")

# ============================================================
# COMPACTACIÃ“N OPERATIVA
# ============================================================
def identificar_callejones(G, clientes, depositos, vertederos):
    no_fijos = set(depositos) | set(vertederos)
    padre_directo = {}
    for c in clientes:
        if c in no_fijos: continue
        pred = set(G.predecessors(c)); suc = set(G.successors(c))
        if len(pred)==1 and len(suc)==1 and pred==suc: padre_directo[c] = next(iter(pred))
        elif len(pred)==0 and len(suc)==1:             padre_directo[c] = next(iter(suc))
        elif len(pred)==1 and len(suc)==0:             padre_directo[c] = next(iter(pred))
    mapa_final = {}
    for hoja in padre_directo:
        actual = padre_directo[hoja]; visitados = {hoja}
        while actual in padre_directo and actual not in visitados:
            visitados.add(actual); actual = padre_directo[actual]
        mapa_final[hoja] = actual
    return mapa_final

def _nombres_calles_oneway(G, nodo):
    nombres_oneway = set()
    nombres_doble = set()

    for _, _, data in list(G.edges(nodo, data=True)) + list(G.in_edges(nodo, data=True)):
        oneway = data.get("oneway", False)
        if isinstance(oneway, str):
            oneway = oneway.lower() in ("true", "yes", "1")
        else:
            oneway = bool(oneway)

        name = data.get("name")
        if name is None:
            continue
        names_set = set(str(x) for x in name) if isinstance(name, list) else {str(name)}

        if oneway:
            nombres_oneway.update(names_set)
        else:
            nombres_doble.update(names_set)

    return nombres_oneway | nombres_doble

def identificar_lados_calle(G, clientes, matriz, umbral_metros=80, excluir=None):
    excluir = set(excluir or [])
    cli_set = [c for c in clientes if c not in excluir]

    cli_a_calles = {c: (_nombres_calles_oneway(G, c) if c in G.nodes else set())
                    for c in cli_set}

    # DiagnÃ³stico: cuÃ¡ntos nodos tienen al menos un nombre de calle
    n_con_nombre = sum(1 for nombres in cli_a_calles.values() if nombres)
    n_sin_nombre = len(cli_set) - n_con_nombre
    print(f"    Nodos con nombre de calle identificado: {n_con_nombre}")
    print(f"    Nodos sin nombre de calle             : {n_sin_nombre}")

    calle_a_cli = defaultdict(list)
    for c, nombres in cli_a_calles.items():
        for n in nombres:
            calle_a_cli[n].append(c)

    print(f"    Calles Ãºnicas encontradas             : {len(calle_a_cli)}")
    print(f"    Calles con mÃ¡s de un cliente          : {sum(1 for m in calle_a_cli.values() if len(m) > 1)}")

    parent = {c: c for c in cli_set}
    def find(x):
        while parent[x] != x: parent[x] = parent[parent[x]]; x = parent[x]
        return x
    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            if ra < rb: parent[rb] = ra
            else:       parent[ra] = rb

    for _, miembros in calle_a_cli.items():
        if len(miembros) < 2: continue
        for i, a in enumerate(miembros):
            for b in miembros[i+1:]:
                if (matriz.get_distance(a,b) <= umbral_metros and
                        matriz.get_distance(b,a) <= umbral_metros):
                    union(a, b)

    resultado = {c: find(c) for c in cli_set if find(c) != c}
    print(f"    Compactaciones laterales generadas    : {len(resultado)}")
    return resultado

def compactar_clientes_operativos(G, nodos_clientes, dict_demandas, matriz,
                                   depositos, vertederos,
                                   umbral_lados_metros=80, verbose=True):
    clientes_orig = list(nodos_clientes)
    callejones = identificar_callejones(G, clientes_orig, depositos, vertederos)
    if verbose: print(f"  Callejones detectados: {len(callejones)}")
    lados = identificar_lados_calle(G, clientes_orig, matriz,
                                     umbral_metros=umbral_lados_metros,
                                     excluir=set(callejones.keys()))
    if verbose: print(f"  Compactaciones laterales: {len(lados)}")
    mapa_c2p = {}
    for c in clientes_orig:
        if c in callejones:
            dest = callejones[c]
            while dest in callejones: dest = callejones[dest]
            while dest in lados:     dest = lados[dest]
        elif c in lados:
            dest = lados[c]
            while dest in callejones: dest = callejones[dest]
            while dest in lados:     dest = lados[dest]
        else:
            dest = c
        mapa_c2p[c] = dest
    mapa_p2c = defaultdict(list)
    for c, p in mapa_c2p.items(): mapa_p2c[p].append(c)
    dem_comp = {p: round(sum(dict_demandas.get(c,0) for c in ms), 2)
                for p, ms in mapa_p2c.items()}
    for n, kg in dem_comp.items(): G.nodes[n]['demanda_kg'] = kg
    nodos_comp = sorted(mapa_p2c.keys())
    if verbose:
        n_o = len(clientes_orig); n_c = len(nodos_comp)
        print(f"  CompactaciÃ³n: {n_o} â†’ {n_c} (-{n_o-n_c}, {(n_o-n_c)/n_o*100:.1f}%)")
    return {"nodos_clientes": nodos_comp, "dict_demandas": dem_comp,
            "mapa_c2p": dict(mapa_c2p), "mapa_p2c": dict(mapa_p2c),
            "clientes_originales": clientes_orig}


# ============================================================
# CELDA 2: DistribuciÃ³n de Demanda
# ============================================================
PESOS_RESIDUO = {
    'hogar_urbano': 1.0, 'bar': 4.06, 'restaurant': 8.50, 'hotel': 5.69,
    'escuela': 37.09, 'universidad': 111.19,
    'mercado_pequeno': 1149.25, 'mercado_grande': 7208.96, 'otros': 1.0
}
np.random.seed(40); random.seed(40)
TOTAL_BASURA_KG = 60000.0
tags = {'amenity': ['restaurant','cafe','fast_food','bar','pub','marketplace','school'],
        'shop': True, 'tourism': ['hotel','hostel'],
        'building': ['apartments','retail','commercial']}
transformer = Transformer.from_crs("epsg:32717", "epsg:4326", always_xy=True)
pts_utm = [(G.nodes[n]['x'], G.nodes[n]['y']) for n in nodos_clientes]
pts_wgs84 = [transformer.transform(x, y) for x, y in pts_utm]
print(f"  Coordenadas convertidas UTMâ†’WGS84: {len(pts_wgs84)} puntos")

# Verificar que la conversiÃ³n tiene sentido (Cuenca estÃ¡ ~lon=-79, lat=-2.9)
lon_medio = sum(p[0] for p in pts_wgs84) / len(pts_wgs84)
lat_medio = sum(p[1] for p in pts_wgs84) / len(pts_wgs84)
print(f"  Centroide del Ã¡rea: lon={lon_medio:.4f}, lat={lat_medio:.4f}")

poly_query = MultiPoint(pts_wgs84).convex_hull.buffer(0.005)
try:
    pois = ox.features_from_polygon(poly_query, tags)
    print(f"  POIs descargados desde OSM: {len(pois)}")
except Exception as e:
    pois = pd.DataFrame()
    print(f"  ADVERTENCIA: no se pudieron descargar POIs desde OSM")
    print(f"  Motivo: {e}")
    print(f"  Todos los nodos quedarÃ¡n con peso base 1.0 (sin diferenciaciÃ³n por tipo)")

pesos = {n: 1.0 for n in nodos_clientes}
if not pois.empty:
    pois['centroid'] = (pois.geometry
                    .to_crs('epsg:32717')
                    .centroid)
    n_pois_asignados = 0
    n_pois_error = 0
    conteo_tipos = defaultdict(int)
    for _, row in pois.iterrows():
        try:
            nn = ox.distance.nearest_nodes(G, row['centroid'].x, row['centroid'].y)
            if nn not in pesos: continue
            amenity  = row.get('amenity','');  tourism  = row.get('tourism','')
            building = row.get('building',''); shop     = row.get('shop','')
            tipo_gen = 'otros'
            if   tourism  in ['hotel','hostel']:                tipo_gen = 'hotel'
            elif amenity  in ['restaurant','fast_food','cafe']:  tipo_gen = 'restaurant'
            elif amenity  in ['bar','pub']:                      tipo_gen = 'bar'
            elif amenity  == 'university':                       tipo_gen = 'universidad'
            elif amenity  in ['school','college']:               tipo_gen = 'escuela'
            elif amenity  == 'marketplace':                      tipo_gen = 'mercado_grande'
            elif building == 'apartments':
                pesos[nn] += 8.0 * PESOS_RESIDUO['hogar_urbano']
                n_pois_asignados += 1
                conteo_tipos['apartments'] += 1
                continue
            elif building in ['house','residential']:            tipo_gen = 'hogar_urbano'
            elif shop and not pd.isna(shop):                    tipo_gen = 'otros'
            conteo_tipos[tipo_gen] += 1
            pesos[nn] += PESOS_RESIDUO[tipo_gen]
            n_pois_asignados += 1
        except Exception as e:
            n_pois_error += 1

if pois.empty:
    print(f"  Nodos con peso base 1.0 (sin POIs): {len(pesos)}")
else:
    print(f"  POIs asignados a nodos clientes: {n_pois_asignados}")
    print(f"  POIs con error al procesar     : {n_pois_error}")
    print(f"  POIs fuera del Ã¡rea de clientes: {len(pois) - n_pois_asignados - n_pois_error}")
    print(f"  DistribuciÃ³n de POIs por tipo:")
    for tipo, cnt in sorted(conteo_tipos.items(), key=lambda x: -x[1]):
        print(f"    {tipo:20s}: {cnt}")

factor = TOTAL_BASURA_KG / sum(pesos.values())
for n in nodos_clientes:
    dict_demandas[n] = max(round(pesos[n]*factor*np.random.uniform(0.95,1.05), 2), 1.0)
diff = TOTAL_BASURA_KG - sum(dict_demandas.values())
dict_demandas[max(dict_demandas, key=dict_demandas.get)] += round(diff, 2)
for n, kg in dict_demandas.items(): G.nodes[n]['demanda_kg'] = kg
print(f"  Total basura: {sum(dict_demandas.values()):.2f} kg")


# ============================================================
# CELDA 2.5: CompactaciÃ³n
# ============================================================
print("\n" + "="*70)
print("  COMPACTACIÃ“N OPERATIVA")
print("="*70)

UMBRAL_COMPACTACION_METROS = 80  # umbral Ãºnico para evitar inconsistencias

class MatrizWrapper:
    def __init__(self, G):
        self.G = G; self.cache = {}; self._lock = threading.Lock()
    def get_distance(self, a, b):
        key = (a, b)
        with self._lock:
            if key in self.cache: return self.cache[key]
        try:
            d = nx.shortest_path_length(self.G, a, b, weight='length')
        except nx.NetworkXNoPath:
            d = float('inf')
        except nx.NodeNotFound:
            d = float('inf')
            print(f"  ADVERTENCIA: nodo no encontrado en grafo al calcular distancia {a}â†’{b}")
        with self._lock: self.cache[key] = d
        return d

matriz_comp = MatrizWrapper(G)
res = compactar_clientes_operativos(
    G, nodos_clientes, dict_demandas, matriz_comp,
    [id_estacion], [id_relleno], UMBRAL_COMPACTACION_METROS, True)

nodos_clientes  = res["nodos_clientes"]
dict_demandas   = res["dict_demandas"]
mapa_c2p        = res["mapa_c2p"]
mapa_p2c        = res["mapa_p2c"]
clientes_orig_  = res["clientes_originales"]
set_clientes    = set(nodos_clientes)

# VerificaciÃ³n post-compactaciÃ³n
demanda_total = sum(dict_demandas.values())
demanda_orig  = sum(dict_demandas.get(c, 0) for c in clientes_orig_)

clientes_sin_mapeo = [c for c in clientes_orig_ if c not in mapa_c2p]
clientes_sin_padre = [c for c in nodos_clientes if c not in mapa_p2c]

print(f"  Clientes operativos: {len(nodos_clientes)} | "
      f"Demanda: {demanda_total:.2f} kg")
print(f"  Umbral de compactaciÃ³n usado: {UMBRAL_COMPACTACION_METROS} m")

if clientes_sin_mapeo:
    print(f"  ADVERTENCIA: {len(clientes_sin_mapeo)} clientes sin mapeo en mapa_c2p")
else:
    print(f"  Todos los {len(clientes_orig_)} clientes originales tienen mapeo correcto")

if clientes_sin_padre:
    print(f"  ADVERTENCIA: {len(clientes_sin_padre)} nodos operativos sin entradas en mapa_p2c")
else:
    print(f"  Todos los {len(nodos_clientes)} nodos operativos tienen clientes asignados")

if abs(demanda_total - demanda_orig) > 0.1:
    print(f"  ADVERTENCIA: demanda no se conservÃ³ â€” "
          f"original={demanda_orig:.2f} kg, actual={demanda_total:.2f} kg")
else:
    print(f"  Demanda conservada correctamente tras compactaciÃ³n")
