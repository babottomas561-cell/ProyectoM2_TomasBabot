"""
Pruebas de las 3 funciones Lambda con un AWS simulado (moto).

Son las mismas pruebas de la sección 5 del notebook Avance_4_CloudArchitecture.ipynb, pero sin
PostgreSQL: los datos de prueba se cargan a mano. Corren solas en GitHub Actions con cada push.

    pytest -v
"""

import importlib
import json
import os
import sys
from decimal import Decimal
from pathlib import Path

import pytest

# Credenciales FALSAS: moto intercepta todas las llamadas, nada sale a AWS.
# Se definen antes de importar boto3 y las Lambda.
os.environ.update(AWS_ACCESS_KEY_ID='testing', AWS_SECRET_ACCESS_KEY='testing', AWS_SESSION_TOKEN='testing',
                  AWS_DEFAULT_REGION='us-east-1', AWS_REGION='us-east-1')

import boto3  # noqa: E402
from moto import mock_aws  # noqa: E402

CARPETA_LAMBDAS = Path(__file__).resolve().parent.parent / '2. Scripts' / 'lambda_functions'
sys.path.insert(0, str(CARPETA_LAMBDAS))

# Mismas tablas y claves que crea 06_aws_setup.py (clave de partición, clave de orden)
TABLAS = {
    'deliveries_status': ('delivery_id', None),
    'vehicle_tracking': ('vehicle_id', 'timestamp'),
    'routes_waypoints': ('route_id', None),
    'alerts_history': ('vehicle_id', 'timestamp'),
}
BOGOTA, MEDELLIN = (4.7110, -74.0721), (6.2442, -75.5812)
MITAD = {'lat': (BOGOTA[0] + MEDELLIN[0]) / 2, 'lon': (BOGOTA[1] + MEDELLIN[1]) / 2}


def api_gateway(datos):
    """Evento como el que manda API Gateway (integración proxy): los datos van como texto en body."""
    return {'httpMethod': 'POST', 'headers': {'Content-Type': 'application/json'}, 'body': json.dumps(datos)}


def llamar(modulo, datos):
    """Llama al handler y devuelve (statusCode, body ya leído)."""
    respuesta = modulo.lambda_handler(api_gateway(datos), None)
    return respuesta['statusCode'], json.loads(respuesta['body'])


def puntos_ruta(origen, destino, n=21):
    """La ruta como 21 puntos en línea recta entre las dos ciudades (igual que en el notebook)."""
    (la1, lo1), (la2, lo2) = origen, destino
    return [{'lat': Decimal(str(round(la1 + (la2 - la1) * i / (n - 1), 5))),
             'lon': Decimal(str(round(lo1 + (lo2 - lo1) * i / (n - 1), 5)))} for i in range(n)]


@pytest.fixture
def aws():
    """Levanta el AWS simulado con las 4 tablas, el tópico SNS y una cola que recibe las alertas."""
    with mock_aws():
        dynamo = boto3.resource('dynamodb')
        for tabla, (hash_key, range_key) in TABLAS.items():
            claves = [{'AttributeName': hash_key, 'KeyType': 'HASH'}]
            atributos = [{'AttributeName': hash_key, 'AttributeType': 'S'}]
            if range_key:
                claves.append({'AttributeName': range_key, 'KeyType': 'RANGE'})
                atributos.append({'AttributeName': range_key, 'AttributeType': 'S'})
            dynamo.create_table(TableName=tabla, KeySchema=claves, AttributeDefinitions=atributos,
                                BillingMode='PAY_PER_REQUEST')

        dynamo.Table('deliveries_status').put_item(Item={
            'delivery_id': '101', 'tracking_number': 'FL-000101', 'status': 'delivered',
            'delivered_datetime': '2026-10-01 14:30:00'})
        dynamo.Table('deliveries_status').put_item(Item={
            'delivery_id': '102', 'tracking_number': 'FL-000102', 'status': 'pending', 'delivered_datetime': ''})
        dynamo.Table('routes_waypoints').put_item(Item={
            'route_id': '1', 'route_code': 'R-BOG-MED', 'waypoints': puntos_ruta(BOGOTA, MEDELLIN)})

        # En AWS real la alerta le llega por mail al supervisor; acá se suscribe una cola SQS para leerla
        topico = boto3.client('sns').create_topic(Name='fleetlogix-alerts')['TopicArn']
        sqs = boto3.client('sqs')
        cola = sqs.create_queue(QueueName='buzon-supervisor')['QueueUrl']
        cola_arn = sqs.get_queue_attributes(QueueUrl=cola, AttributeNames=['QueueArn'])['Attributes']['QueueArn']
        boto3.client('sns').subscribe(TopicArn=topico, Protocol='sqs', Endpoint=cola_arn)

        # Las Lambda leen el ARN del tópico de una variable de entorno al importarse,
        # por eso se (re)importan recién ahora, con el AWS simulado ya andando
        os.environ['ALERTS_TOPIC_ARN'] = topico
        modulos = {nombre: importlib.reload(importlib.import_module(nombre))
                   for nombre in ('verificar_entrega', 'calcular_eta', 'alerta_desvio')}

        yield {'dynamo': dynamo, 'sqs': sqs, 'cola': cola, **modulos}


