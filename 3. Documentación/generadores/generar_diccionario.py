"""
Genera 3. Documentación/data_dictionary.xlsx: el diccionario de datos de las dos capas.

Hojas: Indice (tablas, filas y columnas), PostgreSQL (modelo transaccional), Snowflake_DW (modelo estrella)
y Valores_permitidos. Los tipos, claves, conteos y ejemplos se leen de las bases; las descripciones
están escritas acá abajo.

Requisitos: PostgreSQL cargado, el modelo de Snowflake cargado por el ETL y el archivo .env
(usa la misma conexión que 05_etl_pipeline.py).
Uso:  python "3. Documentación/generadores/generar_diccionario.py"
"""
import importlib.util, warnings
from pathlib import Path
import pandas as pd, psycopg2, snowflake.connector
from openpyxl import load_workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
warnings.filterwarnings('ignore')

RAIZ = str(Path(__file__).resolve().parents[2])
# Reutilizo la configuración de conexión del ETL (lee el .env)
spec = importlib.util.spec_from_file_location('etl', f'{RAIZ}/2. Scripts/05_etl_pipeline.py')
etl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(etl)
import logging; logging.disable(logging.CRITICAL)

pg = psycopg2.connect(**etl.POSTGRES_CONFIG)
sf = snowflake.connector.connect(**etl.SNOWFLAKE_CONFIG)

def sfq(sql):
    c = sf.cursor(); c.execute(sql)
    return pd.DataFrame(c.fetchall(), columns=[d[0].lower() for d in c.description])

# ---------------- Descripciones PostgreSQL ----------------
PG = {
 'vehicles': ('Flota de vehículos de la empresa (maestra)', {
   'vehicle_id': 'Identificador único del vehículo', 'license_plate': 'Patente (placa) colombiana, formato AAA123',
   'vehicle_type': 'Tipo: Camión Grande, Camión Mediano, Van, Motocicleta', 'capacity_kg': 'Capacidad máxima de carga en kg',
   'fuel_type': 'Combustible: diesel o gasolina', 'acquisition_date': 'Fecha de compra del vehículo',
   'status': 'Estado: active, maintenance'}),
 'drivers': ('Conductores empleados (maestra)', {
   'driver_id': 'Identificador único del conductor', 'employee_code': 'Código interno de empleado (EMP0001…)',
   'first_name': 'Nombre', 'last_name': 'Apellido', 'license_number': 'Número de licencia de conducción',
   'license_expiry': 'Vencimiento de la licencia', 'phone': 'Teléfono de contacto', 'hire_date': 'Fecha de contratación',
   'status': 'Estado: active, inactive'}),
 'routes': ('Rutas predefinidas entre 5 ciudades (maestra)', {
   'route_id': 'Identificador único de la ruta', 'route_code': 'Código de ruta (R001…R050)',
   'origin_city': 'Ciudad de origen', 'destination_city': 'Ciudad de destino', 'distance_km': 'Distancia por carretera en km',
   'estimated_duration_hours': 'Duración estimada del recorrido en horas', 'toll_cost': 'Costo total de peajes en COP'}),
 'trips': ('Viajes realizados (transaccional, tabla central)', {
   'trip_id': 'Identificador único del viaje', 'vehicle_id': 'Vehículo usado (FK → vehicles)', 'driver_id': 'Conductor (FK → drivers)',
   'route_id': 'Ruta recorrida (FK → routes)', 'departure_datetime': 'Fecha y hora de salida',
   'arrival_datetime': 'Fecha y hora de llegada (NULL mientras está en curso)', 'fuel_consumed_liters': 'Litros de combustible consumidos en el viaje',
   'total_weight_kg': 'Peso total cargado (40-90% de la capacidad)', 'status': 'Estado: in_progress, completed'}),
 'deliveries': ('Entregas individuales de cada viaje (transaccional)', {
   'delivery_id': 'Identificador único de la entrega', 'trip_id': 'Viaje al que pertenece (FK → trips)',
   'tracking_number': 'Número de seguimiento para el cliente (único)', 'customer_name': 'Nombre del cliente que recibe',
   'delivery_address': 'Dirección de entrega en la ciudad destino', 'package_weight_kg': 'Peso del paquete en kg',
   'scheduled_datetime': 'Fecha y hora programada de entrega', 'delivered_datetime': 'Fecha y hora real de entrega (NULL si está pendiente)',
   'delivery_status': 'Estado: delivered, pending', 'recipient_signature': 'TRUE si el cliente firmó la recepción'}),
 'maintenance': ('Historial de mantenimiento de vehículos (transaccional)', {
   'maintenance_id': 'Identificador único del mantenimiento', 'vehicle_id': 'Vehículo atendido (FK → vehicles)',
   'maintenance_date': 'Fecha del servicio', 'maintenance_type': 'Tipo: cambio de aceite, frenos, llantas, motor, alineación, general',
   'description': 'Detalle del trabajo realizado', 'cost': 'Costo del servicio en COP',
   'next_maintenance_date': 'Fecha sugerida del próximo servicio', 'performed_by': 'Taller que realizó el servicio'}),
}
cols = pd.read_sql("""
  SELECT c.table_name, c.ordinal_position, c.column_name, c.data_type, c.character_maximum_length AS largo,
         c.numeric_precision AS prec, c.numeric_scale AS esc, c.is_nullable,
         (SELECT string_agg(tc.constraint_type, ', ') FROM information_schema.key_column_usage k
            JOIN information_schema.table_constraints tc ON tc.constraint_name = k.constraint_name
           WHERE k.table_name = c.table_name AND k.column_name = c.column_name) AS restricciones,
         (SELECT ccu.table_name || '.' || ccu.column_name FROM information_schema.key_column_usage k
            JOIN information_schema.table_constraints tc ON tc.constraint_name = k.constraint_name AND tc.constraint_type = 'FOREIGN KEY'
            JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name
           WHERE k.table_name = c.table_name AND k.column_name = c.column_name LIMIT 1) AS referencia
  FROM information_schema.columns c WHERE c.table_schema = 'public'
  ORDER BY CASE c.table_name WHEN 'vehicles' THEN 1 WHEN 'drivers' THEN 2 WHEN 'routes' THEN 3 WHEN 'trips' THEN 4 WHEN 'deliveries' THEN 5 ELSE 6 END, c.ordinal_position
""", pg)

