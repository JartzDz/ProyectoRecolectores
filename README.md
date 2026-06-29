# Entrega del proyecto

Esta carpeta contiene solamente codigo, datos necesarios para ejecutar y salidas finales generadas por el algoritmo.

## Codigo y guia

- `main.py`: algoritmo principal Clarke & Wright con servicio por parada `T(w)=10+0.122w`.
- `pipeline_compactación.py`: generacion/compactacion de clientes operativos.
- `gpkg_to_graphml.py`: conversion auxiliar de datos geograficos.
- `GUIA_EJECUCION_Y_VISUALIZACION.md`: comandos y lectura de resultados.

## Datos base necesarios

- `grafo_actualizado.graphml`
- `clientes_compactados.gpkg`
- `nodosAreaFinal.gpkg`
- `ecu_pd_2020_1km.tif`

## Salidas finales generadas

- `mapa_rutas_recoleccion_60t.html` y `.json`
- `mapa_rutas_recoleccion_120t.html` y `.json`
- `rutas_60t.png`
- `rutas_120t.png`
- `kpi_rutas_60t.csv`
- `kpi_rutas_120t.csv`
- `kpi_camiones_60t.csv`
- `kpi_camiones_120t.csv`
- `comparacion_algoritmos.csv`
- `comparacion_k_zonas.csv`
- `comparacion_operativa.csv`

## Capas geograficas generadas

- `base_calles.gpkg`
- `base_clientes.gpkg`
- `base_puntos_clave.gpkg`
- `rutas_tramos_Camion_1.gpkg` a `rutas_tramos_Camion_5.gpkg`

## Nota

La carpeta contiene únicamente los archivos necesarios para ejecutar el algoritmo y revisar los resultados finales generados para los escenarios de 60 y 120 toneladas.