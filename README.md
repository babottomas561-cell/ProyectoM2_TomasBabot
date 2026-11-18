# Proyecto Integrador M2 - FleetLogix

**Tomás Babot** · Data Science · Soy Henry

**Tablero online:** https://fleetlogix-tomasbabot.streamlit.app

FleetLogix es una empresa de transporte y logística con 200 vehículos que opera en 5 ciudades de Colombia.
Trabajaba con sistemas viejos y planillas de cálculo, y la consigna era modernizar toda su infraestructura de datos.
Lo hice en 4 avances:

| Avance | Qué hice | Resultado |
|---|---|---|
| 1 | Armé la base PostgreSQL y la llené con datos sintéticos | 505.650 registros, los 12 controles de calidad dieron 0 errores |
| 2 | Analicé 8 queries de negocio y las optimicé con índices | el tiempo total bajó 74,6% con 5 índices (76,9% con el ajuste para SSD) |
| 3 | Diseñé un Data Warehouse en Snowflake y un ETL automático | cargué 399.996 hechos y coinciden con la base de origen |
| 4 | Analicé y mejoré la arquitectura en AWS | probé todo en un AWS simulado; el costo estimado es de US$ 35 por mes (el tope era US$ 50) |
| Extra | Armé un tablero en Streamlit con los datos del Data Warehouse | 7 páginas con filtros, comparación contra el año anterior, descarga de datos y un explorador libre |

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
│   ├── 07_export_dashboard_data.py    baja de Snowflake los datos que usa el tablero
│   ├── lambda_functions/              las 3 funciones Lambda
│   └── aws_architecture_diagram.png   diagrama de arquitectura
├── 3. Documentación/
│   ├── README.pdf
│   ├── Manual_Consultas_SQL.pdf
│   ├── Arquitectura_Tecnica.pdf
│   ├── data_dictionary.xlsx
│   ├── img/                           diagramas y gráficos
│   └── aws_simulacion/                archivos que genera la simulación de AWS
├── dashboard/                         tablero en Streamlit (extra)
│   ├── app.py
│   ├── consultas.py                   las consultas al Data Warehouse
│   ├── usuario_lectura_snowflake.sql  usuario de solo lectura que usa el tablero
│   ├── data/                          copia de respaldo del Data Warehouse (parquet)
│   └── requirements.txt
├── .streamlit/config.toml             colores y fuente del tablero
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
inserción por lotes con `execute_batch`, un log de la carga y controles al final: 12 validaciones de calidad y 8 distribuciones
que reviso con pandas contra un rango esperado (por ejemplo, entre 80% y 95% de entregas a tiempo). Le corregí 8 problemas al script original, por ejemplo:
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

Pasan las 12 reglas de calidad: integridad referencial, fechas coherentes, capacidad, que ningún conductor ni vehículo
esté en dos viajes a la vez y que las motos no hagan rutas largas.

**Patrones de negocio que le agregué al generador.** El script base reparte todo al azar y en forma pareja: el mismo volumen
todos los días y 90% a tiempo en todas las ciudades. Con datos así el análisis no encuentra nada, así que agregué supuestos
de una operación real en Colombia:

| Patrón | Cómo lo armé |
|---|---|
| Ciudades | Bogotá es el mayor mercado (30% de la demanda) y Cartagena el menor (14%) |
| Estacionalidad | pico en diciembre (+30%) y noviembre, baja en enero; el domingo casi no se trabaja; feriados con poco volumen |
| Crecimiento | la empresa crece 12% por año |
| Flota | cada viaje usa un vehículo y un conductor libres en la ciudad de origen, con 8 h de descanso para el conductor; las motos no hacen rutas de más de 200 km y las rutas largas casi siempre van en camión |
| Combustible | según el tipo de vehículo (de 3,5 L cada 100 km la moto a 32 L el camión grande) y lo cargado que va |
| Retrasos | dependen del tráfico de cada ciudad, las lluvias (el Caribe en septiembre a noviembre), diciembre, la hora pico, el largo de la ruta, los conductores con menos de 6 meses y los vehículos viejos |
| Clientes | 150 empresas por ciudad que piden seguido, unas pocas concentran muchos pedidos, y 12.000 personas |
| Mantenimiento | un camión grande cuesta más de mantener que una moto, y el costo sube con los años del vehículo |

Con esto el 88% de las entregas llega a tiempo, pero Bogotá queda en 85%, la costa llega a bajar a 81% en la temporada de lluvias
y los conductores nuevos llegan a tiempo 82% contra 89% del resto. Todo el detalle está en el notebook del Avance 1.

## 4. Avance 2: análisis SQL y optimización

Elegí las queries 1, 2 y 3 (básicas), 4, 5 y 7 (intermedias) y 9 y 10 (complejas).
Para cada una escribí qué problema de negocio responde y cómo interpreto el resultado. El detalle está en `Manual_Consultas_SQL.pdf`.

**Lo más importante que encontré:** la Query 9 original une viajes y mantenimientos al mismo tiempo, entonces cada viaje
se repite una vez por cada mantenimiento del vehículo (es un *fan-out*). Por eso infla los kilómetros unas 36 veces y los costos más de 700 veces.
Escribí una versión corregida (9b): el costo total cierra exacto con la base y los kilómetros también, salvo los de 3 vehículos que nunca tuvieron mantenimiento (no tienen costo para dividir). Además es unas 150 veces más rápida.

**Índices (`03_optimization_indexes.sql`):** creé 5:
- `deliveries(trip_id)`
- `maintenance(vehicle_id)`
- `trips(vehicle_id)`, solo para viajes completados
- `trips(status)`
- `drivers(license_expiry)`