def tipo_pg(r):
    t = {'character varying': 'VARCHAR', 'timestamp without time zone': 'TIMESTAMP', 'integer': 'INTEGER'}.get(r.data_type, r.data_type.upper())
    if r.data_type == 'character varying': t += f'({int(r.largo)})'
    if r.data_type == 'numeric': t = f'DECIMAL({int(r.prec)},{int(r.esc)})'
    return t

ejemplos = {}
for t in PG:
    fila = pd.read_sql(f"SELECT * FROM {t} WHERE {'delivered_datetime IS NOT NULL' if t == 'deliveries' else 'TRUE'} ORDER BY 1 LIMIT 1", pg).iloc[0]
    ejemplos[t] = {k: ('' if pd.isna(v) else str(v)[:60]) for k, v in fila.items()}
conteos = {t: pd.read_sql(f'SELECT COUNT(*) n FROM {t}', pg)['n'][0] for t in PG}

pg_dict = pd.DataFrame([{
    'tabla': r.table_name, 'columna': r.column_name, 'tipo': tipo_pg(r), 'nulos': 'Sí' if r.is_nullable == 'YES' else 'No',
    'clave / restricción': (r.restricciones or '') + (f' → {r.referencia}' if r.referencia else ''),
    'descripción': PG[r.table_name][1].get(r.column_name, ''), 'ejemplo': ejemplos[r.table_name].get(r.column_name, '')}
    for r in cols.itertuples()])

