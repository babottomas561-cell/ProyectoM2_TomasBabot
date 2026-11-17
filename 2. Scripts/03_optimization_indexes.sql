-- =====================================================
-- FLEETLOGIX - ÍNDICES DE OPTIMIZACIÓN
-- Basados en las 8 queries de 02_queries_analysis.sql
-- Las mediciones con EXPLAIN ANALYZE (antes / después) están en
-- 1. Notebooks/Avance_2_SQLAnalysis.ipynb
-- =====================================================
-- Criterio: un índice sirve cuando la query necesita POCAS filas de una tabla grande
-- (filtros y JOIN por clave). Si la query igual tiene que leer toda la tabla
-- (por ejemplo, la 5 y la 7, que agrupan los 100.000 viajes), el índice no ayuda
-- y PostgreSQL lo ignora. Por eso no se crearon índices "por las dudas":
-- cada índice ocupa espacio y hace más lentos los INSERT.
--
-- Índices que ya traía el esquema base: idx_trips_departure, idx_deliveries_status,
-- idx_vehicles_status.
--
-- Se usan DROP ... IF EXISTS para poder volver a correr el script y repetir la medición.

-- =====================================================
-- ÍNDICE 1: entregas por viaje
-- =====================================================
-- Justificación: PostgreSQL NO crea índices en las claves foráneas automáticamente.
-- Sin este índice, para unir deliveries con trips se leen las 400.000 entregas
-- aunque solo se necesiten las de unos pocos viajes.
-- INCLUDE agrega las columnas que usan las queries, así se resuelve leyendo solo
-- el índice (Index Only Scan) sin ir a la tabla.
-- Queries beneficiadas: 4 y 10
DROP INDEX IF EXISTS idx_deliveries_trip_id;
CREATE INDEX idx_deliveries_trip_id
    ON deliveries(trip_id)
    INCLUDE (delivery_id, package_weight_kg, scheduled_datetime, delivered_datetime);

-- =====================================================
-- ÍNDICE 2: mantenimientos por vehículo
-- =====================================================
-- Justificación: la query 9 busca los mantenimientos de cada vehículo y suma su costo.
-- Queries beneficiadas: 9 y 9b
DROP INDEX IF EXISTS idx_maintenance_vehicle_cost;
CREATE INDEX idx_maintenance_vehicle_cost
    ON maintenance(vehicle_id)
    INCLUDE (cost, maintenance_id);

-- =====================================================
-- ÍNDICE 3: viajes completados por vehículo (índice parcial)
-- =====================================================
-- Justificación: la query 9 agrupa los viajes COMPLETADOS por vehículo.
-- El WHERE hace que el índice guarde solo los viajes completados (índice parcial):
-- es más chico y coincide exactamente con el filtro de la query.
-- Queries beneficiadas: 9 y 9b
DROP INDEX IF EXISTS idx_trips_vehicle_completed;
CREATE INDEX idx_trips_vehicle_completed
    ON trips(vehicle_id)
    INCLUDE (trip_id, route_id)
    WHERE status = 'completed';

-- =====================================================
-- ÍNDICE 4: estado del viaje
-- =====================================================
-- Justificación: la query 3 cuenta viajes por estado; con este índice el conteo
-- se hace leyendo solo el índice (mucho más chico que la tabla).
-- También sirve al tablero de operación para buscar rápido los viajes 'in_progress'.
-- Queries beneficiadas: 3
DROP INDEX IF EXISTS idx_trips_status;
CREATE INDEX idx_trips_status ON trips(status);

-- =====================================================
-- ÍNDICE 5: vencimiento de licencias
-- =====================================================
-- Justificación: la query 2 filtra por license_expiry y solo devuelve unas pocas filas.
-- Hoy drivers tiene 400 filas y la ganancia es de centésimas de milisegundo, pero el
-- control de licencias se corre todos los días y el índice evita que se degrade si la planta crece.
-- Queries beneficiadas: 2
DROP INDEX IF EXISTS idx_drivers_license_expiry;
CREATE INDEX idx_drivers_license_expiry ON drivers(license_expiry);

-- =====================================================
-- ACTUALIZAR ESTADÍSTICAS
-- =====================================================
-- El planificador decide si usa o no un índice según estas estadísticas.
ANALYZE vehicles;
ANALYZE drivers;
ANALYZE routes;
ANALYZE trips;
ANALYZE deliveries;
ANALYZE maintenance;

-- =====================================================
-- VERIFICAR LOS ÍNDICES CREADOS
-- =====================================================
SELECT
    tablename,
    indexname,
    pg_size_pretty(pg_relation_size(indexname::regclass)) AS tamano,
    indexdef
FROM pg_indexes
WHERE schemaname = 'public'
    AND indexname LIKE 'idx_%'
ORDER BY tablename, indexname;

-- =====================================================
-- AJUSTE OPCIONAL DEL PLANIFICADOR (disco SSD)
-- =====================================================
-- random_page_cost vale 4 por defecto (pensado para discos mecánicos). En una
-- computadora con SSD, leer "salteado" cuesta casi lo mismo que leer en orden, y el
-- valor recomendado es 1.1. Con eso PostgreSQL se anima a usar más los índices.
-- Se aplica solo a la sesión (no cambia la configuración del servidor):
-- SET random_page_cost = 1.1;

-- =====================================================
-- PARA VOLVER AL ESTADO "SIN ÍNDICES" (repetir la medición)
-- =====================================================
-- DROP INDEX IF EXISTS idx_deliveries_trip_id, idx_maintenance_vehicle_cost,
--     idx_trips_vehicle_completed, idx_trips_status, idx_drivers_license_expiry;
