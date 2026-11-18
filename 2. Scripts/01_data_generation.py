"""
FleetLogix - Generación de Datos Sintéticos
Genera 505000+ registros respetando relaciones y reglas de negocio
"""

import psycopg2
from psycopg2.extras import execute_batch
import pandas as pd
import numpy as np
from faker import Faker
from datetime import datetime, timedelta
import random
import logging
from tqdm import tqdm
import json
import os
import bisect

# Lee las variables del archivo .env (si existe) para la conexión
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env'))
except ImportError:
    pass

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('data_generation.log'),
        logging.StreamHandler()
    ]
)

# Configuración de conexión
# Se lee de variables de entorno para no dejar la contraseña escrita en el código.
# En mi Mac, PostgreSQL 18 (Homebrew) usa mi usuario del sistema y no pide contraseña.
DB_CONFIG = {
    'host': os.getenv('PGHOST', 'localhost'),
    'database': os.getenv('PGDATABASE', 'fleetlogix'),
    'user': os.getenv('PGUSER', os.getenv('USER', 'postgres')),
    'password': os.getenv('PGPASSWORD', ''),
    'port': int(os.getenv('PGPORT', 5432))
}

# Inicializar Faker con semilla para reproducibilidad
fake = Faker('es_CO')  # Español Colombia (por Bogotá)
Faker.seed(42)
random.seed(42)
np.random.seed(42)

