"""
FleetLogix - Pipeline ETL automático
Extrae de PostgreSQL, transforma con pandas y carga en el Data Warehouse de Snowflake.

Modos de uso (desde la carpeta "2. Scripts"):
    python 05_etl_pipeline.py --full                 # carga inicial: toda la historia
    python 05_etl_pipeline.py                        # carga incremental: entregas de AYER
    python 05_etl_pipeline.py --fecha 2026-11-16     # carga incremental de un día puntual
    python 05_etl_pipeline.py --schedule             # queda corriendo y ejecuta todos los días a las 02:00

Alternativa con cron (Mac/Linux), en lugar de --schedule:
    0 2 * * * cd "/ruta/al/proyecto/2. Scripts" && python 05_etl_pipeline.py >> etl_cron.log 2>&1

Credenciales: se leen del archivo .env de la raíz del proyecto (ver .env.example).
"""

import argparse
import json
import logging
import os
import time
import warnings
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import psycopg2
import schedule
import snowflake.connector
from snowflake.connector.pandas_tools import write_pandas

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler(os.path.join(os.path.dirname(os.path.abspath(__file__)), 'etl_pipeline.log')),
              logging.StreamHandler()]
)
# Sin los avisos internos del conector de Snowflake (proxy, región de AWS): no son errores y llenaban el log
logging.getLogger('snowflake').setLevel(logging.ERROR)
# pandas avisa que solo prueba read_sql con SQLAlchemy; con psycopg2 funciona bien y así se evita otra dependencia
warnings.filterwarnings('ignore', message='pandas only supports SQLAlchemy')

POSTGRES_CONFIG = {
    'host': os.getenv('PGHOST', 'localhost'),
    'database': os.getenv('PGDATABASE', 'fleetlogix'),
    'user': os.getenv('PGUSER', os.getenv('USER', 'postgres')),
    'password': os.getenv('PGPASSWORD', ''),
    'port': int(os.getenv('PGPORT', 5432)),
}

SNOWFLAKE_CONFIG = {
    'account': os.getenv('SNOWFLAKE_ACCOUNT'),
    'user': os.getenv('SNOWFLAKE_USER'),
    'warehouse': os.getenv('SNOWFLAKE_WAREHOUSE', 'FLEETLOGIX_WH'),
    'database': os.getenv('SNOWFLAKE_DATABASE', 'FLEETLOGIX_DW'),
    'schema': os.getenv('SNOWFLAKE_SCHEMA', 'ANALYTICS'),
    'role': os.getenv('SNOWFLAKE_ROLE', 'ACCOUNTADMIN'),
    # Al cerrar la sesión, esperar las consultas que sigan corriendo (el conector pide decirlo explícito)
    'enable_server_session_keep_alive_auto_detection': True,
}
# Autenticación: con par de llaves (recomendado, evita la verificación en dos pasos)
# o, si no hay llave configurada, con contraseña.
_llave = os.getenv('SNOWFLAKE_PRIVATE_KEY_FILE')
if _llave:
    _raiz = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    SNOWFLAKE_CONFIG['private_key_file'] = _llave if os.path.isabs(_llave) else os.path.join(_raiz, _llave)
else:
    SNOWFLAKE_CONFIG['password'] = os.getenv('SNOWFLAKE_PASSWORD')

# Supuestos de negocio, en pesos colombianos (COP). El script base usaba un solo precio de
# combustible (5.000) y cobraba igual 1 kg a 100 km que a 1.000 km: los ajusté a valores reales.
PRECIO_LITRO = {'diesel': 2900, 'gasolina': 4200}        # ACPM y gasolina en Colombia, 2025-2026
FACTOR_PEAJE = {'Motocicleta': 0, 'Van': 1, 'Camión Mediano': 2, 'Camión Grande': 3}  # las motos no pagan peaje
COSTO_HORA_CONDUCTOR = 14000                              # salario + prestaciones por hora de viaje
INGRESO_BASE_ENTREGA = 20000
TARIFA_KG = 150                                           # por kg, más
TARIFA_KG_KM = 0.55                                       # por kg y por km de la ruta
MINUTOS_TOLERANCIA = 30          # una entrega es "a tiempo" si llega hasta 30 min tarde

