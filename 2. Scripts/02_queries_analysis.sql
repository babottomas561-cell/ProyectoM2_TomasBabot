-- =====================================================
-- FLEETLOGIX - 8 QUERIES SQL SELECCIONADAS (de las 12 provistas)
-- Selección según la consigna del Avance 2:
--   3 básicas (1, 2, 3) + intermedias 4 y 5 + una de 6/7/8 (la 7)
--   + compleja 9 + una de 10/11/12 (la 10)
-- Cada query indica el problema de negocio que responde.
-- Los resultados e interpretación están en 1. Notebooks/Avance_2_SQLAnalysis.ipynb
-- =====================================================

-- =====================================================
-- QUERIES BÁSICAS
-- =====================================================

-- Query 1: Contar vehículos por tipo
-- Problema de negocio: conocer la composición de la flota
SELECT
    vehicle_type,
    COUNT(*) AS cantidad
FROM vehicles
GROUP BY vehicle_type
ORDER BY cantidad DESC;

-- Query 2: Conductores con licencia próxima a vencer (o ya vencida)
-- Problema de negocio: prevenir problemas legales por licencias vencidas
-- Ajuste: se agrega el estado del conductor para priorizar a los activos.
SELECT
    first_name,
    last_name,
    license_number,
    license_expiry,
    status
FROM drivers
WHERE license_expiry < CURRENT_DATE + INTERVAL '30 days'
ORDER BY license_expiry;

-- Query 3: Total de viajes por estado
-- Problema de negocio: monitorear operaciones en curso
SELECT
    status,
    COUNT(*) AS total_viajes
FROM trips
GROUP BY status;

-- =====================================================
-- QUERIES INTERMEDIAS
-- =====================================================

-- Query 4: Entregas por ciudad destino en los últimos 2 meses
-- Problema de negocio: identificar demanda por ciudad para planificar recursos
SELECT
    r.destination_city,
    COUNT(DISTINCT t.trip_id) AS total_viajes,
    COUNT(d.delivery_id) AS total_entregas,
    SUM(d.package_weight_kg) AS peso_total_kg
FROM routes r
INNER JOIN trips t ON r.route_id = t.route_id
INNER JOIN deliveries d ON t.trip_id = d.trip_id
WHERE t.departure_datetime >= CURRENT_DATE - INTERVAL '60 days'
GROUP BY r.destination_city
ORDER BY total_entregas DESC;

-- Query 5: Conductores activos con cantidad de viajes completados
-- Problema de negocio: evaluar la carga de trabajo por conductor
SELECT
    d.driver_id,
    d.first_name || ' ' || d.last_name AS nombre_completo,
    d.license_expiry,
    COUNT(t.trip_id) AS viajes_totales,
    SUM(CASE WHEN t.status = 'completed' THEN 1 ELSE 0 END) AS viajes_completados
FROM drivers d
LEFT JOIN trips t ON d.driver_id = t.driver_id
WHERE d.status = 'active'
GROUP BY d.driver_id, d.first_name, d.last_name, d.license_expiry
HAVING COUNT(t.trip_id) > 0
ORDER BY viajes_completados DESC;

-- Query 7: Rutas con mayor consumo de combustible por kilómetro
-- Problema de negocio: identificar rutas ineficientes para optimizarlas
SELECT
    r.route_code,
    r.origin_city || ' -> ' || r.destination_city AS ruta,
    r.distance_km,
    COUNT(t.trip_id) AS viajes_realizados,
    ROUND(AVG(t.fuel_consumed_liters), 2) AS promedio_combustible_litros,
    ROUND(AVG(t.fuel_consumed_liters / NULLIF(r.distance_km, 0)) * 100, 2) AS litros_por_100km,
    SUM(t.fuel_consumed_liters) AS combustible_total
FROM routes r
INNER JOIN trips t ON r.route_id = t.route_id
WHERE t.fuel_consumed_liters IS NOT NULL
    AND r.distance_km > 0
    AND t.status = 'completed'
GROUP BY r.route_id, r.route_code, r.origin_city, r.destination_city, r.distance_km
HAVING COUNT(t.trip_id) >= 50
ORDER BY litros_por_100km DESC
LIMIT 10;

-- =====================================================
-- QUERIES COMPLEJAS
-- =====================================================

