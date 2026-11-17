-- Usuario de solo lectura para el tablero de Streamlit.
-- El tablero no usa mi usuario: usa este, que solo puede leer FLEETLOGIX_DW.ANALYTICS y entra con su propio
-- par de llaves (sin contraseña). Si la llave se filtra, alcanza con borrar este usuario.
-- Se corre una sola vez como ACCOUNTADMIN. <LLAVE_PUBLICA> es el contenido de keys/tablero_streamlit.pub
-- sin las líneas BEGIN/END (la llave privada queda en keys/, que no se sube al repo).

CREATE ROLE IF NOT EXISTS FLEETLOGIX_TABLERO;
GRANT USAGE ON WAREHOUSE FLEETLOGIX_WH TO ROLE FLEETLOGIX_TABLERO;
GRANT USAGE ON DATABASE FLEETLOGIX_DW TO ROLE FLEETLOGIX_TABLERO;
GRANT USAGE ON SCHEMA FLEETLOGIX_DW.ANALYTICS TO ROLE FLEETLOGIX_TABLERO;
GRANT SELECT ON ALL TABLES IN SCHEMA FLEETLOGIX_DW.ANALYTICS TO ROLE FLEETLOGIX_TABLERO;

CREATE USER IF NOT EXISTS TABLERO_STREAMLIT
    TYPE = SERVICE
    DEFAULT_ROLE = FLEETLOGIX_TABLERO
    DEFAULT_WAREHOUSE = FLEETLOGIX_WH
    COMMENT = 'Tablero FleetLogix en Streamlit (solo lectura)';
ALTER USER TABLERO_STREAMLIT SET RSA_PUBLIC_KEY = '<LLAVE_PUBLICA>';
GRANT ROLE FLEETLOGIX_TABLERO TO USER TABLERO_STREAMLIT;

-- El warehouse se apaga solo al minuto sin consultas, para no gastar créditos
ALTER WAREHOUSE FLEETLOGIX_WH SET AUTO_SUSPEND = 60 AUTO_RESUME = TRUE;