# ---------------- Descripciones Snowflake ----------------
DW_TABLAS = {
 'dim_date': ('Dimensión calendario 2024-2027 (una fila por día)', 'Generada por el ETL'),
 'dim_time': ('Dimensión horaria (una fila por minuto del día)', 'Generada por el ETL'),
 'dim_vehicle': ('Vehículos (SCD tipo 1: estado actual)', 'vehicles + maintenance'),
 'dim_driver': ('Conductores con historial (SCD tipo 2)', 'drivers + trips/deliveries (últimos 90 días)'),
 'dim_route': ('Rutas con clasificación de dificultad', 'routes'),
 'dim_customer': ('Clientes (nombre + ciudad de entrega)', 'deliveries + routes'),
 'fact_deliveries': ('Hechos: una fila por entrega completada', 'deliveries + trips + routes'),
 'agg_daily_totals': ('Totales pre-calculados por día', 'fact_deliveries'),
}
DW = {
 'date_key': 'Clave de fecha AAAAMMDD', 'full_date': 'Fecha', 'day_of_week': 'Día de la semana (1 = lunes … 7 = domingo)', 'day_name': 'Nombre del día',
 'day_of_month': 'Día del mes', 'day_of_year': 'Día del año', 'week_of_year': 'Semana ISO del año', 'month_num': 'Mes (1-12)', 'month_name': 'Nombre del mes',
 'quarter': 'Trimestre', 'year': 'Año', 'is_weekend': 'TRUE si es sábado o domingo', 'is_holiday': 'TRUE si es feriado nacional de fecha fija',
 'holiday_name': 'Nombre del feriado', 'fiscal_quarter': 'Trimestre fiscal (igual al calendario)', 'fiscal_year': 'Año fiscal',
 'time_key': 'Clave de hora HHMM', 'hour': 'Hora (0-23)', 'minute': 'Minuto', 'second': 'Segundo (siempre 0)', 'time_of_day': 'Madrugada, Mañana, Tarde o Noche',
 'hour_24': 'Hora formato 24 h', 'hour_12': 'Hora formato 12 h', 'am_pm': 'AM o PM', 'is_business_hour': 'TRUE entre 08:00 y 18:00',
 'shift': 'Turno: T1 06-14, T2 14-22, T3 22-06',
 'vehicle_key': 'Clave sustituta del vehículo', 'vehicle_id': 'ID del vehículo en el origen', 'license_plate': 'Patente', 'vehicle_type': 'Tipo de vehículo',
 'capacity_kg': 'Capacidad en kg', 'fuel_type': 'Combustible', 'acquisition_date': 'Fecha de compra', 'age_months': 'Antigüedad en meses al momento de la carga',
 'status': 'Estado actual', 'last_maintenance_date': 'Fecha del último mantenimiento', 'valid_from': 'Inicio de vigencia de la versión',
 'valid_to': 'Fin de vigencia (9999-12-31 = vigente)', 'is_current': 'TRUE si es la versión vigente',
 'driver_key': 'Clave sustituta del conductor (una por versión)', 'driver_id': 'ID del conductor en el origen', 'employee_code': 'Código de empleado',
 'full_name': 'Nombre y apellido', 'license_number': 'Número de licencia', 'license_expiry': 'Vencimiento de licencia', 'phone': 'Teléfono', 'hire_date': 'Fecha de contratación',
 'experience_months': 'Meses en la empresa', 'performance_category': 'Alto (≥90% a tiempo), Medio (≥82%), Bajo o Sin datos, según los últimos 90 días',
 'zone': 'Ciudad donde más entregó en los últimos 90 días (cambio → nueva versión SCD2)',
 'route_key': 'Clave sustituta de la ruta', 'route_id': 'ID de la ruta en el origen', 'route_code': 'Código de ruta', 'origin_city': 'Ciudad de origen',
 'destination_city': 'Ciudad de destino', 'distance_km': 'Distancia en km', 'estimated_duration_hours': 'Duración estimada en horas', 'toll_cost': 'Peajes en COP',
 'difficulty_level': 'Fácil (< 300 km), Medio (< 700 km), Difícil', 'route_type': 'Regional (< 200 km) o Interurbana',
 'customer_key': 'Clave sustituta del cliente', 'customer_id': 'Identificador autoincremental', 'customer_name': 'Nombre del cliente',
 'customer_type': 'Individual / Empresa / Gobierno (asignado de forma sintética y estable: el origen no lo registra)', 'city': 'Ciudad de entrega',
 'first_delivery_date': 'Primera entrega registrada', 'total_deliveries': 'Entregas en la carga inicial', 'customer_category': 'Premium (≥3 entregas), Regular (2), Ocasional (1)',
 'delivery_key': 'Clave sustituta del hecho (autoincremental)', 'scheduled_time_key': 'Hora programada (FK → dim_time)', 'delivered_time_key': 'Hora real de entrega (FK → dim_time)',
 'delivery_id': 'ID de la entrega en el origen (dimensión degenerada)', 'trip_id': 'ID del viaje en el origen', 'tracking_number': 'Número de seguimiento',
 'package_weight_kg': 'Peso del paquete en kg',
 'fuel_consumed_liters': 'Litros del viaje ÷ entregas del viaje (aditivo)', 'delivery_time_minutes': 'Minutos desde la salida del viaje hasta la entrega',
 'delay_minutes': 'Minutos de demora respecto de lo programado (0 si llegó antes)', 'deliveries_per_hour': 'Entregas del viaje ÷ horas de viaje',
 'fuel_efficiency_km_per_liter': 'Km de la ruta ÷ litros del viaje', 'cost_per_delivery': '(litros × precio del combustible + peajes × factor del vehículo + horas × 14.000) ÷ entregas del viaje, en COP',
 'revenue_per_delivery': '20.000 + kg × (150 + 0,55 × km de la ruta), en COP', 'is_on_time': 'TRUE si la demora es ≤ 30 minutos', 'is_damaged': 'Paquete dañado (el origen no lo registra: FALSE)',
 'has_signature': 'TRUE si el cliente firmó', 'delivery_status': 'Estado (siempre delivered)', 'etl_batch_id': 'Corrida del ETL que cargó la fila',
 'etl_timestamp': 'Momento de la carga',
 'summary_date': 'Día resumido', 'total_deliveries_agg': 'Entregas del día', 'on_time_deliveries': 'Entregas a tiempo del día', 'on_time_pct': '% a tiempo del día',
 'avg_delay_minutes': 'Demora promedio del día', 'total_weight_kg': 'Peso total del día', 'total_fuel_liters': 'Litros del día', 'total_revenue': 'Ingresos del día en COP',
 'created_at': 'Momento del cálculo',
}
TABLE_SPECIFIC = {('fact_deliveries', 'distance_km'): 'Km de la ruta ÷ entregas del viaje (aditivo)', ('agg_daily_totals', 'total_deliveries'): 'Entregas del día'}
dw_cols = sfq("""SELECT LOWER(table_name) AS tabla, LOWER(column_name) AS columna, data_type, character_maximum_length AS largo,
                 numeric_precision AS prec, numeric_scale AS esc, is_nullable, ordinal_position
                 FROM information_schema.columns WHERE table_schema = 'ANALYTICS' ORDER BY table_name, ordinal_position""")
