# Proyecto Integrador M2 - FleetLogix

**Tomás Babot** · Data Science · Soy Henry

FleetLogix es una empresa de transporte y logística con 200 vehículos que opera en 5 ciudades de Colombia.
Trabajaba con sistemas viejos y planillas de cálculo, y la consigna era modernizar toda su infraestructura de datos.
Lo hice en 4 avances:

| Avance | Qué hice | Resultado |
|---|---|---|
| 1 | Armé la base PostgreSQL y la llené con datos sintéticos | 505.650 registros, los 12 controles de calidad dieron 0 errores |
| 2 | Analicé 8 queries de negocio y las optimicé con índices | el tiempo total bajó 74,4% con 5 índices (77,3% con el ajuste para SSD) |
| 3 | Diseñé un Data Warehouse en Snowflake y un ETL automático | cargué 399.994 hechos y coinciden con la base de origen |
| 4 | Analicé y mejoré la arquitectura en AWS | probé todo en un AWS simulado; el costo estimado es de US$ 35 por mes (el tope era US$ 50) |

## 1. Cómo está organizado el repositorio

```
ProyectoM2_TomasBabot/
├── 1. Notebooks/                      un notebook por avance, ya ejecutado
│   ├── Avance_1_DataGeneration.ipynb
│   ├── Avance_2_SQLAnalysis.ipynb
│   ├── Avance_3_DataWarehouse.ipynb
│   └── Avance_4_CloudArchitecture.ipynb
├── 2. Scripts/
│   ├── 00_fleetlogix_db_schema.sql    esquema base (6 tablas) que dio Henry
│   ├── 01_data_generation.py          genera los 505.650 registros
│   ├── 02_queries_analysis.sql        las 8 queries que elegí (+ la 9 corregida)
│   ├── 03_optimization_indexes.sql    los 5 índices
│   ├── 04_dimensional_model.sql       modelo estrella en Snowflake
│   ├── 05_etl_pipeline.py             ETL de PostgreSQL a Snowflake
│   ├── 06_aws_setup.py                creación de la infraestructura AWS (mi versión corregida)
│   ├── lambda_functions/              las 3 funciones Lambda
│   └── aws_architecture_diagram.png   diagrama de arquitectura
├── 3. Documentación/
│   ├── README.pdf
│   ├── Manual_Consultas_SQL.pdf
│   ├── Arquitectura_Tecnica.pdf
│   ├── data_dictionary.xlsx
│   ├── img/                           diagramas y gráficos
│   └── aws_simulacion/                archivos que genera la simulación de AWS
├── requirements.txt
└── .env.example                       variables de conexión (el .env real no lo subo)
```

## 2. Cómo correrlo

Necesitás Python 3.11, PostgreSQL (yo usé la versión 18) y una cuenta de Snowflake (sirve la de prueba).

```bash
pip install -r requirements.txt
cp .env.example .env          # y completar los datos de conexión
```

1. Crear la base y las tablas: `createdb fleetlogix` y después `psql -d fleetlogix -f "2. Scripts/00_fleetlogix_db_schema.sql"`.
2. Generar los datos: `cd "2. Scripts"` y `python 01_data_generation.py` (tarda unos 2 minutos).
3. Crear los índices: `psql -d fleetlogix -f 03_optimization_indexes.sql`. El notebook del Avance 2 los borra y los vuelve a crear para medir.
4. Snowflake: correr `04_dimensional_model.sql` en una hoja de Snowflake.
5. ETL: `python 05_etl_pipeline.py --full` para la carga inicial. Para que corra todos los días: `python 05_etl_pipeline.py --schedule`,
   o con cron: `0 2 * * * cd ".../2. Scripts" && python 05_etl_pipeline.py`.
6. AWS: no hace falta tener cuenta, porque el notebook del Avance 4 corre `06_aws_setup.py` y las Lambda contra un AWS simulado con la librería `moto`.
7. Abrir los notebooks de `1. Notebooks/` en orden.

**Credenciales:** no hay ninguna escrita en el código. Se leen del archivo `.env`, que está en el `.gitignore`.
Para Snowflake usé autenticación con par de llaves (la llave privada está en `keys/`, que tampoco se sube).
Lo hice así porque entro a Snowflake con Google y no tengo contraseña.