-- Query 9: Costo de mantenimiento por kilómetro recorrido (versión ORIGINAL)
-- Problema de negocio: evaluar el costo-beneficio de cada tipo de vehículo
-- ATENCIÓN: esta versión tiene un error de "multiplicación de filas" (fan-out):
-- al unir trips y maintenance a la vez, cada viaje se repite por cada mantenimiento
-- del vehículo, y entonces km_totales y costo_mantenimiento_total salen inflados.
-- Se deja para mostrar el problema; la versión corregida está debajo (9b).
WITH vehicle_metrics AS (
    SELECT
        v.vehicle_id,
        v.vehicle_type,
        v.license_plate,
        COUNT(DISTINCT t.trip_id) AS total_viajes,
        SUM(r.distance_km) AS km_totales,
        SUM(m.cost) AS costo_mantenimiento_total,
        COUNT(DISTINCT m.maintenance_id) AS cantidad_mantenimientos
    FROM vehicles v
    LEFT JOIN trips t ON v.vehicle_id = t.vehicle_id
    LEFT JOIN routes r ON t.route_id = r.route_id
    LEFT JOIN maintenance m ON v.vehicle_id = m.vehicle_id
    WHERE t.status = 'completed'
    GROUP BY v.vehicle_id, v.vehicle_type, v.license_plate
)
SELECT
    vehicle_type,
    COUNT(vehicle_id) AS cantidad_vehiculos,
    SUM(total_viajes) AS viajes_totales,
    SUM(km_totales) AS kilometros_totales,
    SUM(costo_mantenimiento_total) AS costo_total_mantenimiento,
    ROUND(SUM(costo_mantenimiento_total) / NULLIF(SUM(km_totales), 0), 2) AS costo_por_km,
    ROUND(AVG(costo_mantenimiento_total / NULLIF(cantidad_mantenimientos, 0)), 2) AS costo_promedio_por_mantenimiento
FROM vehicle_metrics
WHERE km_totales > 0 AND costo_mantenimiento_total > 0
GROUP BY vehicle_type
ORDER BY costo_por_km DESC;

-- Query 9b: Costo de mantenimiento por kilómetro (versión CORREGIDA)
-- Se calcula por separado lo que recorrió cada vehículo y lo que gastó en mantenimiento,
-- y recién después se unen (una fila por vehículo de cada lado: no hay duplicados).
WITH km_por_vehiculo AS (
    SELECT t.vehicle_id,
           COUNT(*) AS total_viajes,
           SUM(r.distance_km) AS km_totales
    FROM trips t
    JOIN routes r ON t.route_id = r.route_id
    WHERE t.status = 'completed'
    GROUP BY t.vehicle_id
),
mant_por_vehiculo AS (
    SELECT vehicle_id,
           COUNT(*) AS cantidad_mantenimientos,
           SUM(cost) AS costo_mantenimiento_total
    FROM maintenance
    GROUP BY vehicle_id
)
SELECT
    v.vehicle_type,
    COUNT(*) AS cantidad_vehiculos,
    SUM(k.total_viajes) AS viajes_totales,
    SUM(k.km_totales) AS kilometros_totales,
    SUM(m.costo_mantenimiento_total) AS costo_total_mantenimiento,
    ROUND(SUM(m.costo_mantenimiento_total) / NULLIF(SUM(k.km_totales), 0), 2) AS costo_por_km,
    ROUND(SUM(m.costo_mantenimiento_total) / NULLIF(SUM(m.cantidad_mantenimientos), 0), 2) AS costo_promedio_por_mantenimiento
FROM vehicles v
JOIN km_por_vehiculo k ON v.vehicle_id = k.vehicle_id
JOIN mant_por_vehiculo m ON v.vehicle_id = m.vehicle_id
GROUP BY v.vehicle_type
ORDER BY costo_por_km DESC;

-- Query 10: Ranking de conductores por eficiencia (Window Functions)
-- Problema de negocio: identificar a los mejores conductores para incentivos
WITH conductor_metricas AS (
    SELECT
        d.driver_id,
        d.first_name || ' ' || d.last_name AS nombre,
        COUNT(DISTINCT t.trip_id) AS viajes,
        COUNT(DISTINCT del.delivery_id) AS entregas,
        AVG(t.fuel_consumed_liters / NULLIF(r.distance_km, 0)) * 100 AS consumo_100km,
        COUNT(CASE WHEN del.delivered_datetime <= del.scheduled_datetime THEN 1 END)::NUMERIC /
            NULLIF(COUNT(del.delivery_id), 0) * 100 AS puntualidad_pct
    FROM drivers d
    JOIN trips t ON d.driver_id = t.driver_id
    JOIN routes r ON t.route_id = r.route_id
    LEFT JOIN deliveries del ON t.trip_id = del.trip_id
    WHERE t.departure_datetime >= CURRENT_DATE - INTERVAL '3 months'
    GROUP BY d.driver_id, d.first_name, d.last_name
    HAVING COUNT(DISTINCT t.trip_id) >= 20
)
SELECT
    nombre,
    viajes,
    entregas,
    ROUND(consumo_100km, 2) AS consumo_100km,
    ROUND(puntualidad_pct, 2) AS puntualidad_pct,
    RANK() OVER (ORDER BY puntualidad_pct DESC) AS rank_puntualidad,
    RANK() OVER (ORDER BY consumo_100km ASC) AS rank_eficiencia,
    RANK() OVER (ORDER BY entregas DESC) AS rank_productividad,
    ROUND((RANK() OVER (ORDER BY puntualidad_pct DESC) +
           RANK() OVER (ORDER BY consumo_100km ASC) +
           RANK() OVER (ORDER BY entregas DESC)) / 3.0, 2) AS score_promedio
FROM conductor_metricas
ORDER BY score_promedio ASC
LIMIT 20;
