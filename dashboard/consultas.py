"""
Consultas al Data Warehouse (FLEETLOGIX_DW.ANALYTICS) que usa el tablero.

Las usan dos programas, por eso están acá y no repetidas:
  - dashboard/app.py, cuando lee Snowflake en vivo
  - 2. Scripts/07_export_dashboard_data.py, que guarda la copia en dashboard/data/*.parquet
"""
import pandas as pd

# Una fila por día, ciudad destino, tipo de vehículo y turno
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

# Una fila por conductor: suma todas sus versiones (SCD tipo 2) y toma nombre y zona de la versión actual
SQL_CONDUCTORES = """
WITH por_conductor AS (
    SELECT dr.driver_id,
           COUNT(*)                     AS entregas,
           SUM(IFF(f.is_on_time, 1, 0)) AS entregas_a_tiempo,
           SUM(f.revenue_per_delivery)  AS ingreso,
           SUM(f.cost_per_delivery)     AS costo,
           AVG(f.deliveries_per_hour)   AS entregas_por_hora
    FROM fact_deliveries f
    JOIN dim_driver dr ON f.driver_key = dr.driver_key
    GROUP BY dr.driver_id
)
SELECT p.driver_id, a.full_name AS conductor, a.zone AS zona, a.performance_category AS categoria,
       p.entregas, p.entregas_a_tiempo, p.ingreso, p.costo, p.entregas_por_hora
FROM por_conductor p
JOIN dim_driver a ON a.driver_id = p.driver_id AND a.is_current
"""

CONSULTAS = {'entregas_diarias': SQL_ENTREGAS, 'conductores': SQL_CONDUCTORES}
TEXTO = ('fecha', 'ciudad', 'tipo_vehiculo', 'turno', 'conductor', 'zona', 'categoria')


def leer(conexion, nombre):
    """Corre una de las CONSULTAS con una conexión de snowflake.connector y deja los tipos listos para graficar."""
    df = conexion.cursor().execute(CONSULTAS[nombre]).fetch_pandas_all()
    df.columns = df.columns.str.lower()
    # Snowflake devuelve los NUMBER con decimales como Decimal: los paso a float
    for col in df.columns:
        if col not in TEXTO:
            df[col] = pd.to_numeric(df[col])
    if 'fecha' in df:
        df['fecha'] = pd.to_datetime(df['fecha'])
    return df
