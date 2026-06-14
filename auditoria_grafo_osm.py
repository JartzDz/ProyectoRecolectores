# -*- coding: utf-8 -*-
"""
Auditoria del grafo OSM usado para ruteo.

Genera capas y reportes para distinguir problemas de:
- datos OSM incompletos o sentidos mal etiquetados,
- nodos no alcanzables por direccion de via,
- clientes sin ruta hacia/desde puntos clave,
- nodos que existen en el grafo pero no se estaban dibujando.
"""

from pathlib import Path
from collections import Counter
import math

import geopandas as gpd
import networkx as nx
import osmnx as ox
import pandas as pd
from shapely.geometry import Point


GRAPHML_PATH = "grafo_actualizado.graphml"
OUTPUT_DIR = Path("auditoria_grafo_osm")

LOC_ESTACION = (-2.8758464, -78.9814250)  # lat, lon
LOC_RELLENO = (-2.965480, -78.930210)     # lat, lon


def as_bool(value):
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    text = str(value).strip().lower()
    return text in {"true", "yes", "1", "-1"}


def first_value(value):
    if isinstance(value, (list, tuple)) and value:
        return value[0]
    return value


def is_blank(value):
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    if isinstance(value, (list, tuple, set)):
        return len(value) == 0 or all(is_blank(item) for item in value)
    return str(value).strip() == ""


def get_key_nodes(G):
    id_estacion = None
    id_relleno = None

    for nodo, data in G.nodes(data=True):
        tipo = data.get("tipo_nodo", "")
        if tipo == "estacion":
            id_estacion = nodo
        elif tipo == "relleno":
            id_relleno = nodo

    if id_estacion is None:
        id_estacion = ox.distance.nearest_nodes(G, LOC_ESTACION[1], LOC_ESTACION[0])
    if id_relleno is None:
        id_relleno = ox.distance.nearest_nodes(G, LOC_RELLENO[1], LOC_RELLENO[0])

    return id_estacion, id_relleno


def node_point(G, node):
    return Point(float(G.nodes[node]["x"]), float(G.nodes[node]["y"]))


def safe_float(value, default=math.nan):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def build_nodes_layer(G, largest_strong, from_station, to_relleno, weak_component_id, strong_component_id):
    rows = []
    for node, data in G.nodes(data=True):
        in_degree = G.in_degree(node)
        out_degree = G.out_degree(node)
        tipo = data.get("tipo_nodo", "calle")

        issues = []
        if node not in largest_strong:
            issues.append("fuera_componente_principal_dirigida")
        if in_degree == 0:
            issues.append("sin_entrada")
        if out_degree == 0:
            issues.append("sin_salida")
        if tipo == "cliente" and node not in from_station:
            issues.append("cliente_no_alcanzable_desde_estacion")
        if tipo == "cliente" and node not in to_relleno:
            issues.append("cliente_no_llega_a_relleno")

        rows.append({
            "id_nodo": int(node),
            "tipo_nodo": tipo,
            "in_degree": int(in_degree),
            "out_degree": int(out_degree),
            "street_count": safe_float(data.get("street_count")),
            "demanda_kg": safe_float(data.get("demanda_kg"), 0.0),
            "weak_comp": weak_component_id.get(node, -1),
            "strong_comp": strong_component_id.get(node, -1),
            "en_comp_principal": node in largest_strong,
            "alcanzable_estacion": node in from_station,
            "puede_llegar_relleno": node in to_relleno,
            "problemas": ";".join(issues),
            "geometry": node_point(G, node),
        })

    return gpd.GeoDataFrame(rows, crs="EPSG:4326")


def build_problem_edges_layer(G, nodes_with_issues):
    _, gdf_edges = ox.graph_to_gdfs(G)
    gdf_edges = gdf_edges.reset_index()

    def edge_issue(row):
        issues = []
        if row["u"] in nodes_with_issues or row["v"] in nodes_with_issues:
            issues.append("conecta_nodo_problematico")
        if as_bool(row.get("oneway")):
            issues.append("oneway")
        if is_blank(row.get("name")):
            issues.append("sin_nombre")
        if is_blank(row.get("geometry")):
            issues.append("sin_geometria_real")
        return ";".join(issues)

    gdf_edges["problemas"] = gdf_edges.apply(edge_issue, axis=1)
    problem_edges = gdf_edges[gdf_edges["problemas"] != ""].copy()

    keep = [
        "u", "v", "key", "osmid", "name", "highway", "oneway", "length",
        "problemas", "geometry",
    ]
    keep = [col for col in keep if col in problem_edges.columns]
    return problem_edges[keep]


def component_lookup(components):
    lookup = {}
    for idx, comp in enumerate(components, start=1):
        for node in comp:
            lookup[node] = idx
    return lookup


