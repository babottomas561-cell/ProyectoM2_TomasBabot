"""
FleetLogix - Lambda 1: fleetlogix-verificar-entrega

Qué hace: recibe un delivery_id y consulta en DynamoDB (tabla deliveries_status)
si esa entrega ya figura como entregada.

Disparador: API Gateway  POST /deliveries/verify  (la app móvil del conductor).
Permisos que necesita el rol: dynamodb:GetItem sobre deliveries_status y escribir logs.
"""

import json
import os

import boto3

# El cliente se crea fuera del handler: AWS lo reutiliza entre invocaciones (más rápido)
dynamodb = boto3.resource('dynamodb', region_name=os.getenv('AWS_REGION', 'us-east-1'))
TABLE_NAME = os.getenv('DELIVERIES_TABLE', 'deliveries_status')


def _leer_evento(event):
    """API Gateway (integración proxy) manda los datos como texto JSON en 'body'.
    Si se prueba desde la consola de Lambda, llegan directamente en el evento."""
    if isinstance(event, dict) and isinstance(event.get('body'), str):
        return json.loads(event['body'] or '{}')
    return event or {}


def _respuesta(status_code, body):
    return {
        'statusCode': status_code,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps(body, default=str)
    }


def lambda_handler(event, context):
    datos = _leer_evento(event)
    delivery_id = datos.get('delivery_id')

    # 1. Validar la entrada
    if not delivery_id:
        return _respuesta(400, {'error': 'delivery_id es requerido'})

    try:
        # 2. Buscar la entrega por su clave primaria (lectura directa, muy barata)
        table = dynamodb.Table(TABLE_NAME)
        response = table.get_item(Key={'delivery_id': str(delivery_id)})

        # 3. Si no existe -> 404
        if 'Item' not in response:
            return _respuesta(404, {'error': 'Entrega no encontrada', 'delivery_id': delivery_id})

        # 4. Si existe -> decir si está completada
        item = response['Item']
        return _respuesta(200, {
            'delivery_id': delivery_id,
            'tracking_number': item.get('tracking_number'),
            'is_completed': item.get('status') == 'delivered',
            'status': item.get('status'),
            'delivered_datetime': item.get('delivered_datetime', '')
        })

    except Exception as e:  # tabla inexistente, permisos, etc. Queda registrado en CloudWatch
        print(f"ERROR verificar_entrega: {e}")
        return _respuesta(500, {'error': str(e)})
