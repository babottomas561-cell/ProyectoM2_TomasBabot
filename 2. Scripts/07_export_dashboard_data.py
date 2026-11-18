"""
FleetLogix - Exporta los datos del Data Warehouse (Snowflake) para el dashboard de Streamlit.

Saca dos tablas resumidas del modelo estrella y las guarda en dashboard/data/:
  - entregas_diarias.parquet: una fila por día, ciudad de origen, ciudad destino, tipo de vehículo y turno
  - conductores.parquet:      una fila por conductor (versión actual de dim_driver)

El tablero lee Snowflake en vivo si tiene credenciales; si no, usa esta copia
(por ejemplo cuando venza la prueba de Snowflake).
Uso:  python 07_export_dashboard_data.py
"""
import os
import sys
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

# Las consultas están en dashboard/consultas.py porque el tablero también las usa cuando lee Snowflake en vivo
sys.path.insert(0, os.path.join(RAIZ, 'dashboard'))
from consultas import CONSULTAS, leer  # noqa: E402

if __name__ == '__main__':
    os.makedirs(SALIDA, exist_ok=True)
    with snowflake.connector.connect(**config) as conn:
        for nombre in CONSULTAS:
            df = leer(conn, nombre)
            ruta = os.path.join(SALIDA, f'{nombre}.parquet')
            df.to_parquet(ruta, index=False)
            print(f'{nombre}: {len(df):,} filas -> {ruta}')