# ---------- Lambda 1: verificar_entrega ----------

def test_verificar_entrega_completada(aws):
    status, body = llamar(aws['verificar_entrega'], {'delivery_id': '101'})
    assert status == 200
    assert body['is_completed'] is True
    assert body['tracking_number'] == 'FL-000101'


def test_verificar_entrega_pendiente(aws):
    status, body = llamar(aws['verificar_entrega'], {'delivery_id': '102'})
    assert status == 200
    assert body['is_completed'] is False
    assert body['status'] == 'pending'


def test_verificar_entrega_inexistente(aws):
    status, _ = llamar(aws['verificar_entrega'], {'delivery_id': '999999999'})
    assert status == 404


def test_verificar_entrega_sin_id(aws):
    status, _ = llamar(aws['verificar_entrega'], {})
    assert status == 400


def test_verificar_entrega_evento_directo(aws):
    """Desde la consola de Lambda el evento llega sin body: también tiene que andar."""
    respuesta = aws['verificar_entrega'].lambda_handler({'delivery_id': '101'}, None)
    assert respuesta['statusCode'] == 200


# ---------- Lambda 2: calcular_eta ----------

def test_calcular_eta_a_mitad_de_ruta(aws):
    datos = {'vehicle_id': 'V-017', 'current_location': MITAD,
             'destination': {'lat': MEDELLIN[0], 'lon': MEDELLIN[1]}, 'current_speed_kmh': 60}
    status, body = llamar(aws['calcular_eta'], datos)
    assert status == 200
    # Bogotá - Medellín son unos 240 km en línea recta, a mitad de camino faltan unos 120
    assert 110 < body['distance_remaining_km'] < 130
    assert body['estimated_minutes'] == round(body['distance_remaining_km'] / 60 * 60)
    # La lectura queda guardada en vehicle_tracking (con Decimal, no float)
    assert aws['dynamo'].Table('vehicle_tracking').scan(Select='COUNT')['Count'] == 1


def test_calcular_eta_vehiculo_detenido(aws):
    datos = {'vehicle_id': 'V-018', 'current_location': MITAD,
             'destination': {'lat': MEDELLIN[0], 'lon': MEDELLIN[1]}, 'current_speed_kmh': 0}
    status, body = llamar(aws['calcular_eta'], datos)
    assert status == 200
    assert body['estimated_minutes'] is None
    assert body['eta'] == 'No disponible'


def test_calcular_eta_sin_destino(aws):
    status, _ = llamar(aws['calcular_eta'], {'vehicle_id': 'V-019', 'current_location': MITAD})
    assert status == 400


# ---------- Lambda 3: alerta_desvio ----------

BASE_DESVIO = {'vehicle_id': 'V-017', 'driver_id': '42', 'route_id': '1'}


def test_alerta_desvio_en_ruta(aws):
    cerca = {'lat': MITAD['lat'] + 0.01, 'lon': MITAD['lon']}          # ~1 km de la ruta
    status, body = llamar(aws['alerta_desvio'], {**BASE_DESVIO, 'current_location': cerca})
    assert status == 200
    assert body['is_deviated'] is False
    assert aws['dynamo'].Table('alerts_history').scan(Select='COUNT')['Count'] == 0


def test_alerta_desvio_desviado_manda_alerta(aws):
    lejos = {'lat': MITAD['lat'] + 0.20, 'lon': MITAD['lon'] + 0.15}   # ~25 km de la ruta
    status, body = llamar(aws['alerta_desvio'], {**BASE_DESVIO, 'current_location': lejos})
    assert status == 200
    assert body['is_deviated'] is True
    assert body['deviation_km'] > 5

    # La alerta queda guardada en alerts_history...
    assert aws['dynamo'].Table('alerts_history').scan(Select='COUNT')['Count'] == 1
    # ...y llega por SNS
    mensajes = aws['sqs'].receive_message(QueueUrl=aws['cola'], MaxNumberOfMessages=10).get('Messages', [])
    assert len(mensajes) == 1
    alerta = json.loads(json.loads(mensajes[0]['Body'])['Message'])
    assert alerta['alert_type'] == 'ROUTE_DEVIATION'
    assert alerta['vehicle_id'] == 'V-017'


def test_alerta_desvio_ruta_inexistente(aws):
    datos = {**BASE_DESVIO, 'route_id': '9999', 'current_location': MITAD}
    status, _ = llamar(aws['alerta_desvio'], datos)
    assert status == 404


def test_alerta_desvio_faltan_datos(aws):
    status, _ = llamar(aws['alerta_desvio'], {'vehicle_id': 'V-017'})
    assert status == 400
