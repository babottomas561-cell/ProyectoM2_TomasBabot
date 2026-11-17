"""
FleetLogix - Configuración de AWS (versión revisada del script base de Henry)

Crea los recursos de la arquitectura:
    1. RDS PostgreSQL      -> base transaccional (reemplaza al PostgreSQL local)
    2. S3                  -> datos crudos, procesados, backups y logs
    3. DynamoDB (4 tablas) -> estado "en vivo" de entregas, GPS, rutas y alertas
    4. SNS                 -> tópico de alertas (mail / SMS a supervisores)
    5. IAM                 -> rol de las Lambda con permisos mínimos
    6. Snapshot y script de migración PostgreSQL local -> RDS

Qué se corrigió respecto del script base (detalle en 3. Documentación/Arquitectura_Tecnica.pdf):
    - La contraseña de RDS ya no está escrita en el código: la genera y guarda AWS Secrets Manager.
    - RDS NO es público (PubliclyAccessible=False) y queda cifrado (StorageEncrypted=True).
    - Versión de PostgreSQL vigente y disco gp3 (más barato y rápido que gp2).
    - El snapshot inicial espera a que la base esté disponible (antes fallaba: la base tarda ~10 min).
    - S3: cifrado por defecto, bloqueo de acceso público y versionado; los datos crudos pasan a
      almacenamiento barato a los 30 días y a Glacier a los 90.
    - IAM: en lugar de "FullAccess" a DynamoDB, S3 y SNS, una política con SOLO las acciones que usan las Lambda.
    - Ventanas de backup y mantenimiento separadas (en el original se tocaban a las 04:00 y AWS lo rechaza).
    - Tópico SNS creado por el script (el código de las Lambda lo recibe por variable de entorno).

Uso:  python 06_aws_setup.py            (requiere credenciales de AWS configuradas)
      En el notebook Avance_4 se ejecuta contra un AWS simulado (librería moto), sin costo.
"""

import json
import os
from datetime import datetime

import boto3

AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
RDS_INSTANCE_ID = 'fleetlogix-db'
S3_BUCKET_NAME = os.getenv('FLEETLOGIX_BUCKET', 'fleetlogix-data')
TABLAS_DYNAMODB = ['deliveries_status', 'vehicle_tracking', 'routes_waypoints', 'alerts_history']


def clientes():
    """Se crean dentro de una función para que el notebook pueda usar el AWS simulado."""
    return {nombre: boto3.client(nombre, region_name=AWS_REGION)
            for nombre in ['rds', 's3', 'dynamodb', 'sns', 'iam', 'sts']}


def crear_rds_postgresql(aws):
    print("Creando RDS PostgreSQL...")
    try:
        r = aws['rds'].create_db_instance(
            DBInstanceIdentifier=RDS_INSTANCE_ID,
            DBInstanceClass='db.t3.micro',        # capa gratuita el primer año
            Engine='postgres',
            EngineVersion='16.4',
            DBName='fleetlogix',
            MasterUsername='fleetlogix_admin',
            ManageMasterUserPassword=True,        # AWS genera la clave y la guarda en Secrets Manager
            AllocatedStorage=20,
            StorageType='gp3',
            StorageEncrypted=True,                # cifrado en reposo (KMS)
            BackupRetentionPeriod=7,              # backups automáticos 7 días
            PreferredBackupWindow='03:00-03:30',  # después del ETL de las 02:00
            PreferredMaintenanceWindow='sun:04:30-sun:05:30',  # no debe superponerse con el backup
            PubliclyAccessible=False,             # solo accesible desde la VPC
            DeletionProtection=True,
            Tags=[{'Key': 'Project', 'Value': 'FleetLogix'}, {'Key': 'Environment', 'Value': 'Development'}]
        )
        print(f"  RDS creado: {r['DBInstance']['DBInstanceIdentifier']}")
    except aws['rds'].exceptions.DBInstanceAlreadyExistsFault:
        print("  RDS ya existe")


