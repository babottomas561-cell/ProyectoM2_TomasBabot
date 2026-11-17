"""
FleetLogix - Lambda 2: fleetlogix-calcular-eta

Qué hace: con la ubicación actual del vehículo, el destino y la velocidad,
calcula la distancia que falta y la hora estimada de llegada (ETA), y guarda
la lectura en DynamoDB (tabla vehicle_tracking) para que la app y el panel la vean.

Disparador: API Gateway  POST /vehicles/eta  (o EventBridge cada 5 minutos).
Permisos: dynamodb:PutItem sobre vehicle_tracking y escribir logs.
"""

import json
import math
import os
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import boto3

dynamodb = boto3.resource('dynamodb', region_name=os.getenv('AWS_REGION', 'us-east-1'))
TABLE_NAME = os.getenv('TRACKING_TABLE', 'vehicle_tracking')


def _leer_evento(event):
    if isinstance(event, dict) and isinstance(event.get('body'), str):
        return json.loads(event['body'] or '{}')
    return event or {}


def _respuesta(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(body, default=str)
    }


def distancia_km(lat1, lon1, lat2, lon2):
    """Fórmula de Haversine: distancia real sobre la Tierra (radio 6.371 km).
    (El script original usaba 111 km por grado, que exagera la distancia en longitud.)"""
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def lambda_handler(event, context):
    datos = _leer_evento(event)
    vehicle_id = datos.get('vehicle_id')
    actual = datos.get('current_location')   # {"lat": .., "lon": ..}
    destino = datos.get('destination')       # {"lat": .., "lon": ..}
    velocidad = float(datos.get('current_speed_kmh', 60))

    if not all([vehicle_id, actual, destino]):
        return _respuesta(400, {'error': 'Faltan parámetros: vehicle_id, current_location, destination'})

    try:
        km = distancia_km(actual['lat'], actual['lon'], destino['lat'], destino['lon'])

        ahora = datetime.now(timezone.utc)
        if velocidad > 0:
            minutos = round(km / velocidad * 60)
            eta = (ahora + timedelta(minutes=minutos)).isoformat()
        else:  # vehículo detenido: no se puede estimar
            minutos, eta = None, None

        # DynamoDB no acepta float: los números se guardan como Decimal
        dynamodb.Table(TABLE_NAME).put_item(Item={
            'vehicle_id': str(vehicle_id),
            'timestamp': ahora.isoformat(),
            'current_location': {k: Decimal(str(v)) for k, v in actual.items()},
            'destination': {k: Decimal(str(v)) for k, v in destino.items()},
            'distance_remaining_km': Decimal(str(round(km, 2))),
            'current_speed_kmh': Decimal(str(velocidad)),
            'eta': eta or 'No disponible'
        })

        return _respuesta(200, {
            'vehicle_id': vehicle_id,
            'distance_remaining_km': round(km, 2),
            'estimated_minutes': minutos,
            'eta': eta or 'No disponible'
        })

    except Exception as e:
        print(f"ERROR calcular_eta: {e}")
        return _respuesta(500, {'error': str(e)})