# Feriados nacionales de fecha fija en Colombia (los móviles no se incluyen, simplificación)
FERIADOS_FIJOS = {
    (1, 1): 'Año Nuevo', (5, 1): 'Día del Trabajo', (7, 20): 'Día de la Independencia',
    (8, 7): 'Batalla de Boyacá', (12, 8): 'Inmaculada Concepción', (12, 25): 'Navidad',
}


class FleetLogixETL:
    def __init__(self):
        self.pg_conn = None
        self.sf_conn = None
        self.batch_id = int(datetime.now().timestamp())
        self.metrics = {'records_extracted': 0, 'records_rejected': 0,
                        'records_transformed': 0, 'records_loaded': 0, 'errors': 0}

    # ------------------------------------------------------------------
    # Conexiones
    # ------------------------------------------------------------------
    def connect_databases(self):
        try:
            self.pg_conn = psycopg2.connect(**POSTGRES_CONFIG)
            logging.info("Conectado a PostgreSQL")
            self.sf_conn = snowflake.connector.connect(**SNOWFLAKE_CONFIG)
            logging.info("Conectado a Snowflake")
            return True
        except Exception as e:
            logging.error(f"Error en conexión: {e}")
            self.metrics['errors'] += 1
            return False

    def close_connections(self):
        if self.pg_conn:
            self.pg_conn.close()
        if self.sf_conn:
            self.sf_conn.close()
        logging.info("Conexiones cerradas")

    def _sf(self, sql, params=None):
        """Ejecuta una sentencia en Snowflake y devuelve las filas."""
        cur = self.sf_conn.cursor()
        try:
            cur.execute(sql, params)
            return cur.fetchall()
        finally:
            cur.close()

    def _write(self, df, tabla):
        """Sube un DataFrame a una tabla de Snowflake (write_pandas usa archivos Parquet + COPY,
        mucho más rápido que insertar fila por fila)."""
        df = df.reset_index(drop=True)          # write_pandas no sube el índice y avisa si no es 0..n-1
        df.columns = [c.upper() for c in df.columns]
        ok, _, nrows, _ = write_pandas(self.sf_conn, df, tabla.upper(),
                                       quote_identifiers=False, use_logical_type=True)
        if not ok:
            raise RuntimeError(f"write_pandas falló en {tabla}")
        return nrows

    # ------------------------------------------------------------------
    # EXTRACT
    # ------------------------------------------------------------------
    def extract_deliveries(self, desde, hasta) -> pd.DataFrame:
        """Entregas COMPLETADAS cuyo horario programado está en [desde, hasta),
        con los datos de su viaje, ruta, vehículo y conductor."""
        logging.info(f"Extrayendo entregas desde {desde} hasta {hasta}...")
        query = """
            SELECT d.delivery_id, d.trip_id, d.tracking_number, d.customer_name,
                   d.package_weight_kg, d.scheduled_datetime, d.delivered_datetime,
                   d.delivery_status, d.recipient_signature,
                   t.vehicle_id, t.driver_id, t.route_id,
                   t.departure_datetime, t.arrival_datetime,
                   t.fuel_consumed_liters, t.total_weight_kg,
                   v.vehicle_type, v.fuel_type,
                   r.distance_km, r.toll_cost, r.origin_city, r.destination_city,
                   (SELECT COUNT(*) FROM deliveries d2 WHERE d2.trip_id = d.trip_id) AS deliveries_in_trip
            FROM deliveries d
            JOIN trips  t ON d.trip_id  = t.trip_id
            JOIN routes r ON t.route_id = r.route_id
            JOIN vehicles v ON t.vehicle_id = v.vehicle_id
            WHERE d.delivery_status = 'delivered'
              AND d.scheduled_datetime >= %s
              AND d.scheduled_datetime <  %s
        """
        df = pd.read_sql(query, self.pg_conn, params=(desde, hasta))
        self.metrics['records_extracted'] = len(df)
        logging.info(f"Extraídas {len(df):,} entregas")
        return df

    def extract_masters(self):
        """Tablas maestras para las dimensiones (son chicas, se traen completas)."""
        vehicles = pd.read_sql("""
            SELECT v.*, (SELECT MAX(m.maintenance_date) FROM maintenance m
                         WHERE m.vehicle_id = v.vehicle_id) AS last_maintenance_date
            FROM vehicles v
        """, self.pg_conn)
        # Desempeño y zona de cada conductor en los últimos 90 días
        drivers = pd.read_sql("""
            WITH ult AS (
                SELECT t.driver_id, r.destination_city,
                       (d.delivered_datetime <= d.scheduled_datetime + INTERVAL '30 minutes') AS a_tiempo
                FROM trips t
                JOIN routes r ON r.route_id = t.route_id
                JOIN deliveries d ON d.trip_id = t.trip_id
                WHERE d.delivery_status = 'delivered'
                  AND t.departure_datetime >= (SELECT MAX(departure_datetime) FROM trips) - INTERVAL '90 days'
            ),
            zona AS (
                SELECT driver_id, destination_city,
                       ROW_NUMBER() OVER (PARTITION BY driver_id ORDER BY COUNT(*) DESC, destination_city) AS rn
                FROM ult GROUP BY driver_id, destination_city
            )
            SELECT dr.*,
                   z.destination_city AS zone,
                   (SELECT ROUND(100.0 * AVG(CASE WHEN a_tiempo THEN 1 ELSE 0 END), 2)
                    FROM ult u WHERE u.driver_id = dr.driver_id) AS on_time_pct_90d
            FROM drivers dr
            LEFT JOIN zona z ON z.driver_id = dr.driver_id AND z.rn = 1
        """, self.pg_conn)
        routes = pd.read_sql("SELECT * FROM routes", self.pg_conn)
        return vehicles, drivers, routes

    # ------------------------------------------------------------------
    # TRANSFORM
    # ------------------------------------------------------------------
    def transform_facts(self, df: pd.DataFrame) -> pd.DataFrame:
        logging.info("Transformando entregas...")
        for c in ['scheduled_datetime', 'delivered_datetime', 'departure_datetime', 'arrival_datetime']:
            df[c] = pd.to_datetime(df[c])
        for c in ['package_weight_kg', 'fuel_consumed_liters', 'total_weight_kg', 'distance_km', 'toll_cost']:
            df[c] = df[c].astype(float)

        # Métricas de tiempo
        df['delivery_time_minutes'] = ((df['delivered_datetime'] - df['departure_datetime'])
                                       .dt.total_seconds() / 60).round()
        retraso = (df['delivered_datetime'] - df['scheduled_datetime']).dt.total_seconds() / 60
        df['delay_minutes'] = retraso.clip(lower=0).round()
        df['is_on_time'] = retraso <= MINUTOS_TOLERANCIA

        # Entregas por hora del viaje (productividad del conductor en ese viaje)
        horas_viaje = (df['arrival_datetime'] - df['departure_datetime']).dt.total_seconds() / 3600
        df['deliveries_per_hour'] = (df['deliveries_in_trip'] / horas_viaje).round(2)

        # Combustible y distancia son del VIAJE: se reparten entre sus entregas para que
        # al sumar la tabla de hechos no se cuenten varias veces (métrica aditiva)
        df['fuel_efficiency_km_per_liter'] = (df['distance_km'] / df['fuel_consumed_liters']).round(2)
        # Costo del viaje = combustible + peajes + horas del conductor; se reparte entre sus entregas
        costo_viaje = (df['fuel_consumed_liters'] * df['fuel_type'].map(PRECIO_LITRO)
                       + df['toll_cost'] * df['vehicle_type'].map(FACTOR_PEAJE)
                       + horas_viaje * COSTO_HORA_CONDUCTOR)
        df['cost_per_delivery'] = (costo_viaje / df['deliveries_in_trip']).round(2)
        # Ingreso: un cargo fijo más una tarifa por kg que crece con la distancia de la ruta
        df['revenue_per_delivery'] = (INGRESO_BASE_ENTREGA
                                      + df['package_weight_kg'] * (TARIFA_KG + TARIFA_KG_KM * df['distance_km'])).round(2)
        df['fuel_consumed_liters'] = (df['fuel_consumed_liters'] / df['deliveries_in_trip']).round(2)
        df['distance_km'] = (df['distance_km'] / df['deliveries_in_trip']).round(2)

        # Control de calidad: se descartan (y se registran) las filas imposibles
        antes = len(df)
        df = df[df['delivery_time_minutes'] >= 0]                                 # sin tiempos negativos
        df = df[(df['package_weight_kg'] > 0) & (df['package_weight_kg'] < 10000)]  # pesos en rango
        df = df[df['deliveries_per_hour'].between(0, 100)]                       # viajes con duración válida
        df = df.dropna(subset=['vehicle_id', 'driver_id', 'route_id', 'delivered_datetime'])
        self.metrics['records_rejected'] = antes - len(df)
        if antes - len(df):
            logging.warning(f"Calidad: {antes - len(df)} filas descartadas")

        # Claves de fecha y hora (formato YYYYMMDD y HHMM)
        df['date_key'] = df['scheduled_datetime'].dt.strftime('%Y%m%d').astype(int)
        df['scheduled_time_key'] = df['scheduled_datetime'].dt.hour * 100 + df['scheduled_datetime'].dt.minute
        df['delivered_time_key'] = df['delivered_datetime'].dt.hour * 100 + df['delivered_datetime'].dt.minute

        self.metrics['records_transformed'] = len(df)
        logging.info(f"Transformadas {len(df):,} entregas")
        return df

    @staticmethod
    def build_dim_date(inicio: date, fin: date) -> pd.DataFrame:
        dias = pd.date_range(inicio, fin, freq='D')
        nombres_dia = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
        nombres_mes = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio',
                       'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
        dim = pd.DataFrame({'full_date': dias.date})
        dim['date_key'] = dias.strftime('%Y%m%d').astype(int)
        dim['day_of_week'] = dias.dayofweek + 1                      # 1 = lunes ... 7 = domingo
        dim['day_name'] = [nombres_dia[d] for d in dias.dayofweek]
        dim['day_of_month'] = dias.day
        dim['day_of_year'] = dias.dayofyear
        dim['week_of_year'] = dias.isocalendar().week.values.astype(int)
        dim['month_num'] = dias.month
        dim['month_name'] = [nombres_mes[m - 1] for m in dias.month]
        dim['quarter'] = dias.quarter
        dim['year'] = dias.year
        dim['is_weekend'] = dias.dayofweek >= 5
        dim['holiday_name'] = [FERIADOS_FIJOS.get((d.month, d.day)) for d in dias]
        dim['is_holiday'] = dim['holiday_name'].notna()
        dim['fiscal_quarter'] = dim['quarter']                      # año fiscal = año calendario
        dim['fiscal_year'] = dim['year']
        return dim

    @staticmethod
    def build_dim_time() -> pd.DataFrame:
        """Una fila por minuto del día (1.440 filas). time_key = HHMM."""
        filas = []
        for h in range(24):
            for m in range(60):
                if h < 6:
                    momento, turno = 'Madrugada', 'Turno 3'
                elif h < 12:
                    momento, turno = 'Mañana', 'Turno 1'
                elif h < 18:
                    momento, turno = 'Tarde', 'Turno 2' if h >= 14 else 'Turno 1'
                else:
                    momento, turno = 'Noche', 'Turno 2' if h < 22 else 'Turno 3'
                filas.append({
                    'time_key': h * 100 + m, 'hour': h, 'minute': m, 'second': 0,
                    'time_of_day': momento,
                    'hour_24': f'{h:02d}:{m:02d}',
                    'hour_12': f'{(h % 12) or 12:02d}:{m:02d} {"AM" if h < 12 else "PM"}',
                    'am_pm': 'AM' if h < 12 else 'PM',
                    'is_business_hour': 8 <= h < 18,
                    'shift': turno,          # T1 06-14, T2 14-22, T3 22-06
                })
        return pd.DataFrame(filas)

    @staticmethod
    def build_dim_vehicle(vehicles: pd.DataFrame, hoy: date) -> pd.DataFrame:
        dim = vehicles.copy()
        adq = pd.to_datetime(dim['acquisition_date'])
        dim['age_months'] = ((pd.Timestamp(hoy) - adq).dt.days // 30).astype(int)
        dim['vehicle_key'] = dim['vehicle_id']
        dim['valid_from'] = dim['acquisition_date']
        dim['valid_to'] = date(9999, 12, 31)
        dim['is_current'] = True
        return dim[['vehicle_key', 'vehicle_id', 'license_plate', 'vehicle_type', 'capacity_kg',
                    'fuel_type', 'acquisition_date', 'age_months', 'status', 'last_maintenance_date',
                    'valid_from', 'valid_to', 'is_current']]

    @staticmethod
    def build_dim_route(routes: pd.DataFrame) -> pd.DataFrame:
        dim = routes.copy()
        dist = dim['distance_km'].astype(float)
        dim['difficulty_level'] = np.select([dist < 300, dist < 700], ['Fácil', 'Medio'], 'Difícil')
        dim['route_type'] = np.where(dist < 200, 'Regional', 'Interurbana')
        dim['route_key'] = dim['route_id']
        return dim[['route_key', 'route_id', 'route_code', 'origin_city', 'destination_city',
                    'distance_km', 'estimated_duration_hours', 'toll_cost',
                    'difficulty_level', 'route_type']]

    @staticmethod
    def build_dim_driver_source(drivers: pd.DataFrame, hoy: date) -> pd.DataFrame:
        """Versión 'nueva' de cada conductor (lo que dice hoy PostgreSQL)."""
        src = drivers.copy()
        src['full_name'] = src['first_name'] + ' ' + src['last_name']
        src['experience_months'] = ((pd.Timestamp(hoy) - pd.to_datetime(src['hire_date'])).dt.days // 30).astype(int)
        pct = src['on_time_pct_90d'].astype(float)
        src['performance_category'] = np.select([pct >= 90, pct >= 82], ['Alto', 'Medio'], 'Bajo')
        src.loc[pct.isna(), 'performance_category'] = 'Sin datos'
        src['zone'] = src['zone'].fillna('Sin asignar')
        return src[['driver_id', 'employee_code', 'full_name', 'license_number', 'license_expiry',
                    'phone', 'hire_date', 'experience_months', 'status', 'performance_category', 'zone']]

    # ------------------------------------------------------------------
    # LOAD
    # ------------------------------------------------------------------
    def load_dimensions(self, facts: pd.DataFrame, full: bool):
        logging.info("Cargando dimensiones...")
        hoy = date.today()
        vehicles, drivers, routes = self.extract_masters()

        # dim_date y dim_time: calendario fijo, se cargan una sola vez
        if self._sf("SELECT COUNT(*) FROM dim_date")[0][0] == 0:
            self._write(self.build_dim_date(date(2024, 1, 1), date(2027, 12, 31)), 'dim_date')
        if self._sf("SELECT COUNT(*) FROM dim_time")[0][0] == 0:
            self._write(self.build_dim_time(), 'dim_time')

        # dim_vehicle y dim_route: SCD tipo 1 (se sobrescriben con el estado actual)
        self._sf("TRUNCATE TABLE dim_vehicle")
        self._write(self.build_dim_vehicle(vehicles, hoy), 'dim_vehicle')
        self._sf("TRUNCATE TABLE dim_route")
        self._write(self.build_dim_route(routes), 'dim_route')

        # dim_driver: SCD tipo 2 (si cambia zona, estado, licencia o teléfono,
        # se cierra la versión vieja y se agrega una nueva; así se conserva la historia)
        self._load_dim_driver_scd2(self.build_dim_driver_source(drivers, hoy), hoy)

        # dim_customer: se agregan solo los clientes nuevos
        self._load_dim_customer(facts)
        logging.info("Dimensiones actualizadas")

    def _load_dim_driver_scd2(self, src: pd.DataFrame, hoy: date):
        cols_cambio = ['zone', 'status', 'license_expiry', 'phone']
        actual = pd.DataFrame(
            self._sf("SELECT driver_key, driver_id, zone, status, license_expiry, phone "
                     "FROM dim_driver WHERE is_current"),
            columns=['driver_key', 'driver_id'] + cols_cambio)

        if actual.empty:      # primera carga: todos entran como versión vigente
            nuevos = src.copy()
            nuevos['valid_from'] = pd.to_datetime(nuevos['hire_date']).dt.date
            cambiados_ids = []
        else:
            comp = src.merge(actual, on='driver_id', how='left', suffixes=('', '_dw'))
            es_nuevo = comp['driver_key'].isna()
            cambio = pd.Series(False, index=comp.index)
            for c in cols_cambio:
                cambio |= comp[c].astype(str) != comp[c + '_dw'].astype(str)
            cambiados = comp[~es_nuevo & cambio]
            cambiados_ids = cambiados['driver_id'].tolist()
            nuevos = comp[es_nuevo | (~es_nuevo & cambio)][src.columns].copy()
            nuevos['valid_from'] = hoy
            if cambiados_ids:  # cerrar la versión anterior
                ids = ','.join(str(int(i)) for i in cambiados_ids)
                self._sf(f"UPDATE dim_driver SET valid_to = DATEADD(day, -1, CURRENT_DATE()), "
                         f"is_current = FALSE WHERE is_current AND driver_id IN ({ids})")
            # Para los que no cambiaron, refrescar solo atributos tipo 1 (desempeño, experiencia)
            sin_cambio = comp[~es_nuevo & ~cambio]
            if not sin_cambio.empty:
                tmp = sin_cambio[['driver_key', 'performance_category', 'experience_months']].copy()
                self._sf("CREATE OR REPLACE TEMPORARY TABLE tmp_driver_t1 "
                         "(driver_key INT, performance_category VARCHAR(20), experience_months INT)")
                self._write(tmp, 'tmp_driver_t1')
                self._sf("UPDATE dim_driver d SET performance_category = t.performance_category, "
                         "experience_months = t.experience_months FROM tmp_driver_t1 t "
                         "WHERE d.driver_key = t.driver_key")

        if not nuevos.empty:
            max_key = self._sf("SELECT COALESCE(MAX(driver_key), 0) FROM dim_driver")[0][0]
            nuevos['driver_key'] = range(max_key + 1, max_key + 1 + len(nuevos))
            nuevos['valid_to'] = date(9999, 12, 31)
            nuevos['is_current'] = True
            self._write(nuevos, 'dim_driver')
        logging.info(f"dim_driver: {len(nuevos)} versiones nuevas, {len(cambiados_ids)} cerradas (SCD2)")

    def _load_dim_customer(self, facts: pd.DataFrame):
        clientes = (facts.groupby(['customer_name', 'destination_city'])
                    .agg(first_delivery_date=('scheduled_datetime', 'min'),
                         total_deliveries=('delivery_id', 'count'))
                    .reset_index().rename(columns={'destination_city': 'city'}))
        existentes = pd.DataFrame(self._sf("SELECT customer_name, city FROM dim_customer"),
                                  columns=['customer_name', 'city'])
        clientes = clientes.merge(existentes, on=['customer_name', 'city'], how='left', indicator=True)
        clientes = clientes[clientes['_merge'] == 'left_only'].drop(columns='_merge')
        if clientes.empty:
            return
        # Tipo de cliente: el sistema origen no lo registra; se asigna un tipo sintético
        # estable (siempre el mismo para el mismo nombre): 80% Individual, 15% Empresa, 5% Gobierno
        h = pd.util.hash_pandas_object(clientes['customer_name'], index=False) % 100
        clientes['customer_type'] = np.select([h < 80, h < 95], ['Individual', 'Empresa'], 'Gobierno')
        clientes['customer_category'] = np.select(
            [clientes['total_deliveries'] >= 3, clientes['total_deliveries'] == 2], ['Premium', 'Regular'], 'Ocasional')
        clientes['first_delivery_date'] = clientes['first_delivery_date'].dt.date
        max_key = self._sf("SELECT COALESCE(MAX(customer_key), 0) FROM dim_customer")[0][0]
        clientes['customer_key'] = range(max_key + 1, max_key + 1 + len(clientes))
        self._write(clientes[['customer_key', 'customer_name', 'customer_type', 'city',
                              'first_delivery_date', 'total_deliveries', 'customer_category']], 'dim_customer')
        logging.info(f"dim_customer: {len(clientes):,} clientes nuevos")

    def load_facts(self, df: pd.DataFrame):
        logging.info("Cargando tabla de hechos...")
        # Buscar las claves sustitutas (surrogate keys) vigentes de cada dimensión
        drv = pd.DataFrame(self._sf("SELECT driver_id, driver_key FROM dim_driver WHERE is_current"),
                           columns=['driver_id', 'driver_key'])
        cli = pd.DataFrame(self._sf("SELECT customer_name, city, customer_key FROM dim_customer"),
                           columns=['customer_name', 'destination_city', 'customer_key'])
        df = df.merge(drv, on='driver_id', how='left').merge(cli, on=['customer_name', 'destination_city'], how='left')
        df['vehicle_key'] = df['vehicle_id']
        df['route_key'] = df['route_id']
        df['is_damaged'] = False
        df['has_signature'] = df['recipient_signature']
        df['etl_batch_id'] = self.batch_id

        cols = ['date_key', 'scheduled_time_key', 'delivered_time_key', 'vehicle_key', 'driver_key',
                'route_key', 'customer_key', 'delivery_id', 'trip_id', 'tracking_number',
                'package_weight_kg', 'distance_km', 'fuel_consumed_liters', 'delivery_time_minutes',
                'delay_minutes', 'deliveries_per_hour', 'fuel_efficiency_km_per_liter',
                'cost_per_delivery', 'revenue_per_delivery', 'is_on_time', 'is_damaged',
                'has_signature', 'delivery_status', 'etl_batch_id']
        fact = df[cols].copy()
        for c in ['delivery_time_minutes', 'delay_minutes']:
            fact[c] = fact[c].astype(int)

        # Idempotencia: si ese rango de fechas ya se había cargado, se borra antes de insertar
        self._sf("DELETE FROM fact_deliveries WHERE date_key BETWEEN %s AND %s",
                 (int(fact['date_key'].min()), int(fact['date_key'].max())))
        n = self._write(fact, 'fact_deliveries')
        self.metrics['records_loaded'] = n
        logging.info(f"Cargadas {n:,} filas en fact_deliveries")

    def calculate_daily_totals(self):
        """Pre-calcula totales por día para reportes rápidos (tabla agg_daily_totals)."""
        self._sf("""
            CREATE TABLE IF NOT EXISTS agg_daily_totals (
                summary_date DATE, etl_batch_id INT, total_deliveries INT, on_time_deliveries INT,
                on_time_pct DECIMAL(5,2), avg_delay_minutes DECIMAL(10,2), total_weight_kg DECIMAL(14,2),
                total_fuel_liters DECIMAL(14,2), total_revenue DECIMAL(14,2),
                created_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP())
        """)
        self._sf("""
            DELETE FROM agg_daily_totals WHERE summary_date IN (
                SELECT DISTINCT d.full_date FROM fact_deliveries f
                JOIN dim_date d ON f.date_key = d.date_key WHERE f.etl_batch_id = %s)
        """, (self.batch_id,))
        self._sf("""
            INSERT INTO agg_daily_totals (summary_date, etl_batch_id, total_deliveries, on_time_deliveries,
                on_time_pct, avg_delay_minutes, total_weight_kg, total_fuel_liters, total_revenue)
            SELECT d.full_date, %s, COUNT(*), SUM(IFF(f.is_on_time, 1, 0)),
                   ROUND(100 * AVG(IFF(f.is_on_time, 1, 0)), 2), ROUND(AVG(f.delay_minutes), 2),
                   SUM(f.package_weight_kg), SUM(f.fuel_consumed_liters), SUM(f.revenue_per_delivery)
            FROM fact_deliveries f JOIN dim_date d ON f.date_key = d.date_key
            WHERE f.etl_batch_id = %s
            GROUP BY d.full_date
        """, (self.batch_id, self.batch_id))
        logging.info("Totales diarios calculados")

    # ------------------------------------------------------------------
    # Orquestación
    # ------------------------------------------------------------------
    def run_etl(self, full=False, fecha=None):
        inicio = datetime.now()
        logging.info(f"Iniciando ETL - batch {self.batch_id} - modo {'completo' if full else 'incremental'}")
        try:
            if not self.connect_databases():
                return self.metrics
            if full:
                desde, hasta = date(2000, 1, 1), date.today() + timedelta(days=1)
            else:
                dia = fecha or (date.today() - timedelta(days=1))   # por defecto: ayer
                desde, hasta = dia, dia + timedelta(days=1)

            df = self.extract_deliveries(desde, hasta)
            if df.empty:
                logging.info("No hay entregas nuevas para cargar")
            else:
                df = self.transform_facts(df)
                self.load_dimensions(df, full)
                self.load_facts(df)
                self.calculate_daily_totals()
        except Exception as e:
            logging.error(f"Error fatal en ETL: {e}")
            self.metrics['errors'] += 1
        finally:
            self.close_connections()
        segundos = (datetime.now() - inicio).total_seconds()
        logging.info(f"ETL terminado en {segundos:.1f} s - métricas: {json.dumps(self.metrics)}")
        return self.metrics


def job():
    FleetLogixETL().run_etl()


def main():
    parser = argparse.ArgumentParser(description='ETL FleetLogix: PostgreSQL -> Snowflake')
    parser.add_argument('--full', action='store_true', help='carga toda la historia')
    parser.add_argument('--fecha', help='día a cargar (YYYY-MM-DD); por defecto, ayer')
    parser.add_argument('--schedule', action='store_true', help='ejecutar todos los días a las 02:00')
    args = parser.parse_args()

    if args.schedule:
        schedule.every().day.at("02:00").do(job)
        logging.info("ETL programado todos los días a las 02:00. Ctrl+C para detener.")
        while True:
            schedule.run_pending()
            time.sleep(60)
    else:
        fecha = datetime.strptime(args.fecha, '%Y-%m-%d').date() if args.fecha else None
        FleetLogixETL().run_etl(full=args.full, fecha=fecha)


if __name__ == '__main__':
    main()