def crear_s3_bucket(aws):
    print("Creando bucket S3...")
    s3 = aws['s3']
    try:
        s3.create_bucket(Bucket=S3_BUCKET_NAME)
    except (s3.exceptions.BucketAlreadyOwnedByYou, s3.exceptions.BucketAlreadyExists):
        print("  El bucket ya existe")

    for carpeta in ['raw-data/', 'processed-data/', 'backups/', 'logs/']:
        s3.put_object(Bucket=S3_BUCKET_NAME, Key=carpeta, Body=b'')

    # Seguridad: nadie puede hacer público el bucket y todo se guarda cifrado
    s3.put_public_access_block(Bucket=S3_BUCKET_NAME, PublicAccessBlockConfiguration={
        'BlockPublicAcls': True, 'IgnorePublicAcls': True,
        'BlockPublicPolicy': True, 'RestrictPublicBuckets': True})
    s3.put_bucket_encryption(Bucket=S3_BUCKET_NAME, ServerSideEncryptionConfiguration={
        'Rules': [{'ApplyServerSideEncryptionByDefault': {'SSEAlgorithm': 'AES256'}}]})
    s3.put_bucket_versioning(Bucket=S3_BUCKET_NAME, VersioningConfiguration={'Status': 'Enabled'})

    # Ciclo de vida: lo viejo pasa a almacenamiento más barato
    s3.put_bucket_lifecycle_configuration(Bucket=S3_BUCKET_NAME, LifecycleConfiguration={'Rules': [
        {'ID': 'raw-data-a-almacenamiento-barato', 'Status': 'Enabled', 'Filter': {'Prefix': 'raw-data/'},
         'Transitions': [{'Days': 30, 'StorageClass': 'STANDARD_IA'}, {'Days': 90, 'StorageClass': 'GLACIER'}]},
        {'ID': 'borrar-logs-viejos', 'Status': 'Enabled', 'Filter': {'Prefix': 'logs/'},
         'Expiration': {'Days': 365}},
    ]})
    print(f"  Bucket listo: {S3_BUCKET_NAME}")


def crear_tablas_dynamodb(aws):
    print("Creando tablas DynamoDB...")
    # (clave de partición, clave de orden). Las de GPS y alertas se ordenan por fecha y hora.
    claves = {
        'deliveries_status': ('delivery_id', None),
        'vehicle_tracking': ('vehicle_id', 'timestamp'),
        'routes_waypoints': ('route_id', None),
        'alerts_history': ('vehicle_id', 'timestamp'),
    }
    for tabla, (hash_key, range_key) in claves.items():
        key_schema = [{'AttributeName': hash_key, 'KeyType': 'HASH'}]
        atributos = [{'AttributeName': hash_key, 'AttributeType': 'S'}]
        if range_key:
            key_schema.append({'AttributeName': range_key, 'KeyType': 'RANGE'})
            atributos.append({'AttributeName': range_key, 'AttributeType': 'S'})
        try:
            aws['dynamodb'].create_table(
                TableName=tabla, KeySchema=key_schema, AttributeDefinitions=atributos,
                BillingMode='PAY_PER_REQUEST',    # se paga por uso: sin tráfico, casi sin costo
                SSESpecification={'Enabled': True},
                Tags=[{'Key': 'Project', 'Value': 'FleetLogix'}])
            print(f"  Tabla creada: {tabla}")
        except aws['dynamodb'].exceptions.ResourceInUseException:
            print(f"  Tabla ya existe: {tabla}")


def crear_topico_sns(aws, email_supervisor=None):
    print("Creando tópico SNS de alertas...")
    arn = aws['sns'].create_topic(Name='fleetlogix-alerts')['TopicArn']
    if email_supervisor:   # el supervisor recibe un mail para confirmar la suscripción
        aws['sns'].subscribe(TopicArn=arn, Protocol='email', Endpoint=email_supervisor)
    print(f"  Tópico: {arn}")
    return arn


def configurar_backups_automaticos(aws):
    """Los backups diarios ya quedan activos con BackupRetentionPeriod=7.
    Acá se saca además un snapshot manual inicial, pero ESPERANDO a que la base esté lista."""
    print("Configurando backups...")
    aws['rds'].get_waiter('db_instance_available').wait(
        DBInstanceIdentifier=RDS_INSTANCE_ID, WaiterConfig={'Delay': 30, 'MaxAttempts': 40})
    snapshot_id = f"fleetlogix-initial-{datetime.now().strftime('%Y%m%d%H%M%S')}"
    aws['rds'].create_db_snapshot(DBSnapshotIdentifier=snapshot_id, DBInstanceIdentifier=RDS_INSTANCE_ID,
                                  Tags=[{'Key': 'Type', 'Value': 'Manual'}])
    print(f"  Snapshot inicial: {snapshot_id} (más backups automáticos con retención de 7 días)")
    return snapshot_id