Para medir usé `EXPLAIN ANALYZE` y me quedé con la mediana de 6 corridas:

| | Sin índices | Con índices | Mejora |
|---|---|---|---|
| Total de las 8 queries | 5.401 ms | 1.372 ms | **74,6%** |
| Con el ajuste para SSD (`random_page_cost = 1.1`) | | 1.246 ms | **76,9%** |

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
| Filas cargadas | 399.996 (todas las entregas completadas) |
| Hechos sin su dimensión | 0 |
| Peso total y % a tiempo contra PostgreSQL | iguales |
| Volver a cargar el mismo día | no duplica |
| Cambiar el teléfono de un conductor | se crea una versión nueva en `dim_driver` y la anterior queda cerrada |
| Carga inicial completa | 74 segundos |

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

## 7. Extra: tablero en Streamlit

![Tablero FleetLogix](3.%20Documentación/img/dashboard_resumen.png)

Para mostrar los resultados armé un tablero con Streamlit y Plotly, publicado en Streamlit Community Cloud:
**https://fleetlogix-tomasbabot.streamlit.app**. No lee la base operativa: **lee el Data Warehouse de Snowflake en vivo**.
Corre dos consultas sobre el modelo estrella (`dashboard/consultas.py`): resume `fact_deliveries` por día, ciudad,
tipo de vehículo, turno y ciudad de origen (unas 90.000 filas) y calcula los totales de cada conductor.

- **Seguridad:** el tablero no usa mi usuario. Creé uno de solo lectura (`usuario_lectura_snowflake.sql`) que solo puede
  hacer SELECT en `FLEETLOGIX_DW.ANALYTICS` y entra con su propio par de llaves, sin contraseña. La llave privada está en
  los Secrets de Streamlit Cloud y en `.streamlit/secrets.toml` en mi compu, que no se sube al repo.
- **Costo:** guarda el resultado una hora, así no prende el warehouse en cada visita. El warehouse es X-Small y se apaga
  solo al minuto sin consultas.
- **Respaldo:** `07_export_dashboard_data.py` guarda las mismas consultas en `dashboard/data/` en parquet. Si Snowflake no
  responde, o cuando venza la cuenta de prueba, el tablero sigue andando con esa copia. La barra lateral muestra de cuál
  de las dos fuentes está leyendo, y en vivo tiene un botón para volver a leer Snowflake.

```bash
streamlit run dashboard/app.py                    # lee Snowflake si existe .streamlit/secrets.toml
python "2. Scripts/07_export_dashboard_data.py"   # actualiza la copia de respaldo
```

Páginas:

- **Resumen:** 5 indicadores con su evolución y la variación contra el mismo período del año anterior, una lectura automática
  según los filtros, entregas mensuales 2026 contra 2025, ingreso y costo, y margen por ciudad.
- **Ciudades y rutas:** mapa de Colombia con los corredores entre ciudades. El grosor de cada arco es la cantidad de entregas y el
  color es la puntualidad o el margen (se elige arriba del mapa). También muestra entregas y margen por ciudad y una tabla de detalle.

  ![Mapa de rutas](3.%20Documentación/img/dashboard_mapa.png)

- **Flota:** margen, entregas, consumo y carga por tipo de vehículo, y un mapa de calor del margen por tipo de vehículo y largo
  de la ruta. Ahí se ve que la van pierde plata en las rutas largas.
- **Puntualidad:** mapa de calor por ciudad y mes (se ven las lluvias del Caribe y diciembre), por día y turno, y minutos por entrega en cada ciudad.
- **Conductores:** puntualidad contra cantidad de entregas de cada conductor, el efecto de los conductores nuevos y un ranking que se puede ordenar.
- **Explorador:** con PyGWalker cualquiera puede armar sus propios gráficos arrastrando columnas, parecido a Tableau.
- **Modelo de datos:** de dónde salen los datos y el modelo estrella.

Los filtros de la barra lateral (período o rango de fechas, ciudad, tipo de vehículo y turno) valen para todas las páginas,
y cada gráfico tiene una pestaña "Datos" para ver la tabla y bajarla en CSV.
Dejé afuera el primer día y los dos últimos de los datos porque tienen viajes que todavía no terminaron
(el último día tiene 23 entregas contra unas 550 de un día normal). Si no, bajaban los totales y las comparaciones.

## 8. Decisiones y limitaciones

- **Elegí estrella y no copo de nieve** porque los analistas necesitan menos JOIN y Snowflake responde más rápido.
- **DynamoDB para el tiempo real y RDS para lo transaccional:** DynamoDB responde en milisegundos buscando por clave y se paga por uso.
  RDS mantiene la integridad relacional del modelo original.
- **Datos sintéticos:** los patrones que encuentra el análisis (estacionalidad, ciudades, conductores) los puse yo en el generador,
  así que sirven para mostrar las herramientas pero no son datos reales de una empresa. Los precios del combustible, los peajes y las
  tarifas del ETL son supuestos razonables para Colombia. El tipo de cliente (Individual, Empresa, Gobierno) no existe en la base de
  origen y lo asigné de forma sintética.
- **Precios de AWS:** usé los precios de lista de us-east-1 y son aproximados. Antes de implementar habría que confirmarlos con AWS Pricing Calculator.

## 9. Herramientas

Python (pandas, numpy, Faker, psycopg2, SQLAlchemy, matplotlib, schedule, boto3, moto, Streamlit, Plotly, PyGWalker), PostgreSQL 18, Snowflake,
AWS (API Gateway, Lambda, DynamoDB, RDS, S3, SNS, CloudWatch, IAM, KMS, Secrets Manager), Jupyter y Git.