def component_summary(components, kind):
    rows = []
    for idx, comp in enumerate(components, start=1):
        rows.append({
            "tipo": kind,
            "componente": idx,
            "nodos": len(comp),
            "muestra_nodos": ",".join(str(n) for n in list(comp)[:10]),
        })
    return rows


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)

    print(f"Cargando grafo: {GRAPHML_PATH}")
    G = ox.load_graphml(GRAPHML_PATH)
    print(f"Grafo: {G.number_of_nodes()} nodos, {G.number_of_edges()} aristas")

    id_estacion, id_relleno = get_key_nodes(G)
    print(f"Estacion: {id_estacion}")
    print(f"Relleno: {id_relleno}")

    weak_components = sorted(nx.weakly_connected_components(G), key=len, reverse=True)
    strong_components = sorted(nx.strongly_connected_components(G), key=len, reverse=True)
    largest_strong = strong_components[0] if strong_components else set()

    from_station = nx.descendants(G, id_estacion) | {id_estacion}
    to_relleno = nx.ancestors(G, id_relleno) | {id_relleno}

    weak_component_id = component_lookup(weak_components)
    strong_component_id = component_lookup(strong_components)

    clientes = [n for n, d in G.nodes(data=True) if d.get("tipo_nodo") == "cliente"]
    clientes_sin_estacion = [n for n in clientes if n not in from_station]
    clientes_sin_relleno = [n for n in clientes if n not in to_relleno]

    gdf_nodes = build_nodes_layer(
        G, largest_strong, from_station, to_relleno,
        weak_component_id, strong_component_id,
    )
    nodes_with_issues = set(
        int(row.id_nodo)
        for row in gdf_nodes.itertuples()
        if row.problemas
    )
    gdf_problem_edges = build_problem_edges_layer(G, nodes_with_issues)

    clientes_problematicos = gdf_nodes[
        gdf_nodes["problemas"].str.contains("cliente_", na=False)
    ].copy()
    nodos_problematicos = gdf_nodes[gdf_nodes["problemas"] != ""].copy()

    gpkg_path = OUTPUT_DIR / "auditoria_grafo_osm.gpkg"
    gdf_nodes.to_file(gpkg_path, layer="todos_los_nodos", driver="GPKG")
    nodos_problematicos.to_file(gpkg_path, layer="nodos_problematicos", driver="GPKG")
    clientes_problematicos.to_file(gpkg_path, layer="clientes_sin_ruta", driver="GPKG")
    gdf_problem_edges.to_file(gpkg_path, layer="aristas_a_revisar", driver="GPKG")

    edge_oneway = Counter()
    edge_highway = Counter()
    missing_geometry = 0
    missing_name = 0
    for _, _, _, data in G.edges(keys=True, data=True):
        edge_oneway[str(data.get("oneway", None))] += 1
        edge_highway[str(first_value(data.get("highway", "")))] += 1
        if not data.get("geometry"):
            missing_geometry += 1
        if not data.get("name"):
            missing_name += 1

    resumen = {
        "nodos": G.number_of_nodes(),
        "aristas": G.number_of_edges(),
        "clientes": len(clientes),
        "componentes_debiles": len(weak_components),
        "componentes_fuertes": len(strong_components),
        "nodos_fuera_comp_fuerte_principal": G.number_of_nodes() - len(largest_strong),
        "nodos_sin_entrada": sum(1 for n in G.nodes if G.in_degree(n) == 0),
        "nodos_sin_salida": sum(1 for n in G.nodes if G.out_degree(n) == 0),
        "clientes_no_alcanzables_desde_estacion": len(clientes_sin_estacion),
        "clientes_no_llegan_a_relleno": len(clientes_sin_relleno),
        "aristas_sin_geometria_real": missing_geometry,
        "aristas_sin_nombre": missing_name,
        "aristas_oneway_true": sum(
            count for value, count in edge_oneway.items() if as_bool(value)
        ),
        "id_estacion": id_estacion,
        "id_relleno": id_relleno,
    }

    pd.DataFrame([resumen]).to_csv(OUTPUT_DIR / "resumen_auditoria.csv", index=False)
    pd.DataFrame(
        component_summary(weak_components, "debil")
        + component_summary(strong_components, "fuerte")
    ).to_csv(OUTPUT_DIR / "componentes.csv", index=False)
    clientes_problematicos.drop(columns="geometry").to_csv(
        OUTPUT_DIR / "clientes_sin_ruta.csv", index=False
    )
    nodos_problematicos.drop(columns="geometry").to_csv(
        OUTPUT_DIR / "nodos_problematicos.csv", index=False
    )
    pd.DataFrame(edge_oneway.items(), columns=["oneway", "aristas"]).to_csv(
        OUTPUT_DIR / "conteo_oneway.csv", index=False
    )
    pd.DataFrame(edge_highway.most_common(), columns=["highway", "aristas"]).to_csv(
        OUTPUT_DIR / "conteo_highway.csv", index=False
    )

    txt_path = OUTPUT_DIR / "resumen_auditoria.txt"
    with txt_path.open("w", encoding="utf-8") as f:
        f.write("AUDITORIA GRAFO OSM\n")
        f.write("===================\n\n")
        for key, value in resumen.items():
            f.write(f"{key}: {value}\n")
        f.write("\nClientes sin ruta desde estacion:\n")
        f.write(", ".join(str(n) for n in clientes_sin_estacion) or "Ninguno")
        f.write("\n\nClientes sin ruta hacia relleno:\n")
        f.write(", ".join(str(n) for n in clientes_sin_relleno) or "Ninguno")
        f.write("\n")

    print("\nResumen:")
    for key, value in resumen.items():
        print(f"  {key}: {value}")
    print(f"\nArchivos generados en: {OUTPUT_DIR.resolve()}")
    print(f"GeoPackage principal: {gpkg_path}")
    print(f"Resumen texto: {txt_path}")


if __name__ == "__main__":
    main()
