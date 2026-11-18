"""
Genera los 3 PDF de 3. Documentación: README.pdf, Manual_Consultas_SQL.pdf y Arquitectura_Tecnica.pdf.

Cada PDF se arma como una página HTML (estilo simple: Arial, títulos negros, tablas grises) y Google Chrome
en modo headless la imprime a PDF. El contenido sale de:
  - README.md (README.pdf, más un anexo con los diagramas)
  - el notebook del Avance 2, 02_queries_analysis.sql, queries_6_8_11_12.sql y tiempos_indices.csv (Manual).
    Las queries se vuelven a correr contra PostgreSQL para mostrar el resultado.
  - el notebook del Avance 4 (Arquitectura)

Requisitos: la base fleetlogix cargada (pasos 1 a 3 del README), el archivo .env y Google Chrome.
Uso:  python "3. Documentación/generadores/generar_pdfs.py"
      (si Chrome no está en la ruta de Mac, indicarla con la variable CHROME)
"""
import os, re, subprocess, html, tempfile
from pathlib import Path
import mistune, nbformat
import pandas as pd
from sqlalchemy import create_engine

RAIZ = str(Path(__file__).resolve().parents[2])
DOC = os.path.join(RAIZ, '3. Documentación')
TMP = tempfile.mkdtemp()     # acá quedan los HTML intermedios
CHROME = os.getenv('CHROME', '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(RAIZ, '.env'))
except ImportError:
    pass
md = mistune.create_markdown(plugins=['table'], escape=False)

CSS = """
@page { size: A4; margin: 20mm 18mm; }
body { font-family: Arial, Helvetica, sans-serif; font-size: 11pt; line-height: 1.4; color: #000; background: #fff; }
h1 { font-size: 18pt; margin: 0 0 6pt; }
h2 { font-size: 14pt; margin-top: 18pt; page-break-after: avoid; }
h3 { font-size: 12pt; margin-top: 12pt; page-break-after: avoid; }
p, li { margin: 4pt 0; }
table { border-collapse: collapse; width: 100%; margin: 6pt 0 10pt; font-size: 9.5pt; }
tr { page-break-inside: avoid; }
th { background: #e8e8e8; text-align: left; padding: 3pt 5pt; border: 1px solid #999; }
td { border: 1px solid #999; padding: 3pt 5pt; vertical-align: top; }
td.n { white-space: nowrap; }
td.n, th.n { text-align: right; }
code { font-family: "Courier New", monospace; font-size: 9.5pt; }
pre { border: 1px solid #ccc; padding: 6pt; font-size: 8.5pt; white-space: pre-wrap; page-break-inside: avoid; }
pre code { font-size: 8.5pt; }
img { max-width: 100%; display: block; margin: 8pt auto; }
hr { border: none; border-top: 1px solid #999; margin: 14pt 0; }
.sub { margin-bottom: 14pt; }
.salto { page-break-before: always; }
"""


def a_pdf(nombre, titulo, cuerpo_html):
    ruta_html = os.path.join(TMP, nombre.replace('.pdf', '.html'))
    with open(ruta_html, 'w', encoding='utf-8') as f:
        f.write(f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>{titulo}</title>'
                f'<base href="{Path(DOC).as_uri()}/"><style>{CSS}</style></head><body>{cuerpo_html}</body></html>')
    salida = os.path.join(DOC, nombre)
    subprocess.run([CHROME, '--headless=new', '--disable-gpu', '--no-pdf-header-footer',
                    '--allow-file-access-from-files', f'--print-to-pdf={salida}', Path(ruta_html).as_uri()],
                   check=True, capture_output=True)
    print('PDF:', salida, os.path.getsize(salida) // 1024, 'KB')


def tabla(df, enteros=(), decimales=()):
    """DataFrame -> tabla HTML con números alineados a la derecha y formato es-AR (1.234,5)."""
    def fmt(v, col):
        if pd.isna(v):
            return ''
        if col in enteros:
            return f'{v:,.0f}'.replace(',', '.')
        if col in decimales:
            return f'{v:,.2f}'.replace(',', 'X').replace('.', ',').replace('X', '.')
        return html.escape(str(v))
    num = set(enteros) | set(decimales)
    cab = ''.join(f'<th class="{"n" if c in num else ""}">{html.escape(str(c)).replace("_", "_&#8203;")}</th>' for c in df.columns)
    filas = ''.join('<tr>' + ''.join(f'<td class="{"n" if c in num else ""}">{fmt(v, c)}</td>'
                                       for c, v in zip(df.columns, fila)) + '</tr>'
                    for fila in df.itertuples(index=False))
    return f'<table><thead><tr>{cab}</tr></thead><tbody>{filas}</tbody></table>'


# ---------------------------------------------------------------- README.pdf
readme = open(os.path.join(RAIZ, 'README.md'), encoding='utf-8').read()
readme = readme.replace('3.%20Documentación/img/', 'img/')  # en el PDF las imágenes son relativas a 3. Documentación
readme = re.sub(r'^\[!\[CI\]\(.*\n', '', readme, flags=re.M)  # la insignia del CI tiene sentido en GitHub, no en el PDF
cuerpo = md(readme)
cuerpo += ('<div class="salto"></div><h2>Anexo: diagramas</h2>'
           '<h3>Modelo entidad-relación (PostgreSQL)</h3><img src="img/diagrama_ER_fleetlogix.png">'
           '<h3>Modelo estrella (Snowflake)</h3><img src="img/modelo_estrella.png">'
           '<div class="salto"></div><h3>Data Warehouse en Snowflake: tablas creadas</h3><img src="img/snowflake_01_tablas.jpg">'
           '<h3>Data Warehouse en Snowflake: consulta sobre el modelo estrella</h3><img src="img/snowflake_02_consulta.jpg">'
           '<div class="salto"></div><h3>Arquitectura AWS</h3><img src="../2.%20Scripts/aws_architecture_diagram.png">')
a_pdf('README.pdf', 'FleetLogix README', cuerpo)

# ---------------------------------------------------------------- Manual_Consultas_SQL.pdf
nb2 = nbformat.read(os.path.join(RAIZ, '1. Notebooks', 'Avance_2_SQLAnalysis.ipynb'), 4)
celda = lambda i: nb2.cells[i].source

texto = open(os.path.join(RAIZ, '2. Scripts', '02_queries_analysis.sql'), encoding='utf-8').read()
partes = re.split(r'\n-- (Query \w+):', texto)
queries = {}
for i in range(1, len(partes), 2):
    cuerpo_q = partes[i + 1].split('\n', 1)[1]
    cuerpo_q = '\n'.join(l for l in cuerpo_q.splitlines() if l.strip() and not l.strip().startswith('--'))
    queries[partes[i]] = cuerpo_q[:cuerpo_q.index(';') + 1]

engine = create_engine('postgresql+psycopg2://', connect_args=dict(
    host=os.getenv('PGHOST', 'localhost'), port=int(os.getenv('PGPORT', 5432)), dbname=os.getenv('PGDATABASE', 'fleetlogix'),
    user=os.getenv('PGUSER', os.getenv('USER')), password=os.getenv('PGPASSWORD', '')))
q = lambda nombre: pd.read_sql(queries[nombre].rstrip(';'), engine)


def bloque(nombre, i_titulo, i_interp, resultado_html, extra=''):
    titulo = celda(i_titulo).replace('### ', '## ')
    return (md(titulo) + '<h3>SQL</h3><pre><code>' + html.escape(queries[nombre]) + '</code></pre>'
            + '<h3>Resultado</h3>' + resultado_html + extra + md(celda(i_interp)))


s = []
s.append('<h1>Manual de Consultas SQL</h1><div class="sub">Proyecto Integrador M2 - FleetLogix<br>Tomás Babot<br><br>'
         'Base PostgreSQL <code>fleetlogix</code> (505.650 registros). Scripts: <code>2. Scripts/02_queries_analysis.sql</code> '
         'y <code>03_optimization_indexes.sql</code>. Todo lo ejecuté en <code>1. Notebooks/Avance_2_SQLAnalysis.ipynb</code>.<br><br>'
         'En este manual explico las 12 queries que dio Henry: primero las 8 que elegí para el análisis y la optimización, '
         'y al final las otras 4 (6, 8, 11 y 12).</div>')
s.append(md(celda(0).split('\n', 3)[3]))   # intro y tabla de queries elegidas (sin el título del notebook)

s.append(bloque('Query 1', 3, 5, tabla(q('Query 1'), enteros=['cantidad'])))
s.append(bloque('Query 2', 6, 8, tabla(q('Query 2'))))
s.append(bloque('Query 3', 9, 11, tabla(q('Query 3'), enteros=['total_viajes'])))
q4 = q('Query 4')
q4['%_entregas'] = (100 * q4['total_entregas'] / q4['total_entregas'].sum()).round(1)
s.append(bloque('Query 4', 12, 14, tabla(q4, enteros=['total_viajes', 'total_entregas'],
                                          decimales=['peso_total_kg', '%_entregas'])))
q5 = q('Query 5')
d5 = q5['viajes_totales'].describe()
s.append(bloque('Query 5', 15, 17,
                '<p>Primeros 10 de ' + str(len(q5)) + ' conductores:</p>'
                + tabla(q5.head(10), enteros=['driver_id', 'viajes_totales', 'viajes_completados'])
                + f'<p>Viajes por conductor: promedio {d5["mean"]:.0f}, mediana {d5["50%"]:.0f}, '
                  f'mínimo {d5["min"]:.0f}, máximo {d5["max"]:.0f}.</p>'))
s.append(bloque('Query 7', 18, 20, tabla(q('Query 7'), enteros=['viajes_realizados'],
                                          decimales=['distance_km', 'promedio_combustible_litros', 'litros_por_100km', 'combustible_total'])))

cols9 = dict(enteros=['cantidad_vehiculos', 'viajes_totales', 'kilometros_totales', 'costo_total_mantenimiento'],
             decimales=['costo_por_km', 'costo_promedio_por_mantenimiento'])
q9, q9b = q('Query 9'), q('Query 9b')
km_real = pd.read_sql("SELECT SUM(r.distance_km) km FROM trips t JOIN routes r ON t.route_id=r.route_id WHERE t.status='completed'", engine)['km'][0]
costo_real = pd.read_sql('SELECT SUM(cost) c FROM maintenance', engine)['c'][0]
control = pd.DataFrame({'control': ['Kilómetros recorridos', 'Costo de mantenimiento (COP)'],
                        'real_en_la_base': [km_real, costo_real],
                        'query_9_original': [q9['kilometros_totales'].sum(), q9['costo_total_mantenimiento'].sum()],
                        'query_9b_corregida': [q9b['kilometros_totales'].sum(), q9b['costo_total_mantenimiento'].sum()]})
control['inflado_x'] = (control['query_9_original'] / control['real_en_la_base']).round(1)
s.append(md(celda(21).replace('### ', '## '))
         + '<h3>SQL original (con el error)</h3><pre><code>' + html.escape(queries['Query 9']) + '</code></pre>'
         + '<h3>SQL corregida (9b)</h3><pre><code>' + html.escape(queries['Query 9b']) + '</code></pre>'
         + '<h3>Resultado original</h3>' + tabla(q9, **cols9)
         + '<h3>Resultado corregido</h3>' + tabla(q9b, **cols9)
         + '<h3>Control contra los totales reales</h3>'
         + tabla(control, enteros=['real_en_la_base', 'query_9_original', 'query_9b_corregida'], decimales=['inflado_x'])
         + md(celda(23)))
q10 = q('Query 10')
s.append('<div class="salto"></div>')
s.append(bloque('Query 10', 24, 26, '<p>Primeros 10 del ranking:</p>' + tabla(
    q10.head(10), enteros=['viajes', 'entregas', 'rank_puntualidad', 'rank_eficiencia', 'rank_productividad'],
    decimales=['consumo_100km', 'puntualidad_pct', 'score_promedio'])))

# --- Las otras 4 queries (6, 8, 11, 12), copiadas del archivo original de Henry
base = open(os.path.join(DOC, 'generadores', 'queries_6_8_11_12.sql'), encoding='utf-8').read()
partes_b = re.split(r'\n-- (Query \d+):', base)
for i in range(1, len(partes_b), 2):
    if partes_b[i] in ('Query 6', 'Query 8', 'Query 11', 'Query 12'):
        cq = partes_b[i + 1].split('\n', 1)[1]
        cq = '\n'.join(l for l in cq.splitlines() if l.strip() and not l.strip().startswith('--'))
        queries[partes_b[i]] = cq[:cq.index(';') + 1]


def extra_query(nombre, titulo, problema, resultado_html, interpretacion):
    return (f'<h2>{nombre}: {titulo}</h2><p><i>Problema:</i> {problema}</p><h3>SQL</h3><pre><code>'
            + html.escape(queries[nombre]) + '</code></pre><h3>Resultado</h3>' + resultado_html + md(interpretacion))


s.append('<div class="salto"></div><h2>Las otras 4 queries</h2>'
         '<p>La consigna pedía elegir 8 de las 12 queries para el análisis principal (las de arriba, que son las que están en '
         '<code>02_queries_analysis.sql</code> y en el notebook). Igual corrí y expliqué las otras 4, para tener el manual completo '
         'de las 12. No las usé para medir los índices.</p>')
q6 = q('Query 6'); d6 = q6.describe()
c = lambda x: f'{x:.2f}'.replace('.', ',')
s.append(extra_query('Query 6', 'Promedio de entregas por conductor (últimos 6 meses)', 'medir la productividad de cada conductor.',
    f'<p>Primeros 8 de {len(q6)} conductores:</p>' + tabla(q6.head(8), enteros=['driver_id', 'total_viajes', 'total_entregas'],
                                                        decimales=['promedio_entregas_por_viaje', 'promedio_entregas_diarias'])
    + f'<p>Entre los {len(q6)} conductores: {c(d6.loc["mean", "promedio_entregas_por_viaje"])} entregas por viaje en promedio '
      f'(de {c(d6.loc["min", "promedio_entregas_por_viaje"])} a {c(d6.loc["max", "promedio_entregas_por_viaje"])}) y '
      f'{c(d6.loc["mean", "promedio_entregas_diarias"])} entregas por día.</p>',
    '**Interpretación:** todos los conductores hacen alrededor de **4 entregas por viaje**, que es lo que define el script de '
    'generación (de 2 a 6 por viaje). Lo que más cambia entre conductores es la cantidad de viajes (de 14 a 106 en 6 meses), no las entregas por viaje. '
    'Ojo con `promedio_entregas_diarias`: divide siempre por 180 días, así que a los conductores contratados hace poco les da un '
    'promedio más bajo del real. Para comparar productividad conviene dividir por los días trabajados.'))
q8 = q('Query 8')
s.append(extra_query('Query 8', 'Entregas retrasadas por día de la semana (últimos 90 días)', 'encontrar patrones de retraso para planificar mejor.',
    tabla(q8, enteros=['num_dia', 'total_entregas', 'entregas_retrasadas'], decimales=['porcentaje_retrasos', 'minutos_promedio_diferencia']),
    '**Interpretación:** el porcentaje de entregas con más de 30 minutos de retraso es parecido todos los días, entre **13% y 14%**. '
    'Lo que sí cambia es el volumen: el domingo tiene un tercio de las entregas de un día hábil y el sábado tres cuartos. '
    'No hay un día problemático, así que el retraso no depende del día sino de otros factores (ciudad, mes, conductor). '
    'En estos 90 días el porcentaje es más alto que en todo el año (12%) porque incluye la temporada de lluvias. '
    'Detalle técnico: `TO_CHAR(..., \'Day\')` devuelve el nombre del día en inglés porque depende de la configuración de idioma del servidor.'))
q11 = q('Query 11')
s.append(extra_query('Query 11', 'Tendencia mensual de viajes con LAG y LEAD', 'proyectar necesidades futuras a partir de la tendencia.',
    tabla(q11, enteros=['total_viajes', 'viajes_mes_anterior', 'viajes_mes_siguiente', 'cambio_absoluto'],
          decimales=['cambio_porcentual', 'toneladas_transportadas', 'combustible_promedio_viaje', 'promedio_movil_3m']),
    '**Interpretación:** `LAG` trae el valor del mes anterior y `LEAD` el del mes siguiente, sin tener que hacer un JOIN de la tabla '
    'con sí misma. La demanda tiene **estacionalidad**: diciembre de 2025 fue el mes más alto (5.386 viajes) y enero de 2026 el más '
    'bajo (3.387, un 37% menos). Desde ahí crece hasta octubre (4.945). La caída de noviembre de 2026 **no es real**: el mes todavía '
    'no terminó. Para proyectar no alcanza el promedio móvil de 3 meses, porque no ve el pico de fin de año: conviene comparar '
    'cada mes con el mismo mes del año anterior.'))
q12 = q('Query 12')
s.append(extra_query('Query 12', 'Entregas por hora y día de la semana (pivot)', 'ajustar horarios de operación y personal.',
    tabla(q12, enteros=list(q12.columns)),
    '**Interpretación:** la query convierte los días en columnas con `SUM(CASE WHEN ...)` (un *pivot*). Las entregas programadas '
    'crecen desde las 6 de la mañana, se mantienen altas entre las 12 y las 19 (entre 2.150 y 2.270 por hora en los 60 días) '
    'y bajan desde las 20. El lunes es el día de más volumen (sale lo acumulado del fin de semana) y el domingo tiene menos de '
    'un tercio. Conviene concentrar a los repartidores y la atención al cliente en la franja de mayor volumen y '
    'reducir personal en las primeras horas.'))

# --- Índices
indices = pd.DataFrame([
    ('idx_deliveries_trip_id', 'deliveries(trip_id) INCLUDE (delivery_id, package_weight_kg, scheduled_datetime, delivered_datetime)',
     'PostgreSQL no indexa solo las claves foráneas; con INCLUDE la query se resuelve leyendo solo el índice (Index Only Scan)', '4, 10'),
    ('idx_maintenance_vehicle_cost', 'maintenance(vehicle_id) INCLUDE (cost, maintenance_id)',
     'busca los mantenimientos de cada vehículo y suma su costo sin ir a la tabla', '9, 9b'),
    ('idx_trips_vehicle_completed', "trips(vehicle_id) INCLUDE (trip_id, route_id) WHERE status = 'completed'",
     'índice parcial: guarda solo los viajes completados, que es exactamente el filtro de la query', '9, 9b'),
    ('idx_trips_status', 'trips(status)', 'el conteo por estado se hace leyendo solo el índice; sirve al tablero de operación', '3'),
    ('idx_drivers_license_expiry', 'drivers(license_expiry)',
     'filtro por fecha que devuelve pocas filas; evita que la alerta diaria se degrade si crece la planta', '2'),
], columns=['índice', 'definición', 'justificación', 'queries'])

t = pd.read_csv(os.path.join(DOC, 'tiempos_indices.csv'), index_col=0).reset_index().rename(columns={'index': 'query'})
t.columns = ['query', 'sin índices (ms)', 'con índices (ms)', 'índices + SSD (ms)', 'mejora índices %', 'mejora índices + SSD %']
dec = list(t.columns[1:])

s.append('<div class="salto"></div><h2>Optimización con índices</h2>')
s.append('<p>Criterio: un índice sirve cuando la query necesita <b>pocas filas de una tabla grande</b> (filtros y JOIN por clave). '
         'Si la query igual tiene que leer toda la tabla, el índice no ayuda y PostgreSQL lo ignora. Cada índice ocupa espacio y hace '
         'más lentos los INSERT, por eso creé solo los que tienen una query que los usa. El esquema base ya traía '
         '<code>idx_trips_departure</code>, <code>idx_deliveries_status</code> e <code>idx_vehicles_status</code>.</p>')
s.append('<h3>Los 5 índices que creé</h3>' + tabla(indices))
s.append(md(celda(27).replace('## 2. Optimización con índices', '### Método de medición').replace('**Método de medición:**', '')))
s.append('<h3>Resultados</h3>' + tabla(t, decimales=dec) + '<img src="img/tiempos_indices.png">')
# Tiempos de la Query 9 y la 9b medidos en el notebook del Avance 2 (sección 2.4)
s.append('<h3>Reescritura de la Query 9</h3>' + tabla(pd.DataFrame({
    'versión': ['9 original (sin índices)', '9 original (con índices)', '9b corregida (con índices)'],
    'ms': [5141.49, 1114.53, 32.74], 'veces más rápida': [1.0, 4.6, 157.0]}), decimales=['ms', 'veces más rápida']))
s.append('<h3>Qué cambió en los planes de ejecución</h3>'
         '<p><b>Query 4.</b> Antes: <code>Seq Scan on deliveries</code> (lee las 400.000 entregas) + <code>Hash Join</code>, 74 ms. '
         'Con índices y ajuste SSD: <code>Nested Loop</code> + <code>Index Only Scan using idx_deliveries_trip_id</code> '
         '(solo las ~38.400 entregas de los últimos 60 días), 45 ms.</p>'
         '<p><b>Query 9.</b> Antes: <code>Seq Scan</code> de trips y maintenance y un <code>Hash Join</code> que genera 3,5 millones de filas '
         '(el fan-out), 5.234 ms. Después: <code>Nested Loop Left Join</code> que toma los mantenimientos de cada vehículo desde el índice, '
         '1.114 ms. Sigue generando 3,5 millones de filas: por eso la solución de fondo es la 9b.</p>')
uso = pd.read_sql("""SELECT relname AS tabla, indexrelname AS indice, idx_scan AS veces_usado,
                     pg_size_pretty(pg_relation_size(indexrelid)) AS tamano FROM pg_stat_user_indexes
                     WHERE indexrelname IN ('idx_deliveries_trip_id','idx_maintenance_vehicle_cost','idx_trips_vehicle_completed',
                     'idx_trips_status','idx_drivers_license_expiry') ORDER BY indice""", engine)
s.append('<h3>Uso real de los índices (pg_stat_user_indexes)</h3>' + tabla(uso, enteros=['veces_usado'])
         + '<p>Los 5 índices fueron usados por el planificador: ninguno es espacio desperdiciado.</p>')
concl = celda(44).replace('## 3. Conclusiones del Avance 2', '## Conclusiones')
concl = concl.replace('baja más de un **50%** (ver la fila TOTAL de la tabla)', 'baja un **74,6%** (5.401 → 1.372 ms)')
s.append(md(concl))
a_pdf('Manual_Consultas_SQL.pdf', 'Manual de Consultas SQL', ''.join(s))

# ---------------------------------------------------------------- Arquitectura_Tecnica.pdf
nb4 = nbformat.read(os.path.join(RAIZ, '1. Notebooks', 'Avance_4_CloudArchitecture.ipynb'), 4)
c4 = lambda i: nb4.cells[i].source
a = []
a.append('<h1>Arquitectura Técnica en AWS</h1><div class="sub">Proyecto Integrador M2 - FleetLogix<br>Tomás Babot<br><br>'
         'Scripts: <code>2. Scripts/06_aws_setup.py</code>, <code>2. Scripts/lambda_functions/</code>. '
         'La simulación está en <code>1. Notebooks/Avance_4_CloudArchitecture.ipynb</code>.</div>')
a.append('<p>El objetivo de este avance es <b>entender, documentar y justificar</b> la arquitectura. Para comprobar que el código funciona sin gastar '
         'plata ni crear recursos reales, ejecuté todo contra un AWS simulado en memoria (librería <code>moto</code>): '
         'las llamadas de <code>boto3</code> son las mismas que en AWS real.</p>')
a.append('<h2>1. Diagrama de la arquitectura</h2><img src="../2.%20Scripts/aws_architecture_diagram.png">')
a.append(md(c4(3)))
a.append('<div class="salto"></div>' + md(c4(4)))
a.append(md(c4(5)))
a.append(md(c4(6)))

sim = """## 5. Resultados de la simulación

**Infraestructura creada por `06_aws_setup.py`:**

| Control | Resultado |
|---|---|
| RDS PostgreSQL 16.4 | no pública, almacenamiento cifrado, backups 7 días, snapshot inicial |
| S3 `fleetlogix-data` | cifrado AES256, acceso público bloqueado, versionado, carpetas `raw-data/`, `processed-data/`, `backups/`, `logs/` |
| DynamoDB | 4 tablas on-demand: `deliveries_status`, `vehicle_tracking`, `routes_waypoints`, `alerts_history` |
| SNS | tópico `fleetlogix-alerts` con el mail del supervisor |
| IAM | rol `FleetLogixLambdaRole`: `AWSLambdaBasicExecutionRole` (logs) + política propia `FleetLogixMinimo` |

**Política de menor privilegio del rol de las Lambda:**

| Permiso | Acciones | Recursos |
|---|---|---|
| LeerEntregasYRutas | `dynamodb:GetItem` | `deliveries_status`, `routes_waypoints` |
| GuardarGPSyAlertas | `dynamodb:PutItem` | `vehicle_tracking`, `alerts_history` |
| PublicarAlertas | `sns:Publish` | `fleetlogix-alerts` |

**Pruebas que hice con las 3 Lambda corregidas** (datos reales de PostgreSQL: 1.000 entregas y las 50 rutas, eventos con el formato de API Gateway):

| Lambda | Caso | Respuesta |
|---|---|---|
| verificar-entrega | entrega completada | **200**, `is_completed = true` |
| verificar-entrega | entrega pendiente | **200**, `is_completed = false` |
| verificar-entrega | entrega inexistente | **404** "Entrega no encontrada" |
| verificar-entrega | sin `delivery_id` | **400** "delivery_id es requerido" |
| calcular-eta | a mitad de Bogotá → Medellín, 60 km/h | **200**, faltan 119,3 km, llega en 119 min |
| calcular-eta | vehículo detenido | **200**, ETA "No disponible" |
| calcular-eta | falta el destino | **400** |
| alerta-desvio | a ~1 km de la ruta | **200**, sin alerta (umbral 5 km) |
| alerta-desvio | a ~25 km de la ruta | **200**, desvío de 27,75 km, **alerta enviada** |
| alerta-desvio | ruta inexistente | **404** |

La alerta **llegó de verdad**: una cola SQS suscripta al tópico SNS recibió el mensaje
"FleetLogix: desvío de ruta detectado" y quedó 1 registro en `alerts_history`.

**Las mismas pruebas con el código original:**

| Prueba | Respuesta | Causa |
|---|---|---|
| verificar - evento de API Gateway | **400** | busca `delivery_id` en el evento, pero llega dentro de `body` como texto |
| verificar - evento directo (consola) | 200 | única forma en que funcionaba |
| calcular ETA | **500** | DynamoDB no acepta `float` |
| alerta desvío | **500** | resta `Decimal` (de DynamoDB) con `float` |

**Distancia:** Haversine contra la aproximación de 111 km por grado: Bogotá → Medellín 238,7 vs 238,8 km;
Bogotá → Barranquilla 699,8 vs 698,7 km; Cali → Cartagena 780,3 vs 779,1 km. Cerca del ecuador el error es menor a 0,2%,
pero usé Haversine porque es exacta a cualquier latitud y no cuesta más.
"""
a.append('<div class="salto"></div>' + md(sim))

alarmas = """## 6. Monitoreo, seguridad y costos
### 6.1 Alarmas de CloudWatch
Las 8 alarmas avisan al mismo tópico SNS y usan métricas que AWS publica solo (sin código extra).

| Alarma | Métrica | Condición (5 min) | Por qué |
|---|---|---|---|
| fleetlogix-lambda-verificar-errores | AWS/Lambda · Errors | suma > 5 | la app no puede confirmar entregas |
| fleetlogix-lambda-eta-errores | AWS/Lambda · Errors | suma > 5 | clientes sin hora de llegada |
| fleetlogix-lambda-desvio-errores | AWS/Lambda · Errors | suma > 5 | desvíos que no se detectan |
| fleetlogix-lambda-desvio-duracion | AWS/Lambda · Duration | promedio > 2.000 ms | respuesta lenta y más costo |
| fleetlogix-api-errores-5xx | AWS/ApiGateway · 5xx | suma > 10 | la API falla para los conductores |
| fleetlogix-rds-cpu-alta | AWS/RDS · CPUUtilization | promedio > 80% | base saturada: evaluar un tamaño mayor |
| fleetlogix-rds-poco-espacio | AWS/RDS · FreeStorageSpace | promedio < 2 GB | queda poco disco |
| fleetlogix-dynamodb-throttling | AWS/DynamoDB · ThrottledRequests | suma > 0 | pedidos rechazados por exceso de carga |
"""
a.append(md(alarmas) + md(c4(29)) + md(c4(30)) + md(c4(31)))

costos = pd.DataFrame([
    ('RDS PostgreSQL db.t3.micro (Single-AZ)', 13.14, 'US$ 0,018 por hora'),
    ('RDS almacenamiento gp3 20 GB', 2.30, 'US$ 0,115 por GB; backups hasta 20 GB sin cargo'),
    ('EC2 t4g.micro (ETL + bastion)', 6.13, 'US$ 0,0084 por hora'),
    ('EC2 disco EBS gp3 8 GB', 0.64, 'US$ 0,08 por GB'),
    ('IP pública IPv4 de la EC2', 3.65, 'US$ 0,005 por hora'),
    ('API Gateway (HTTP API)', 5.23, '5,23 M pedidos × US$ 1 por millón'),
    ('Lambda: pedidos', 0.85, '1 M gratis por mes; luego US$ 0,20 por millón'),
    ('Lambda: cómputo', 0.00, '98.128 GB-s (400.000 gratis por mes)'),
    ('DynamoDB escrituras on-demand', 0.56, 'US$ 0,625 por millón'),
    ('DynamoDB lecturas on-demand', 0.55, 'US$ 0,125 por millón'),
    ('DynamoDB almacenamiento', 0.00, '< 1 GB con TTL de 90 días (25 GB gratis)'),
    ('S3 (10 GB + pedidos)', 0.28, 'US$ 0,023 por GB'),
    ('CloudWatch Logs (~2,6 GB)', 1.30, 'US$ 0,50 por GB ingerido; 8 alarmas dentro de la capa gratuita'),
    ('Secrets Manager (1 secreto)', 0.40, 'US$ 0,40 por secreto'),
    ('SNS (alertas por mail)', 0.00, 'primeros 1.000 mails gratis'),
    ('Transferencia de datos', 0.00, 'primeros 100 GB de salida gratis'),
    ('TOTAL', 35.03, 'margen contra el tope de US$ 50: US$ 14,97'),
], columns=['servicio', 'US$ por mes', 'cálculo'])
assert abs(costos['US$ por mes'][:-1].sum() - 35.03) < 0.02
a.append(tabla(costos, decimales=['US$ por mes']) + '<img src="img/costos_aws.png">' + md(c4(34)))
a.append(md(c4(36).replace('## 7. Conclusiones del Avance 4', '## 7. Conclusiones')))
a_pdf('Arquitectura_Tecnica.pdf', 'Arquitectura Técnica AWS', ''.join(a))