## 3. Avance 1: modelo relacional y generación de datos

**Modelo:** son 6 tablas. 3 maestras (`vehicles`, `drivers`, `routes`) y 3 transaccionales (`trips`, `deliveries`, `maintenance`),
unidas con 5 relaciones 1 a N. La tabla central es `trips`, porque une vehículo, conductor y ruta, y de ella dependen las entregas.
En el notebook está el diagrama entidad-relación y el análisis de restricciones y cardinalidades.

**Patrones de negocio que encontré:**
- Un viaje tiene varias entregas, y el peso total no puede pasar la capacidad del vehículo.
- Cada viaje y cada entrega pasan por distintos estados.
- La puntualidad se mide comparando la hora programada con la real.
- Hay mantenimiento preventivo y licencias que vencen.

**Mejoras que propongo sin cambiar el modelo:**
- Agregar restricciones `CHECK` para los estados y valores.
- Poner `NOT NULL` en las claves foráneas.
- Crear índices en las claves foráneas, porque PostgreSQL no los crea solo.
- Agregar una tabla de clientes. Esto lo resolví en el DW con `dim_customer`.

**Generación de datos (`01_data_generation.py`):** partí del script de Henry. Usé Faker en español de Colombia,
inserción por lotes con `execute_batch` y una validación al final. Le corregí 8 problemas al script original, por ejemplo:
- Generaba 48 rutas en vez de 50.
- Los viajes terminaban un mes antes de hoy, porque redondeaba el paso de tiempo.
- Al cortar en 400.000 entregas, los últimos viajes quedaban sin ninguna.
- Podía asignarle viajes a un conductor antes de su fecha de contratación.

| Tabla | Registros |
|---|---|
| vehicles | 200 |
| drivers | 400 |
| routes | 50 |
| trips | 100.000 (2 años de operación) |
| deliveries | 400.000 (de 2 a 6 por viaje, promedio 4) |
| maintenance | 5.000 |
| **Total** | **505.650** |

Pasan las 12 reglas de calidad: integridad referencial, fechas coherentes, capacidad y unicidad.
Las distribuciones dan realistas: la mayoría de los viajes salen entre las 8 y las 11, y alrededor del 90% de las entregas llegan a tiempo.

## 4. Avance 2: análisis SQL y optimización

Elegí las queries 1, 2 y 3 (básicas), 4, 5 y 7 (intermedias) y 9 y 10 (complejas).
Para cada una escribí qué problema de negocio responde y cómo interpreto el resultado. El detalle está en `Manual_Consultas_SQL.pdf`.

**Lo más importante que encontré:** la Query 9 original une viajes y mantenimientos al mismo tiempo, entonces cada viaje
se repite una vez por cada mantenimiento del vehículo (es un *fan-out*). Por eso infla los kilómetros unas 33 veces y los costos más de 600 veces.
Escribí una versión corregida (9b): el costo total cierra exacto con la base y los kilómetros también, salvo los de 22 vehículos que nunca tuvieron mantenimiento (no tienen costo para dividir). Además es unas 150 veces más rápida.

**Índices (`03_optimization_indexes.sql`):** creé 5:
- `deliveries(trip_id)`
- `maintenance(vehicle_id)`
- `trips(vehicle_id)`, solo para viajes completados
- `trips(status)`
- `drivers(license_expiry)`

Para medir usé `EXPLAIN ANALYZE` y me quedé con la mediana de 6 corridas:

| | Sin índices | Con índices | Mejora |
|---|---|---|---|
| Total de las 8 queries | 5.159 ms | 1.319 ms | **74,4%** |
| Con el ajuste para SSD (`random_page_cost = 1.1`) | | 1.171 ms | **77,3%** |

Las queries 5 y 7 no mejoran, y tiene sentido: las dos leen los 100.000 viajes completos, y para eso lo más rápido es leer la tabla entera.
Un índice ayuda cuando se necesita una parte chica de la tabla.

## 5. Avance 3: Data Warehouse en Snowflake y ETL