dw_cols = dw_cols[dw_cols.tabla.isin(DW_TABLAS)]
orden = list(DW_TABLAS)
dw_cols['o'] = dw_cols.tabla.map(orden.index); dw_cols = dw_cols.sort_values(['o', 'ordinal_position'])
def tipo_sf(r):
    if r.data_type == 'TEXT': return f'VARCHAR({int(r.largo)})'
    if r.data_type == 'NUMBER': return 'INT' if int(r.esc) == 0 and int(r.prec) == 38 else f'DECIMAL({int(r.prec)},{int(r.esc)})'
    return r.data_type
claves = {'fact_deliveries': {'delivery_key': 'PK', 'date_key': 'FK → dim_date', 'scheduled_time_key': 'FK → dim_time', 'delivered_time_key': 'FK → dim_time',
          'vehicle_key': 'FK → dim_vehicle', 'driver_key': 'FK → dim_driver', 'route_key': 'FK → dim_route', 'customer_key': 'FK → dim_customer'},
          'dim_date': {'date_key': 'PK'}, 'dim_time': {'time_key': 'PK'}, 'dim_vehicle': {'vehicle_key': 'PK'}, 'dim_driver': {'driver_key': 'PK'},
          'dim_route': {'route_key': 'PK'}, 'dim_customer': {'customer_key': 'PK'}}
dw_ej = {}
for t in DW_TABLAS:
    f = sfq(f'SELECT * FROM {t} ORDER BY 1 LIMIT 1').iloc[0]
    dw_ej[t] = {k: ('' if pd.isna(v) else str(v)[:60]) for k, v in f.items()}
dw_n = {t: int(sfq(f'SELECT COUNT(*) n FROM {t}')['n'][0]) for t in DW_TABLAS}
dw_dict = pd.DataFrame([{
    'tabla': r.tabla, 'columna': r.columna, 'tipo': tipo_sf(r), 'clave': claves.get(r.tabla, {}).get(r.columna, ''),
    'descripción': TABLE_SPECIFIC.get((r.tabla, r.columna), DW.get(r.columna, '')), 'ejemplo': dw_ej[r.tabla].get(r.columna, '')}
    for r in dw_cols.itertuples()])