def migrar_datos_postgresql(ruta='migrate_to_rds.sh'):
    """Genera (no ejecuta) el script bash para copiar la base local a RDS."""
    print("Generando script de migración...")
    script = """#!/bin/bash
# Migración PostgreSQL local -> RDS. Se corre desde una máquina con acceso a la VPC
# (por ejemplo un bastion o con VPN), porque RDS no es público.
set -e   # si un paso falla, se corta (no seguir restaurando a medias)

LOCAL_DB="fleetlogix"
LOCAL_USER="${LOCAL_USER:-postgres}"
RDS_ENDPOINT="${RDS_ENDPOINT:?Definir RDS_ENDPOINT}"   # se obtiene de la consola o de describe-db-instances
RDS_USER="fleetlogix_admin"
RDS_DB="fleetlogix"
# La clave se lee de Secrets Manager y se pasa por variable (no queda escrita en el archivo)
export PGPASSWORD="${RDS_PASSWORD:?Definir RDS_PASSWORD}"

echo "1. Exportando la base local (formato comprimido, sin dueños locales)..."
pg_dump -h localhost -U "$LOCAL_USER" -d "$LOCAL_DB" --format=custom --no-owner --no-privileges -f fleetlogix.dump

echo "2. Creando la base en RDS si no existe (conectando a la base 'postgres')..."
psql -h "$RDS_ENDPOINT" -U "$RDS_USER" -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = '$RDS_DB'" | grep -q 1 \\
  || psql -h "$RDS_ENDPOINT" -U "$RDS_USER" -d postgres -c "CREATE DATABASE $RDS_DB;"

echo "3. Restaurando en RDS (4 procesos en paralelo)..."
pg_restore -h "$RDS_ENDPOINT" -U "$RDS_USER" -d "$RDS_DB" --no-owner --jobs=4 fleetlogix.dump

echo "4. Verificando cantidad de filas..."
psql -h "$RDS_ENDPOINT" -U "$RDS_USER" -d "$RDS_DB" -c \\
  "SELECT 'trips' AS tabla, COUNT(*) FROM trips UNION ALL SELECT 'deliveries', COUNT(*) FROM deliveries;"
echo "Migración completada"
"""
    with open(ruta, 'w') as f:
        f.write(script)
    print(f"  Script creado: {ruta}  (ejecutar: RDS_ENDPOINT=... RDS_PASSWORD=... bash {ruta})")
    return ruta


def crear_rol_iam_lambda(aws, cuenta, topic_arn):
    """Rol de las Lambda con permisos mínimos (principio de menor privilegio)."""
    print("Creando rol IAM para Lambda...")
    iam = aws['iam']
    trust = {"Version": "2012-10-17", "Statement": [{
        "Effect": "Allow", "Principal": {"Service": "lambda.amazonaws.com"}, "Action": "sts:AssumeRole"}]}
    tabla = lambda nombre: f"arn:aws:dynamodb:{AWS_REGION}:{cuenta}:table/{nombre}"
    permisos = {"Version": "2012-10-17", "Statement": [
        {"Sid": "LeerEntregasYRutas", "Effect": "Allow", "Action": ["dynamodb:GetItem"],
         "Resource": [tabla('deliveries_status'), tabla('routes_waypoints')]},
        {"Sid": "GuardarGPSyAlertas", "Effect": "Allow", "Action": ["dynamodb:PutItem"],
         "Resource": [tabla('vehicle_tracking'), tabla('alerts_history')]},
        {"Sid": "PublicarAlertas", "Effect": "Allow", "Action": ["sns:Publish"], "Resource": [topic_arn]},
    ]}
    try:
        rol = iam.create_role(RoleName='FleetLogixLambdaRole', AssumeRolePolicyDocument=json.dumps(trust),
                              Description='Rol de las Lambda de FleetLogix (menor privilegio)')
        arn = rol['Role']['Arn']
    except iam.exceptions.EntityAlreadyExistsException:
        arn = f"arn:aws:iam::{cuenta}:role/FleetLogixLambdaRole"
    # Logs en CloudWatch (política administrada mínima de AWS)
    iam.attach_role_policy(RoleName='FleetLogixLambdaRole',
                           PolicyArn='arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole')
    iam.put_role_policy(RoleName='FleetLogixLambdaRole', PolicyName='FleetLogixMinimo',
                        PolicyDocument=json.dumps(permisos))
    print(f"  Rol: {arn}")
    return arn


def main(email_supervisor=None, esperar_rds=True):
    print("FLEETLOGIX - Configuración AWS")
    print("=" * 50)
    aws = clientes()
    cuenta = aws['sts'].get_caller_identity()['Account']

    crear_rds_postgresql(aws)
    crear_s3_bucket(aws)
    crear_tablas_dynamodb(aws)
    topic_arn = crear_topico_sns(aws, email_supervisor)
    snapshot = configurar_backups_automaticos(aws) if esperar_rds else None
    script = migrar_datos_postgresql()
    rol_arn = crear_rol_iam_lambda(aws, cuenta, topic_arn)

    config = {'region': AWS_REGION, 'rds_instance': RDS_INSTANCE_ID, 's3_bucket': S3_BUCKET_NAME,
              'dynamodb_tables': TABLAS_DYNAMODB, 'alerts_topic_arn': topic_arn,
              'lambda_role_arn': rol_arn, 'initial_snapshot': snapshot, 'migration_script': script,
              'timestamp': datetime.now().isoformat()}
    with open('aws_config.json', 'w') as f:
        json.dump(config, f, indent=2)
    print("\nConfiguración guardada en aws_config.json")
    print("Próximos pasos: correr migrate_to_rds.sh, desplegar las 3 Lambda con este rol,")
    print("crear la API en API Gateway y las alarmas de CloudWatch (ver Arquitectura_Tecnica.pdf).")
    return config


if __name__ == '__main__':
    main(email_supervisor=os.getenv('SUPERVISOR_EMAIL'))
