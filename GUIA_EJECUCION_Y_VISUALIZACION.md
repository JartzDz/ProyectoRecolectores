# Guia de ejecucion y visualizacion

## Como ejecutar

El algoritmo acepta parametros antes de iniciar, desde la consola:

```powershell
python main.py
```

Si se ejecuta sin parametros en una consola interactiva, el sistema pregunta que escenario procesar:

```text
1) 60 toneladas
2) 120 toneladas
3) Otro valor
Enter) Usar valor por defecto: 120 toneladas
```

Si se presiona Enter, o si la ejecucion no permite entrada interactiva, usa los valores originales del escenario:

- 120 toneladas.
- 12000 kg de capacidad por camion.
- 10 camiones maximos.
- 8 horas de jornada.
- Velocidades originales del script.
- Calles base visibles en el HTML.

Despues del escenario, el sistema pregunta si se desean ajustar parametros operativos y de costos. Si se responde `s`, permite modificar:

- Capacidad maxima por camion.
- Camiones disponibles.
- Jornada maxima.
- Tiempo por parada.
- Recolectores y choferes por camion.
- Sueldos, horas de nomina, precio del diesel y rendimiento.
- Velocidades de acercamiento, recoleccion, transporte y retorno.

Tambien se pueden sobrescribir valores puntuales:

```powershell
python main.py --toneladas 120 --capacidad-camion-kg 12000 --camiones 10 --horas-trabajo 8
```

Para escenarios predefinidos se puede usar:

```powershell
python main.py --escenario 60t
python main.py --escenario 120t
```

Parametros principales:

- `--escenario`: atajo para ejecutar `60t` o `120t`.
- `--toneladas`: basura total del escenario.
- `--capacidad-camion-kg`: capacidad maxima de cada camion por viaje.
- `--camiones`: cantidad maxima de camiones disponibles.
- `--horas-trabajo`: jornada maxima por camion.
- `--vel-acercamiento`: velocidad desde estacion o relleno al primer cliente.
- `--vel-recoleccion`: velocidad durante la recoleccion.
- `--vel-transporte`: velocidad desde el ultimo cliente al relleno.
- `--vel-retorno`: velocidad de retorno del relleno a la estacion.
- `--recolectores`: numero de recolectores por camion.
- `--choferes`: numero de choferes por camion.
- `--sueldo-recolector`: sueldo mensual por recolector.
- `--sueldo-chofer`: sueldo mensual por chofer.
- `--horas-nomina`: horas mensuales para estimar costo laboral.
- `--tiempo-parada-seg`: tiempo de servicio por parada.
- `--precio-diesel`: precio del diesel por galon.
- `--rendimiento-km-gal`: rendimiento estimado del camion.
- `--configurar-parametros`: abre el asistente interactivo de parametros aunque se use un escenario por consola.
- `--salida-html`: nombre del archivo HTML generado.
- `--incluir-calles`: `si` o `no` para mostrar la red vial base.

Para ver todos los parametros:

```powershell
python main.py --help
```

## Archivos que genera

- `mapa_rutas_recoleccion_<toneladas>t.html`: mapa interactivo.
- `rutas_tramos_Camion_X.gpkg`: tramos geograficos de cada camion.
- `kpi_viajes.csv`: resumen por viaje.
- `kpi_camiones.csv`: resumen por camion.
- `kpi_nodos.csv`: resumen por nodo/cliente.
- `comparacion_*.csv`: tablas comparativas del algoritmo.

## Como leer el mapa

- Lineas grises: recorrido total planificado para cada camion.
- Linea oscura: ruta que se va dibujando mientras avanza la animacion.
- Marcador `R1`, `R2`, etc.: camion animado.
- Codigo `2.3` en la tabla: Camion 2, Viaje 3.
- Flujo de cada viaje: salida desde estacion o relleno, recoleccion de clientes y descarga final en relleno.

## Capas

El control de capas del mapa permite activar o desactivar:

- Sectores iniciales.
- Clientes.
- Puntos clave.
- Calles base.
- Ruta completa de cada camion.
- Viajes individuales de cada camion.

## Notas de mantenimiento

Los parametros editables estan al inicio de `main.py` y tambien pueden sobrescribirse por consola. La visualizacion se genera en la seccion de HTML interactivo, donde se construyen los GeoJSON, metricas y el archivo final.

