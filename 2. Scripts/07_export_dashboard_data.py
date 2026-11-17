"""
FleetLogix - Exporta los datos del Data Warehouse (Snowflake) para el dashboard de Streamlit.

Saca dos tablas resumidas del modelo estrella y las guarda en dashboard/data/:
  - entregas_diarias.parquet: una fila por día, ciudad destino, tipo de vehículo y turno
  - conductores.parquet:      una fila por conductor (versión actual de dim_driver)

Así el dashboard usa datos reales del proyecto pero se puede abrir sin conectarse a Snowflake.
Uso:  python 07_export_dashboard_data.py
"""
import os
import pandas as pd
import snowflake.connector
from dotenv import load_dotenv

CARPETA = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.join(CARPETA, '..')
SALIDA = os.path.join(RAIZ, 'dashboard', 'data')
load_dotenv(os.path.join(RAIZ, '.env'))

config = {
    'account': os.getenv('SNOWFLAKE_ACCOUNT'),
    'user': os.getenv('SNOWFLAKE_USER'),
    'warehouse': os.getenv('SNOWFLAKE_WAREHOUSE', 'FLEETLOGIX_WH'),
    'database': os.getenv('SNOWFLAKE_DATABASE', 'FLEETLOGIX_DW'),
    'schema': os.getenv('SNOWFLAKE_SCHEMA', 'ANALYTICS'),
    'role': os.getenv('SNOWFLAKE_ROLE', 'ACCOUNTADMIN'),
}
llave = os.getenv('SNOWFLAKE_PRIVATE_KEY_FILE')
if llave:
    config['private_key_file'] = llave if os.path.isabs(llave) else os.path.join(RAIZ, llave)
else:
    config['password'] = os.getenv('SNOWFLAKE_PASSWORD')

SQL_ENTREGAS = """
SELECT d.full_date                          AS fecha,
       r.destination_city                   AS ciudad,
       v.vehicle_type                       AS tipo_vehiculo,
       t.shift                              AS turno,
       COUNT(*)                             AS entregas,
       SUM(IFF(f.is_on_time, 1, 0))         AS entregas_a_tiempo,
       SUM(f.package_weight_kg)             AS peso_kg,
       SUM(f.distance_km)                   AS km,
       SUM(f.fuel_consumed_liters)          AS litros,
       SUM(f.revenue_per_delivery)          AS ingreso,
       SUM(f.cost_per_delivery)             AS costo,
       SUM(f.delivery_time_minutes)         AS minutos_entrega
FROM fact_deliveries f
JOIN dim_date d    ON f.date_key = d.date_key
JOIN dim_route r   ON f.route_key = r.route_key
JOIN dim_vehicle v ON f.vehicle_key = v.vehicle_key
JOIN dim_time t    ON f.scheduled_time_key = t.time_key
GROUP BY 1, 2, 3, 4
"""

SQL_CONDUCTORES = """
WITH por_conductor AS (
    SELECT dr.driver_id,
           COUNT(*)                     AS entregas,
           SUM(IFF(f.is_on_time, 1, 0)) AS entregas_a_tiempo,
           SUM(f.revenue_per_delivery)  AS ingreso,
           SUM(f.cost_per_delivery)     AS costo,
           AVG(f.deliveries_per_hour)   AS entregas_por_hora
    FROM fact_deliveries f
    JOIN dim_driver dr ON f.driver_key = dr.driver_key   -- suma todas las versiones (SCD tipo 2) del conductor
    GROUP BY dr.driver_id
)
SELECT p.driver_id, a.full_name AS conductor, a.zone AS zona, a.performance_category AS categoria,
       p.entregas, p.entregas_a_tiempo, p.ingreso, p.costo, p.entregas_por_hora
FROM por_conductor p
JOIN dim_driver a ON a.driver_id = p.driver_id AND a.is_current   -- nombre y zona de la versión actual
"""

if __name__ == '__main__':
    os.makedirs(SALIDA, exist_ok=True)
    with snowflake.connector.connect(**config) as conn:
        for nombre, sql in [('entregas_diarias', SQL_ENTREGAS), ('conductores', SQL_CONDUCTORES)]:
            df = conn.cursor().execute(sql).fetch_pandas_all()
            df.columns = df.columns.str.lower()
            # Snowflake devuelve los NUMBER con decimales como Decimal: los paso a float para graficar
            for col in df.columns:
                if col not in ('fecha', 'ciudad', 'tipo_vehiculo', 'turno', 'conductor', 'zona', 'categoria'):
                    df[col] = pd.to_numeric(df[col])
            if 'fecha' in df:
                df['fecha'] = pd.to_datetime(df['fecha'])
            ruta = os.path.join(SALIDA, f'{nombre}.parquet')
            df.to_parquet(ruta, index=False)
            print(f'{nombre}: {len(df):,} filas -> {ruta}')