assert (dw_dict['descripción'] == '').sum() == 0, dw_dict[dw_dict['descripción'] == '']

# ---------------- Índice ----------------
indice = pd.DataFrame(
    [{'capa': 'PostgreSQL (OLTP)', 'tabla': t, 'descripción': d, 'filas': conteos[t], 'columnas': (pg_dict.tabla == t).sum()} for t, (d, _) in PG.items()] +
    [{'capa': 'Snowflake DW', 'tabla': t, 'descripción': f'{d}. Origen: {o}', 'filas': dw_n[t], 'columnas': (dw_dict.tabla == t).sum()} for t, (d, o) in DW_TABLAS.items()])

valores = pd.DataFrame([
    ('vehicles.vehicle_type', 'Camión Grande', 'capacidad 5.000 kg, diesel'), ('vehicles.vehicle_type', 'Camión Mediano', 'capacidad 3.000 kg, diesel'),
    ('vehicles.vehicle_type', 'Van', 'capacidad 1.500 kg, gasolina'), ('vehicles.vehicle_type', 'Motocicleta', 'capacidad 50 kg, gasolina'),
    ('vehicles.status', 'active / maintenance', ''), ('drivers.status', 'active / inactive', ''),
    ('trips.status', 'completed / in_progress', 'in_progress → arrival_datetime NULL'), ('deliveries.delivery_status', 'delivered / pending', 'pending → delivered_datetime NULL'),
    ('routes.origin_city / destination_city', 'Bogotá, Medellín, Cali, Barranquilla, Cartagena', ''),
    ('maintenance.maintenance_type', 'Cambio de aceite, Revisión de frenos, Cambio de llantas, Revisión de motor, Alineación y balanceo, Mantenimiento general', ''),
    ('dim_time.shift', 'Turno 1 (06-14), Turno 2 (14-22), Turno 3 (22-06)', ''), ('dim_route.difficulty_level', 'Fácil / Medio / Difícil', 'según distancia'),
    ('dim_customer.customer_type', 'Individual / Empresa / Gobierno', '80% / 15% / 5% sintético'), ('dim_driver.performance_category', 'Alto / Medio / Bajo / Sin datos', 'puntualidad 90 días'),
], columns=['campo', 'valores', 'nota'])

ruta = f'{RAIZ}/3. Documentación/data_dictionary.xlsx'
with pd.ExcelWriter(ruta, engine='openpyxl') as w:
    indice.to_excel(w, sheet_name='Indice', index=False)
    pg_dict.to_excel(w, sheet_name='PostgreSQL', index=False)
    dw_dict.to_excel(w, sheet_name='Snowflake_DW', index=False)
    valores.to_excel(w, sheet_name='Valores_permitidos', index=False)

wb = load_workbook(ruta)
borde = Border(bottom=Side(style='thin', color='BBBBBB'))
anchos = {'tabla': 18, 'columna': 26, 'tipo': 16, 'nulos': 7, 'clave / restricción': 30, 'clave': 18, 'descripción': 70, 'ejemplo': 28,
          'capa': 18, 'filas': 10, 'columnas': 10, 'campo': 36, 'valores': 70, 'nota': 34}
for ws in wb.worksheets:
    for cel in ws[1]:
        cel.font = Font(name='Arial', bold=True, color='FFFFFF'); cel.fill = PatternFill('solid', fgColor='2F5597')
        cel.alignment = Alignment(vertical='center')
        ws.column_dimensions[cel.column_letter].width = anchos.get(cel.value, 15)
    for fila in ws.iter_rows(min_row=2):
        for cel in fila:
            cel.font = Font(name='Arial', size=10); cel.alignment = Alignment(wrap_text=True, vertical='top'); cel.border = borde
    ws.freeze_panes = 'A2'; ws.auto_filter.ref = ws.dimensions
for c in wb['Indice']['D'][1:]: c.number_format = '#,##0'
wb.save(ruta)
print(indice.to_string()); print(len(pg_dict), len(dw_dict))