class DataGenerator:
    def __init__(self, db_config):
        self.db_config = db_config
        self.connection = None
        self.cursor = None
        self.cities = ['Bogotá', 'Medellín', 'Cali', 'Barranquilla', 'Cartagena']
        
        # Contadores para logging
        self.counters = {
            'vehicles': 0,
            'drivers': 0,
            'routes': 0,
            'trips': 0,
            'deliveries': 0,
            'maintenance': 0
        }
    
    def connect(self):
        """Establecer conexión con la base de datos"""
        try:
            self.connection = psycopg2.connect(**self.db_config)
            self.cursor = self.connection.cursor()
            logging.info(" Conexión exitosa a PostgreSQL")
            return True
        except Exception as e:
            logging.error(f" Error al conectar: {e}")
            return False
    
    def generate_vehicles(self, count=200):
        """Generar 200 vehículos con diferentes tipos y capacidades"""
        logging.info(f"Generando {count} vehículos...")
        
        vehicle_types = [
            ('Camión Grande', 5000, 'diesel', 0.3),
            ('Camión Mediano', 3000, 'diesel', 0.3),
            ('Van', 1500, 'gasolina', 0.3),
            ('Motocicleta', 50, 'gasolina', 0.1)
        ]
        
        vehicles = []
        used_plates = set()  # MEJORA: license_plate es UNIQUE, evitamos repetir placas
        for i in range(count):
            v_type, capacity, fuel, prob = random.choices(
                vehicle_types,
                weights=[vt[3] for vt in vehicle_types]
            )[0]

            # Generar placa colombiana (ABC123), sin repetir
            license_plate = None
            while license_plate is None or license_plate in used_plates:
                license_plate = f"{fake.random_uppercase_letter()}{fake.random_uppercase_letter()}{fake.random_uppercase_letter()}{random.randint(100,999)}"
            used_plates.add(license_plate)
            
            # Fecha de adquisición en los últimos 5 años
            acquisition_date = fake.date_between(start_date='-5y', end_date='-1m')
            
            # 90% activos, 10% en mantenimiento o inactivos
            status = random.choice(['active'] * 9 + ['maintenance'])
            
            vehicles.append((
                license_plate,
                v_type,
                capacity,
                fuel,
                acquisition_date,
                status
            ))
        
        # Insertar en batch (mismas columnas y en el mismo orden que la tupla de arriba)
        query = """
            INSERT INTO vehicles (license_plate, vehicle_type, capacity_kg,
                                  fuel_type, acquisition_date, status)
            VALUES (%s, %s, %s, %s, %s, %s)
        """

        execute_batch(self.cursor, query, vehicles, page_size=100)
        self.connection.commit()
        self.counters['vehicles'] = count
        logging.info(f" {count} vehículos insertados")
    
    def generate_drivers(self, count=400):
        """Generar 400 conductores con datos realistas"""
        logging.info(f"Generando {count} conductores...")
        
        drivers = []
        license_types = ['C1', 'C2', 'C3', 'A2']  # Tipos de licencia Colombia
        
        for i in range(count):
            employee_code = f"EMP{str(i+1).zfill(4)}"
            first_name = fake.first_name()
            last_name = fake.last_name()
            
            # Licencia colombiana
            license_number = f"{random.randint(1000000000, 9999999999)}"
            license_type = random.choice(license_types)
            
            # Licencia válida por 3 años, algunas próximas a vencer
            license_expiry = fake.date_between(start_date='-1m', end_date='+3y')
            
            phone = f"3{random.randint(100000000, 999999999)}"  # Celular colombiano
            
            # Fecha de contratación en los últimos 5 años
            hire_date = fake.date_between(start_date='-5y', end_date='-1w')
            
            # 95% activos
            status = random.choice(['active'] * 19 + ['inactive'])
            
            drivers.append((
                employee_code,
                first_name,
                last_name,
                license_number,
                license_expiry,
                phone,
                hire_date,
                status
            ))
        
        query = """
            INSERT INTO drivers (employee_code, first_name, last_name, 
                               license_number, license_expiry, phone, 
                               hire_date, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        execute_batch(self.cursor, query, drivers, page_size=100)
        self.connection.commit()
        self.counters['drivers'] = count
        logging.info(f" {count} conductores insertados")
    
    def generate_routes(self, count=50):
        """Generar 50 rutas entre las 5 ciudades principales"""
        logging.info(f"Generando {count} rutas...")
        
        routes = []
        route_counter = 1
        
        # Generar rutas entre todas las combinaciones de ciudades
        for origin in self.cities:
            for destination in self.cities:
                if origin != destination:
                    # Múltiples rutas entre ciudades principales
                    # CORRECCIÓN: con 3 rutas solo para Bogotá salían 8*3 + 12*2 = 48 rutas.
                    # Le damos 3 también al corredor Medellín-Cali -> 8*3 + 2*3 + 10*2 = 50.
                    corredor_principal = {origin, destination} == {'Medellín', 'Cali'}
                    num_routes = 3 if (origin == 'Bogotá' or destination == 'Bogotá' or corredor_principal) else 2
                    
                    for i in range(num_routes):
                        route_code = f"R{str(route_counter).zfill(3)}"
                        
                        # Distancias aproximadas entre ciudades colombianas
                        base_distance = self._get_distance(origin, destination)
                        distance = base_distance + random.uniform(-50, 50)
                        
                        # Tiempo estimado (60-80 km/h promedio)
                        avg_speed = random.uniform(60, 80)
                        duration = distance / avg_speed
                        
                        # Peajes basados en distancia
                        toll_cost = int(distance / 100) * 15000  # 15k pesos por cada 100km
                        
                        routes.append((
                            route_code,
                            origin,
                            destination,
                            round(distance, 2),
                            round(duration, 2),
                            toll_cost
                        ))
                        
                        route_counter += 1
                        if route_counter > count:
                            break
                    
                    if route_counter > count:
                        break
            
            if route_counter > count:
                break
        
        # Ajustar para tener exactamente 50 rutas
        routes = routes[:count]
        
        query = """
            INSERT INTO routes (route_code, origin_city, destination_city, 
                              distance_km, estimated_duration_hours, toll_cost)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        
        execute_batch(self.cursor, query, routes, page_size=50)
        self.connection.commit()
        self.counters['routes'] = count
        logging.info(f" {count} rutas insertadas")
    
    def _get_distance(self, origin, destination):
        """Obtener distancia aproximada entre ciudades colombianas"""
        distances = {
            ('Bogotá', 'Medellín'): 440,
            ('Bogotá', 'Cali'): 460,
            ('Bogotá', 'Barranquilla'): 1000,
            ('Bogotá', 'Cartagena'): 1050,
            ('Medellín', 'Cali'): 420,
            ('Medellín', 'Barranquilla'): 640,
            ('Medellín', 'Cartagena'): 640,
            ('Cali', 'Barranquilla'): 1100,
            ('Cali', 'Cartagena'): 1100,
            ('Barranquilla', 'Cartagena'): 120
        }
        
        key = tuple(sorted([origin, destination]))
        return distances.get(key, 500)
    
    # ------------------------------------------------------------------
    # MEJORA: patrones de negocio. El script base reparte todo al azar y en forma pareja
    # (mismo volumen todos los días, 90% a tiempo en todas partes), y así el análisis no
    # encuentra nada. Estos supuestos imitan una operación real en Colombia.
    # ------------------------------------------------------------------
    # Peso de cada ciudad como origen y como destino (Bogotá es el mayor mercado)
    PESO_CIUDAD = {'Bogotá': 0.30, 'Medellín': 0.22, 'Cali': 0.18, 'Barranquilla': 0.16, 'Cartagena': 0.14}
    # Estacionalidad: pico en Navidad y en noviembre (Black Friday), baja en enero
    PESO_MES = {1: 0.80, 2: 0.88, 3: 0.95, 4: 0.97, 5: 1.00, 6: 1.04,
                7: 1.03, 8: 0.98, 9: 1.00, 10: 1.05, 11: 1.15, 12: 1.30}
    # Día de la semana (lunes = 0): el lunes sale lo acumulado del fin de semana; el domingo casi no se trabaja
    PESO_DIA_SEMANA = [1.10, 1.00, 1.00, 1.00, 1.05, 0.70, 0.30]
    CRECIMIENTO_ANUAL = 0.12                     # la empresa crece 12% por año
    FERIADOS = {(1, 1), (5, 1), (7, 20), (8, 7), (12, 8), (12, 25)}
    # Litros cada 100 km (vacío) según el tipo de vehículo. El script base usaba 8-15 L para todos,
    # y por eso una moto gastaba lo mismo que un camión.
    CONSUMO_100KM = {'Camión Grande': 32.0, 'Camión Mediano': 22.0, 'Van': 12.0, 'Motocicleta': 3.5}
    KM_MAXIMO_MOTO = 200                         # la moto es para trayectos cortos (Barranquilla - Cartagena)
    KM_LARGO = 800                               # rutas a la costa: se prefieren camiones
    DESCANSO_CONDUCTOR_H = 8                     # horas de descanso entre dos viajes del mismo conductor
    ALISTAMIENTO_VEHICULO_H = 2                  # horas para descargar y cargar el vehículo entre viajes

    def _peso_dia(self, dia, avance):
        """Volumen relativo de un día: mes x día de la semana x crecimiento (avance va de 0 a 1 en los 2 años)."""
        peso = self.PESO_MES[dia.month] * self.PESO_DIA_SEMANA[dia.weekday()]
        peso *= (1 + self.CRECIMIENTO_ANUAL) ** (2 * avance)
        if (dia.month, dia.day) in self.FERIADOS:
            peso *= 0.4
        return peso

    def generate_trips(self, count=100000):
        """Generar 100000 viajes en 2 años de operación"""
        logging.info(f"Generando {count} viajes...")

        # Vehículos y conductores activos, con la fecha desde la que se pueden usar
        self.cursor.execute("""
            SELECT vehicle_id, vehicle_type, capacity_kg, acquisition_date
            FROM vehicles WHERE status = 'active' ORDER BY vehicle_id
        """)
        veh = self.cursor.fetchall()
        self.cursor.execute("""
            SELECT driver_id, hire_date
            FROM drivers WHERE status = 'active' ORDER BY driver_id
        """)
        cond = self.cursor.fetchall()
        self.cursor.execute("""
            SELECT route_id, origin_city, destination_city, distance_km, estimated_duration_hours
            FROM routes ORDER BY route_id
        """)
        routes = self.cursor.fetchall()

        # 2 años completos: desde hace 730 días a las 00:00 hasta ayer
        hoy = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        inicio = hoy - timedelta(days=730)

        def horas(fecha):
            """Horas desde el inicio (para comparar fechas rápido con NumPy)."""
            return (datetime.combine(fecha, datetime.min.time()) - inicio).total_seconds() / 3600

        ciudad_idx = {c: i for i, c in enumerate(self.cities)}
        peso_ciudad = np.array([self.PESO_CIUDAD[c] for c in self.cities])

        v_id = np.array([v[0] for v in veh])
        v_tipo = np.array([v[1] for v in veh])
        v_cap = np.array([float(v[2]) for v in veh])
        v_desde = np.array([horas(v[3]) for v in veh])
        v_moto = v_tipo == 'Motocicleta'
        v_van = v_tipo == 'Van'
        v_libre = np.full(len(veh), -1e9)                                    # hora en que queda libre
        v_lugar = np.random.choice(len(self.cities), len(veh), p=peso_ciudad)  # ciudad donde está

        c_id = np.array([c[0] for c in cond])
        c_desde = np.array([horas(c[1]) for c in cond])
        c_libre = np.full(len(cond), -1e9)
        c_lugar = np.random.choice(len(self.cities), len(cond), p=peso_ciudad)

        # 1) Cuántos viajes sale cada día (los 100.000 repartidos según el peso de cada día)
        dias = [inicio + timedelta(days=i) for i in range(730)]
        pesos = np.array([self._peso_dia(d, i / 730) for i, d in enumerate(dias)])
        cuota = pesos / pesos.sum() * count
        por_dia = np.floor(cuota).astype(int)
        faltan = count - por_dia.sum()
        por_dia[np.argsort(-(cuota - por_dia))[:faltan]] += 1               # resto mayor: suma exacta

        # 2) Hora de salida de cada viaje (misma distribución horaria del script base)
        salidas = []
        for dia, n in zip(dias, por_dia):
            horas_dia = np.random.choice(range(24), size=n, p=self._get_hourly_distribution())
            minutos = np.random.randint(0, 60, size=n)
            salidas.extend(((dia - inicio).days * 24 + horas_dia + minutos / 60).tolist())
        salidas.sort()

        # 3) Ruta: origen y destino según la demanda de cada ciudad. Con p(origen, destino)
        #    proporcional a peso(origen) x peso(destino), lo que entra a cada ciudad es igual a
        #    lo que sale, y la flota no se acumula en un solo lugar.
        pares = [(o, d) for o in self.cities for d in self.cities if o != d]
        p_par = np.array([self.PESO_CIUDAD[o] * self.PESO_CIUDAD[d] for o, d in pares])
        p_par /= p_par.sum()
        rutas_del_par = {par: [r for r in routes if (r[1], r[2]) == par] for par in pares}

        trips = []
        reubicados = 0       # viajes en los que hubo que traer el vehículo o el conductor de otra ciudad
        for salida in tqdm(salidas, desc="Generando trips"):
            origen, destino = pares[np.random.choice(len(pares), p=p_par)]
            route_id, _, _, distance, est_duration = random.choice(rutas_del_par[(origen, destino)])
            distance, est_duration = float(distance), float(est_duration)
            o = ciudad_idx[origen]

            # Vehículo: ya comprado, libre, en la ciudad de origen (las motos solo en rutas cortas)
            apto = v_desde <= salida
            if distance > self.KM_MAXIMO_MOTO:
                apto = apto & ~v_moto
            if distance > self.KM_LARGO and random.random() < 0.75:
                apto = apto & ~v_van          # 3 de cada 4 viajes largos se reservan para camiones
            vi, salida, movido = self._elegir(apto, v_libre, v_lugar, o, salida)
            # Conductor: ya contratado, descansado y en la ciudad de origen
            ci, salida, movido_c = self._elegir(c_desde <= salida, c_libre, c_lugar, o, salida)
            reubicados += movido or movido_c

            # Duración real con variación (como el script base)
            actual_duration = est_duration * random.uniform(0.8, 1.3)
            llegada = salida + actual_duration
            v_libre[vi] = llegada + self.ALISTAMIENTO_VEHICULO_H
            c_libre[ci] = llegada + self.DESCANSO_CONDUCTOR_H
            v_lugar[vi] = c_lugar[ci] = ciudad_idx[destino]

            departure = inicio + timedelta(hours=salida)
            arrival = inicio + timedelta(hours=llegada)

            # Carga: más llenos en noviembre y diciembre, más vacíos en enero
            minimo, maximo = {11: (0.5, 0.95), 12: (0.55, 0.95), 1: (0.35, 0.8)}.get(departure.month, (0.4, 0.9))
            carga = random.uniform(minimo, maximo)
            total_weight = v_cap[vi] * carga

            # Combustible: según el tipo de vehículo y lo cargado que va (+5% si tiene más de 4 años)
            tipo = v_tipo[vi]
            fuel_consumed = distance * self.CONSUMO_100KM[tipo] / 100 * (0.85 + 0.3 * carga) * random.uniform(0.92, 1.08)
            if salida - v_desde[vi] > 4 * 365 * 24:
                fuel_consumed *= 1.05

            status = 'completed' if arrival < datetime.now() else 'in_progress'
            trips.append((
                int(v_id[vi]),
                int(c_id[ci]),
                route_id,
                departure.replace(second=0, microsecond=0),
                arrival.replace(second=0, microsecond=0) if status == 'completed' else None,
                round(float(fuel_consumed), 2),   # float(): psycopg2 no entiende np.float64
                round(float(total_weight), 2),
                status
            ))

        logging.info(f"  Viajes con vehículo o conductor traído de otra ciudad: {reubicados:,}")

        # Insertar en batches
        query = """
            INSERT INTO trips (vehicle_id, driver_id, route_id, departure_datetime,
                             arrival_datetime, fuel_consumed_liters, total_weight_kg, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """

        batch_size = 1000
        for i in range(0, len(trips), batch_size):
            batch = trips[i:i+batch_size]
            execute_batch(self.cursor, query, batch, page_size=100)
            self.connection.commit()

            if i % 10000 == 0:
                logging.info(f"  Progreso: {i}/{count} trips insertados")

        self.counters['trips'] = count
        logging.info(f" {count} viajes insertados")

    @staticmethod
    def _elegir(apto, libre, lugar, ciudad, salida):
        """Elige al azar un vehículo o conductor apto, libre a la hora de salida y que esté en la ciudad.
        Si no hay ninguno en esa ciudad, usa uno libre de otra (se reubica). Si no hay ninguno libre,
        el viaje espera al primero que se libere. Devuelve (índice, hora de salida, si se reubicó)."""
        libres = apto & (libre <= salida)
        aca = np.flatnonzero(libres & (lugar == ciudad))
        if len(aca):
            return int(np.random.choice(aca)), salida, False
        otros = np.flatnonzero(libres)
        if len(otros):
            return int(np.random.choice(otros)), salida, True
        candidatos = np.flatnonzero(apto)
        i = int(candidatos[np.argmin(libre[candidatos])])
        return i, float(libre[i]), True

    def _get_hourly_distribution(self):
        """Distribución de probabilidad por hora del día"""
        # Más viajes en horario laboral
        probs = np.ones(24) * 0.02  # Base 2%
        probs[6:20] = 0.06  # 6am-8pm más actividad
        probs[8:12] = 0.08  # 8am-12pm pico mañana
        probs[14:18] = 0.07  # 2pm-6pm pico tarde
        return probs / probs.sum()
    
    # MEJORA: la probabilidad de llegar tarde depende de causas reales (en el script base era 10% fijo).
    # Se suman "puntos de riesgo" en escala logit y se convierten en probabilidad.
    RIESGO_CIUDAD = {'Bogotá': 0.45, 'Cali': 0.15, 'Medellín': 0.0, 'Barranquilla': -0.1, 'Cartagena': 0.0}
    CIUDADES_CARIBE = ('Barranquilla', 'Cartagena')

    def _prob_retraso(self, ciudad, cuando, km, dias_conductor, anios_vehiculo, habilidad):
        z = -3.0
        z += self.RIESGO_CIUDAD[ciudad]                               # tráfico de la ciudad
        if ciudad in self.CIUDADES_CARIBE and cuando.month in (9, 10, 11):
            z += 0.9                                                  # temporada de lluvias en el Caribe
        elif ciudad not in self.CIUDADES_CARIBE and cuando.month in (4, 5, 10, 11):
            z += 0.35                                                 # lluvias en la zona andina
        if cuando.month == 12:
            z += 0.45                                                 # pico de Navidad
        if ciudad not in self.CIUDADES_CARIBE and (6 <= cuando.hour < 9 or 17 <= cuando.hour < 20):
            z += 0.5                                                  # hora pico en las ciudades grandes
        z += 0.3 * km / 500                                           # rutas largas acumulan imprevistos
        if dias_conductor < 180:
            z += 0.6                                                  # conductor con menos de 6 meses
        if anios_vehiculo >= 4:
            z += 0.3                                                  # vehículo viejo
        z += habilidad                                                # cada conductor es distinto
        return 1 / (1 + np.exp(-z))

    def _clientes(self):
        """Cartera de clientes por ciudad: 150 empresas que piden seguido y 12.000 personas.
        En el script base cada entrega tenía un cliente nuevo inventado, y nadie repetía."""
        rubros = ['Distribuidora', 'Ferretería', 'Droguería', 'Almacenes', 'Comercializadora',
                  'Supermercado', 'Importadora', 'Textiles', 'Repuestos', 'Muebles']
        formas = ['S.A.S.', 'S.A.S.', 'S.A.S.', 'Ltda.', 'S.A.']
        cartera = {}
        for ciudad in self.cities:
            empresas = [(f"{random.choice(rubros)} {fake.last_name()} {random.choice(formas)}",
                         f"{fake.street_address()}, {ciudad}") for _ in range(150)]
            personas = [(fake.name(), f"{fake.street_address()}, {ciudad}") for _ in range(12000)]
            # Pocas empresas concentran muchos pedidos (ley de potencias, como en la realidad)
            peso = 1 / np.arange(1, 151) ** 0.8
            cartera[ciudad] = (empresas, peso / peso.sum(), personas)
        return cartera

    def generate_deliveries(self, count=400000):
        """Generar 400000 entregas (promedio 4 por viaje)"""
        logging.info(f"Generando {count} entregas...")

        # Para cada viaje: horarios, peso, ciudad y distancia de la ruta, y la fecha de
        # contratación del conductor y de compra del vehículo (para el riesgo de retraso)
        self.cursor.execute("""
            SELECT t.trip_id,
                   t.departure_datetime,
                   t.arrival_datetime,
                   t.total_weight_kg,
                   r.destination_city,
                   r.distance_km,
                   t.driver_id,
                   d.hire_date,
                   v.acquisition_date
            FROM trips t
            JOIN routes r   ON t.route_id = r.route_id
            JOIN drivers d  ON t.driver_id = d.driver_id
            JOIN vehicles v ON t.vehicle_id = v.vehicle_id
            ORDER BY t.trip_id
        """)
        trips_data = self.cursor.fetchall()

        # Habilidad de cada conductor (no se guarda en la base: es la causa "oculta" que el
        # análisis tiene que descubrir). La mayoría es normal; 1 de cada 20 es muy impuntual.
        rng = np.random.default_rng(7)
        ids = sorted({t[6] for t in trips_data})
        habilidad = dict(zip(ids, rng.normal(0, 0.4, len(ids)) + np.where(rng.random(len(ids)) < 0.05, 0.8, 0)))
        cartera = self._clientes()

        deliveries = []
        delivery_counter = 0

        # MEJORA: primero sorteamos cuántas entregas tiene CADA viaje (2-6, lo más probable 4)
        # y después ajustamos de a una para que la suma dé exactamente `count`.
        # Así ningún viaje queda sin entregas (antes, al llegar al tope se cortaba y los
        # últimos viajes quedaban vacíos).
        entregas_por_viaje = np.random.choice([2, 3, 4, 5, 6], size=len(trips_data),
                                              p=[0.1, 0.2, 0.4, 0.2, 0.1])
        while entregas_por_viaje.sum() > count:   # sobran: restar 1 a un viaje que tenga más de 2
            i = np.random.randint(len(entregas_por_viaje))
            if entregas_por_viaje[i] > 2:
                entregas_por_viaje[i] -= 1
        while entregas_por_viaje.sum() < count:   # faltan: sumar 1 a un viaje que tenga menos de 6
            i = np.random.randint(len(entregas_por_viaje))
            if entregas_por_viaje[i] < 6:
                entregas_por_viaje[i] += 1

        for n_trip, (trip_id, departure, arrival, total_weight, city, km, driver_id,
                     hire_date, acquisition_date) in enumerate(tqdm(trips_data, desc="Generando deliveries")):
            num_deliveries = int(entregas_por_viaje[n_trip])
            weights = self._distribute_weight(float(total_weight), num_deliveries)

            # Tiempo entre entregas
            if arrival:
                delivery_duration = (arrival - departure).total_seconds() / 3600
                time_per_delivery = delivery_duration / num_deliveries
            else:
                time_per_delivery = 0.5  # 30 minutos promedio

            dias_conductor = (departure.date() - hire_date).days
            anios_vehiculo = (departure.date() - acquisition_date).days / 365
            empresas, peso_empresas, personas = cartera[city]

            for i in range(num_deliveries):
                tracking_number = f"FL{datetime.now().year}{str(delivery_counter+1).zfill(8)}"
                # 30% de las entregas son a empresas de la cartera; el resto, a personas
                if random.random() < 0.30:
                    customer_name, delivery_address = empresas[np.random.choice(150, p=peso_empresas)]
                else:
                    customer_name, delivery_address = random.choice(personas)
                # CORRECCIÓN: float() porque con NumPy 2 psycopg2 manda "np.float64(...)" y falla
                package_weight = float(weights[i])

                # Horario programado y real
                scheduled = departure + timedelta(hours=time_per_delivery * (i + 0.5))

                if arrival:
                    p_tarde = self._prob_retraso(city, scheduled, float(km), dias_conductor,
                                                 anios_vehiculo, habilidad[driver_id])
                    if random.random() >= p_tarde:
                        delivered = scheduled + timedelta(minutes=random.randint(-30, 30))
                    else:
                        # Retraso: pasa la tolerancia de 30 min; la mayoría por poco, algunos por horas
                        delivered = scheduled + timedelta(minutes=int(31 + min(np.random.exponential(55), 300)))

                    # MEJORA: una entrega no puede ocurrir antes de que salga el camión
                    delivered = max(delivered, departure + timedelta(minutes=5))

                    delivery_status = 'delivered'
                    signature = random.random() < 0.95  # 95% con firma
                else:
                    delivered = None
                    delivery_status = 'pending'
                    signature = False

                deliveries.append((
                    trip_id,
                    tracking_number,
                    customer_name,
                    delivery_address,
                    round(package_weight, 2),
                    scheduled,
                    delivered,
                    delivery_status,
                    signature
                ))

                delivery_counter += 1

                if delivery_counter >= count:  # CORRECCIÓN: con > salían 400.001
                    break

            if delivery_counter >= count:
                break

        # Insertar en batches
        query = """
            INSERT INTO deliveries (trip_id, tracking_number, customer_name,
                                  delivery_address, package_weight_kg, scheduled_datetime,
                                  delivered_datetime, delivery_status, recipient_signature)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """

        batch_size = 1000
        for i in range(0, len(deliveries), batch_size):
            batch = deliveries[i:i+batch_size]
            execute_batch(self.cursor, query, batch, page_size=100)
            self.connection.commit()

            if i % 50000 == 0:
                logging.info(f"  Progreso: {i}/{len(deliveries)} deliveries insertados")

        self.counters['deliveries'] = len(deliveries)
        logging.info(f" {len(deliveries)} entregas insertadas")

    def _distribute_weight(self, total_weight, num_packages):
        """Distribuir peso total entre paquetes de manera realista"""
        # Generar pesos aleatorios
        weights = np.random.exponential(scale=1.0, size=num_packages)
        # Normalizar para que sumen el total
        weights = weights / weights.sum() * total_weight * 0.95  # 95% del peso total
        # Mínimo 0.5kg por paquete
        weights = np.maximum(weights, 0.5)
        return weights
    
    def generate_maintenance(self, count=5000):
        """Generar 5000 registros de mantenimiento"""
        logging.info(f"Generando {count} registros de mantenimiento...")
        
        # Obtener información de vehículos y sus viajes:
        # por vehículo, cuántos viajes hizo y la fecha del primero y del último.
        # Solo vehículos con viajes (INNER JOIN): sin viajes no hay período para repartir.
        self.cursor.execute("""
            SELECT v.vehicle_id,
                   v.vehicle_type,
                   v.acquisition_date,
                   COUNT(t.trip_id)           AS trip_count,
                   MIN(t.departure_datetime)  AS first_trip,
                   MAX(t.departure_datetime)  AS last_trip
            FROM vehicles v
            JOIN trips t ON t.vehicle_id = v.vehicle_id
            GROUP BY v.vehicle_id, v.vehicle_type, v.acquisition_date
            ORDER BY v.vehicle_id
        """)
        vehicle_stats = self.cursor.fetchall()
        
        maintenance_types = [
            ('Cambio de aceite', 150000, 30),
            ('Revisión de frenos', 250000, 60),
            ('Cambio de llantas', 450000, 90),
            ('Mantenimiento general', 350000, 45),
            ('Revisión de motor', 500000, 60),
            ('Alineación y balanceo', 180000, 30)
        ]
        
        maintenance_records = []
        
        # MEJORA: un camión grande cuesta más de mantener que una moto, y un vehículo viejo más que uno nuevo
        factor_tipo = {'Camión Grande': 1.6, 'Camión Mediano': 1.3, 'Van': 1.0, 'Motocicleta': 0.35}

        for vehicle_id, vehicle_type, acquisition_date, trip_count, first_trip, last_trip in vehicle_stats:
            # Número de mantenimientos basado en viajes (cada ~20 viajes)
            # MEJORA: redondeo hacia arriba. Con // (hacia abajo) cada vehículo "pierde"
            # medio mantenimiento en promedio y el total queda por debajo de 5.000.
            num_maintenance = max(1, -(-trip_count // 20))
            
            if first_trip and last_trip:
                # Distribuir mantenimientos en el período de operación
                operation_days = (last_trip - first_trip).days
                
                for i in range(min(num_maintenance, count - len(maintenance_records))):
                    # Fecha de mantenimiento distribuida
                    days_offset = int(operation_days * (i + 1) / (num_maintenance + 1))
                    maintenance_date = (first_trip + timedelta(days=days_offset)).date()
                    
                    # Tipo de mantenimiento
                    maint_type, base_cost, days_next = random.choice(maintenance_types)
                    
                    # Costo con variación
                    cost = base_cost * random.uniform(0.8, 1.2) * factor_tipo[vehicle_type]
                    cost *= 1 + 0.08 * (maintenance_date - acquisition_date).days / 365
                    
                    # Descripción
                    description = f"{maint_type} programado para {maintenance_date.strftime('%Y-%m-%d')}"
                    
                    # Próximo mantenimiento
                    next_maintenance = maintenance_date + timedelta(days=days_next)
                    
                    # Técnico
                    performed_by = f"{fake.first_name()} {fake.last_name()}"
                    
                    maintenance_records.append((
                        vehicle_id,
                        maintenance_date,
                        maint_type,
                        description,
                        round(cost, 2),
                        next_maintenance,
                        performed_by
                    ))
                    
                    if len(maintenance_records) >= count:
                        break
        
        # Insertar en batch
        query = """
            INSERT INTO maintenance (vehicle_id, maintenance_date, maintenance_type,
                                   description, cost, next_maintenance_date, performed_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        execute_batch(self.cursor, query, maintenance_records[:count], page_size=100)
        self.connection.commit()
        self.counters['maintenance'] = min(len(maintenance_records), count)
        logging.info(f" {self.counters['maintenance']} mantenimientos insertados")
    
    def validate_data_quality(self):
        """Validar integridad y calidad de datos"""
        logging.info("\n VALIDANDO CALIDAD DE DATOS...")
        
        validations = {
            "Integridad referencial - Trips sin vehículo válido": """
                SELECT COUNT(*) FROM trips t 
                LEFT JOIN vehicles v ON t.vehicle_id = v.vehicle_id 
                WHERE v.vehicle_id IS NULL
            """,
            "Integridad referencial - Deliveries sin trip válido": """
                SELECT COUNT(*) FROM deliveries d 
                LEFT JOIN trips t ON d.trip_id = t.trip_id 
                WHERE t.trip_id IS NULL
            """,
            "Consistencia temporal - Trips con arrival < departure": """
                SELECT COUNT(*) FROM trips 
                WHERE arrival_datetime IS NOT NULL 
                AND arrival_datetime < departure_datetime
            """,
            "Consistencia de peso - Trips excediendo capacidad": """
                SELECT COUNT(*) FROM trips t 
                JOIN vehicles v ON t.vehicle_id = v.vehicle_id 
                WHERE t.total_weight_kg > v.capacity_kg
            """,
            "Entregas sin tracking number": """
                SELECT COUNT(*) FROM deliveries
                WHERE tracking_number IS NULL OR tracking_number = ''
            """,
            # MEJORA: validaciones extra de coherencia entre tablas
            "Integridad referencial - Maintenance sin vehículo válido": """
                SELECT COUNT(*) FROM maintenance m
                LEFT JOIN vehicles v ON m.vehicle_id = v.vehicle_id
                WHERE v.vehicle_id IS NULL
            """,
            "Coherencia - Viajes antes de contratar al conductor": """
                SELECT COUNT(*) FROM trips t
                JOIN drivers d ON t.driver_id = d.driver_id
                WHERE t.departure_datetime::date < d.hire_date
            """,
            "Coherencia - Viajes antes de comprar el vehículo": """
                SELECT COUNT(*) FROM trips t
                JOIN vehicles v ON t.vehicle_id = v.vehicle_id
                WHERE t.departure_datetime::date < v.acquisition_date
            """,
            "Horarios - Conductores con viajes superpuestos o sin descanso": """
                SELECT COUNT(*) FROM (
                    SELECT departure_datetime,
                           LAG(arrival_datetime) OVER (PARTITION BY driver_id ORDER BY departure_datetime) AS llegada_anterior
                    FROM trips) x
                WHERE departure_datetime < llegada_anterior + INTERVAL '8 hours'
            """,
            "Horarios - Vehículos en dos viajes a la vez": """
                SELECT COUNT(*) FROM (
                    SELECT departure_datetime,
                           LAG(arrival_datetime) OVER (PARTITION BY vehicle_id ORDER BY departure_datetime) AS llegada_anterior
                    FROM trips) x
                WHERE departure_datetime < llegada_anterior
            """,
            "Coherencia - Motos en rutas de más de 200 km": """
                SELECT COUNT(*) FROM trips t
                JOIN vehicles v ON t.vehicle_id = v.vehicle_id
                JOIN routes r ON t.route_id = r.route_id
                WHERE v.vehicle_type = 'Motocicleta' AND r.distance_km > 200
            """,
            "Coherencia - Entregas antes de la salida del viaje": """
                SELECT COUNT(*) FROM deliveries d
                JOIN trips t ON d.trip_id = t.trip_id
                WHERE d.delivered_datetime < t.departure_datetime
            """
        }
        
        all_valid = True
        for description, query in validations.items():
            self.cursor.execute(query)
            count = self.cursor.fetchone()[0]
            if count > 0:
                logging.warning(f"    {description}: {count} registros")
                all_valid = False
            else:
                logging.info(f"   {description}: OK")
        
        return all_valid
    
    def generate_summary_report(self):
        """Generar reporte resumen de datos generados"""
        logging.info("\n RESUMEN DE GENERACIÓN DE DATOS")
        logging.info("="*50)
        
        # Conteos finales
        tables = ['vehicles', 'drivers', 'routes', 'trips', 'deliveries', 'maintenance']
        total_records = 0
        
        for table in tables:
            self.cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = self.cursor.fetchone()[0]
            logging.info(f"  {table}: {count:,} registros")
            total_records += count
        
        logging.info(f"\n  TOTAL: {total_records:,} registros")
        
        # Estadísticas adicionales
        self.cursor.execute("""
            SELECT 
                AVG(delivery_count) as avg_deliveries_per_trip,
                MIN(delivery_count) as min_deliveries,
                MAX(delivery_count) as max_deliveries
            FROM (
                SELECT trip_id, COUNT(*) as delivery_count
                FROM deliveries
                GROUP BY trip_id
            ) as delivery_stats
        """)
        
        avg_del, min_del, max_del = self.cursor.fetchone()
        logging.info(f"\n  Entregas por viaje: AVG={avg_del:.1f}, MIN={min_del}, MAX={max_del}")
        
        # Guardar resumen en JSON
        summary = {
            'generation_date': datetime.now().isoformat(),
            'total_records': total_records,
            'table_counts': self.counters,
            'validations_passed': self.validate_data_quality()
        }
        
        with open('generation_summary.json', 'w') as f:
            json.dump(summary, f, indent=2)
        
        logging.info("\n Resumen guardado en generation_summary.json")
    
    def close(self):
        """Cerrar conexión"""
        if self.cursor:
            self.cursor.close()
        if self.connection:
            self.connection.close()
        logging.info("\n Conexión cerrada")


def main():
    """Función principal"""
    print(" FLEETLOGIX - Generación de Datos Masivos")
    print("="*60)
    print("Objetivo: Generar 505000+ registros manteniendo integridad")
    print("="*60)
    
    generator = DataGenerator(DB_CONFIG)
    
    try:
        if not generator.connect():
            return
        
        # Generar datos en orden (respetando foreign keys)
        generator.generate_vehicles(200)
        generator.generate_drivers(400)
        generator.generate_routes(50)
        generator.generate_trips(100000)
        generator.generate_deliveries(400000)
        generator.generate_maintenance(5000)
        
        # Validar y generar reporte
        generator.generate_summary_report()
        
    except Exception as e:
        logging.error(f" Error durante la generación: {e}")
        generator.connection.rollback()
    finally:
        generator.close()


if __name__ == "__main__":
    main()