"""
FleetLogix - Lambda 3: fleetlogix-alerta-desvio

Qué hace: compara la posición GPS del camión con los puntos (waypoints) de su ruta
guardados en DynamoDB (tabla routes_waypoints). Si el punto más cercano está a más
de 5 km, considera que el camión se desvió: publica una alerta en SNS (mail/SMS al
supervisor) y la guarda en DynamoDB (tabla alerts_history).

Disparador: API Gateway  POST /vehicles/location  (cada actualización de GPS).
Permisos: dynamodb:GetItem (routes_waypoints), dynamodb:PutItem (alerts_history),
sns:Publish sobre el tópico de alertas y escribir logs.
"""

import json
import math
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3

REGION = os.getenv('AWS_REGION', 'us-east-1')
dynamodb = boto3.resource('dynamodb', region_name=REGION)
sns = boto3.client('sns', region_name=REGION)

# El ARN del tópico se configura como variable de entorno (no se deja fijo en el código)
SNS_TOPIC_ARN = os.getenv('ALERTS_TOPIC_ARN', '')
UMBRAL_DESVIO_KM = float(os.getenv('DEVIATION_THRESHOLD_KM', 5))


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
    """Haversine: distancia real en km entre dos coordenadas."""
    r = 6371
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def lambda_handler(event, context):
    datos = _leer_evento(event)
    vehicle_id = datos.get('vehicle_id')
    actual = datos.get('current_location')
    route_id = datos.get('route_id')
    driver_id = datos.get('driver_id')

    if not all([vehicle_id, actual, route_id]):
        return _respuesta(400, {'error': 'Faltan parámetros: vehicle_id, current_location, route_id'})

    try:
        # 1. Traer los puntos de la ruta esperada
        ruta = dynamodb.Table('routes_waypoints').get_item(Key={'route_id': str(route_id)})
        if 'Item' not in ruta or not ruta['Item'].get('waypoints'):
            return _respuesta(404, {'error': 'Ruta no encontrada', 'route_id': route_id})

        # 2. Distancia al punto de la ruta más cercano
        desvio = min(
            distancia_km(float(w['lat']), float(w['lon']), actual['lat'], actual['lon'])
            for w in ruta['Item']['waypoints']
        )
        se_desvio = desvio > UMBRAL_DESVIO_KM

        # 3. Si se desvió: alerta por SNS + registro histórico
        if se_desvio:
            alerta = {
                'vehicle_id': str(vehicle_id),
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'driver_id': str(driver_id),
                'route_id': str(route_id),
                'deviation_km': round(desvio, 2),
                'current_location': actual,
                'alert_type': 'ROUTE_DEVIATION'
            }
            if SNS_TOPIC_ARN:
                sns.publish(TopicArn=SNS_TOPIC_ARN,
                            Subject='FleetLogix: desvío de ruta detectado',
                            Message=json.dumps(alerta))
            # DynamoDB no acepta float -> se convierten a Decimal antes de guardar
            item = json.loads(json.dumps(alerta), parse_float=Decimal)
            dynamodb.Table('alerts_history').put_item(Item=item)

        return _respuesta(200, {
            'vehicle_id': vehicle_id,
            'is_deviated': se_desvio,
            'deviation_km': round(desvio, 2),
            'alert_sent': se_desvio,
            'threshold_km': UMBRAL_DESVIO_KM
        })

    except Exception as e:
        print(f"ERROR alerta_desvio: {e}")
        return _respuesta(500, {'error': str(e)})
