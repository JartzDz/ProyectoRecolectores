# -*- coding: utf-8 -*-
"""
Actualizar clientes en GraphML usando un GPKG
=============================================

El script:

1. Carga un .graphml original
2. Carga un .gpkg con nodos seleccionados
3. Convierte esos nodos en clientes
4. Elimina clientes anteriores
5. Inicializa demanda_kg en 0
6. Guarda un nuevo .graphml

NOTA:
La demanda real NO se calcula aquí.
Este script únicamente marca nodos como clientes.

La demanda real será calculada posteriormente
por el pipeline de generación espacial de residuos.

Requisitos:
    pip install osmnx geopandas networkx
"""

import os
import osmnx as ox
import geopandas as gpd


# ============================================================
# CONFIGURACIÓN
# ============================================================

GRAPHML_ORIGINAL = "grafo_cuenca.graphml"

GPKG_CLIENTES = "nodosAreaFinal.gpkg"

GRAPHML_SALIDA = "grafo_actualizado.graphml"


# ============================================================
# CARGAR GRAFO
# ============================================================

print("=" * 60)
print("ACTUALIZADOR DE CLIENTES GRAPHML")
print("=" * 60)

print("\n📥 Cargando grafo...")

G = ox.load_graphml(GRAPHML_ORIGINAL)

print(f"✅ Grafo cargado:")
print(f"   Nodos   : {G.number_of_nodes()}")
print(f"   Aristas : {G.number_of_edges()}")


# ============================================================
# LIMPIAR CLIENTES ANTERIORES
# ============================================================

print("\n🧹 Eliminando clientes anteriores...")

clientes_previos = 0

for n, data in G.nodes(data=True):

    if data.get("tipo_nodo") == "cliente":

        # Restaurar nodo normal
        G.nodes[n]["tipo_nodo"] = "calle"

        # Reiniciar demanda
        G.nodes[n]["demanda_kg"] = 0.0

        clientes_previos += 1

print(f"✅ Clientes anteriores eliminados: {clientes_previos}")


# ============================================================
# CARGAR GPKG
# ============================================================

print("\n📥 Cargando GPKG de clientes...")

gdf = gpd.read_file(GPKG_CLIENTES)

print(f"✅ Registros encontrados: {len(gdf)}")


# ============================================================
# CONVERTIR PUNTOS EN CLIENTES
# ============================================================

print("\n🔄 Asignando nuevos clientes...")

clientes_nuevos = 0
nodos_asignados = set()

for idx, row in gdf.iterrows():

    try:

        geom = row.geometry

        if geom is None:
            continue

        x = geom.x
        y = geom.y

        # Buscar nodo más cercano
        nodo = ox.distance.nearest_nodes(G, x, y)

        # Evitar duplicados
        if nodo in nodos_asignados:
            continue

        # Marcar como cliente
        G.nodes[nodo]["tipo_nodo"] = "cliente"

        # Inicializar demanda
        # La demanda real se calculará después
        G.nodes[nodo]["demanda_kg"] = 1.0

        nodos_asignados.add(nodo)

        clientes_nuevos += 1

    except Exception as e:

        print(f"⚠️ Error en fila {idx}: {e}")

print(f"✅ Nuevos clientes asignados: {clientes_nuevos}")


# ============================================================
# VERIFICACIÓN
# ============================================================

clientes_finales = [
    n for n, d in G.nodes(data=True)
    if d.get("tipo_nodo") == "cliente"
]

print("\n📊 RESUMEN FINAL")

print(f"   Clientes totales: {len(clientes_finales)}")


# ============================================================
# GUARDAR GRAPHML
# ============================================================

print("\n💾 Guardando nuevo GraphML...")

ox.save_graphml(G, GRAPHML_SALIDA)

print(f"✅ Archivo generado:")
print(f"   {GRAPHML_SALIDA}")

print("\n🎉 PROCESO COMPLETADO")