**Modelo estrella** (`FLEETLOGIX_DW.ANALYTICS`): la tabla de hechos `fact_deliveries` tiene una fila por entrega completada.
Tiene 6 dimensiones: fecha, hora, vehículo, conductor, ruta y cliente. Las decisiones que tomé:
- Usar claves sustitutas.
- Guardar el historial de los conductores en `dim_driver` (SCD tipo 2).
- Repartir el combustible y la distancia de cada viaje entre sus entregas, para poder sumarlos sin contar un viaje varias veces.
- Usar un warehouse X-Small que se apaga a los 60 segundos, para gastar poco.
- Activar Time Travel de 30 días.
- Crear vistas seguras por rol (Ventas y Operaciones).

**ETL (`05_etl_pipeline.py`):** extrae de PostgreSQL, transforma con pandas y carga con `write_pandas`.
En la transformación calculo 7 métricas, como entregas por hora y costo e ingreso por entrega, y hago controles de calidad.
Tiene tres modos: carga completa, incremental (el día anterior) y programada todos los días a las 02:00.
Si corro dos veces el mismo día no se duplican datos.

| Lo que verifiqué | Resultado |
|---|---|
| Filas cargadas | 399.994 (todas las entregas completadas) |
| Hechos sin su dimensión | 0 |
| Peso total y % a tiempo contra PostgreSQL | iguales |
| Volver a cargar el mismo día | no duplica |
| Cambiar el teléfono de un conductor | se crea una versión nueva en `dim_driver` y la anterior queda cerrada |
| Carga inicial completa | 66 segundos |

Las capturas de las tablas en Snowflake están en el notebook del Avance 3, en `3. Documentación/img/` y al final de este documento.

## 6. Avance 4: arquitectura en AWS

El diagrama (`2. Scripts/aws_architecture_diagram.png`) tiene tres partes:
- **Tiempo real:** API Gateway, las 3 Lambda y DynamoDB, más SNS para las alertas.
- **Transaccional:** RDS PostgreSQL en una subred privada.
- **Analítica:** una EC2 que corre el ETL de noche hacia Snowflake. S3 guarda todo el histórico organizado por fecha (`raw-data/AAAA/MM/DD/`) y los backups.

A todo eso se suman CloudWatch, IAM, KMS, Secrets Manager y Budgets.

En `Arquitectura_Tecnica.pdf` respondo las preguntas de la consigna:
- **a)** Qué recursos crea cada script.
- **b)** Cómo funciona `verificar-entrega`.
- **c)** Cómo funciona `migrar_datos_postgresql()`.

Además encontré 11 problemas en los scripts base, por ejemplo:
- La contraseña de la base estaba escrita en el código.
- La base era pública.
- Las Lambda tenían acceso total a DynamoDB, S3 y SNS.
- Las Lambda fallaban con eventos reales de API Gateway y al guardar números decimales en DynamoDB.

Los corregí todos y lo probé en una simulación con `moto`: se crea la infraestructura, pruebo las 3 Lambda y la alerta
de desvío llega por SNS. También definí 8 alarmas de CloudWatch.

**Costo estimado: US$ 35,03 por mes.** Lo que más ahorra es no usar NAT Gateway, que sale unos US$ 32 por mes.
Para eso dejé las Lambda fuera de la VPC y el ETL corre en una EC2 chica.

## 7. Decisiones y limitaciones

- **Elegí estrella y no copo de nieve** porque los analistas necesitan menos JOIN y Snowflake responde más rápido.
- **DynamoDB para el tiempo real y RDS para lo transaccional:** DynamoDB responde en milisegundos buscando por clave y se paga por uso.
  RDS mantiene la integridad relacional del modelo original.
- **Datos sintéticos:** el script base calcula el combustible solo con la distancia, así que una moto "gasta" lo mismo que un camión.
  Por eso la moto aparece con pérdida en el análisis de rentabilidad. El tipo de cliente (Individual, Empresa, Gobierno) no existe
  en la base de origen y lo asigné de forma sintética.
- **Precios de AWS:** usé los precios de lista de us-east-1 y son aproximados. Antes de implementar habría que confirmarlos con AWS Pricing Calculator.

## 8. Herramientas

Python (pandas, numpy, Faker, psycopg2, SQLAlchemy, matplotlib, schedule, boto3, moto), PostgreSQL 18, Snowflake,
AWS (API Gateway, Lambda, DynamoDB, RDS, S3, SNS, CloudWatch, IAM, KMS, Secrets Manager), Jupyter y Git.
