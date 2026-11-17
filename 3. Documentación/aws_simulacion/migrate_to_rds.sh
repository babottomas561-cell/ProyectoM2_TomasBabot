#!/bin/bash
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
psql -h "$RDS_ENDPOINT" -U "$RDS_USER" -d postgres -tc "SELECT 1 FROM pg_database WHERE datname = '$RDS_DB'" | grep -q 1 \
  || psql -h "$RDS_ENDPOINT" -U "$RDS_USER" -d postgres -c "CREATE DATABASE $RDS_DB;"

echo "3. Restaurando en RDS (4 procesos en paralelo)..."
pg_restore -h "$RDS_ENDPOINT" -U "$RDS_USER" -d "$RDS_DB" --no-owner --jobs=4 fleetlogix.dump

echo "4. Verificando cantidad de filas..."
psql -h "$RDS_ENDPOINT" -U "$RDS_USER" -d "$RDS_DB" -c \
  "SELECT 'trips' AS tabla, COUNT(*) FROM trips UNION ALL SELECT 'deliveries', COUNT(*) FROM deliveries;"
echo "Migración completada"
