#!/bin/bash
# Script de inicialización de replicación para mysql_replica
# Se ejecuta en segundo plano para no interrumpir el proceso de arranque principal de MySQL

(
  export MYSQL_PWD=root

  echo "=== [SLAVE SETUP] Iniciando script de replicación en segundo plano..."

  # 1. Esperar a que el servidor final de mysql_replica esté listo en puerto de red TCP (no en el socket temporal)
  echo "=== [SLAVE SETUP] Esperando que mysql_replica local (TCP) inicie..."
  until mysql -h 127.0.0.1 -u root -e "SELECT 1;" &>/dev/null; do
    sleep 2
  done
  echo "=== [SLAVE SETUP] mysql_replica local está listo para recibir conexiones TCP."

  # 2. Esperar a que el servidor mysql_principal esté listo y acepte conexiones
  echo "=== [SLAVE SETUP] Esperando que mysql_principal (Master) esté listo..."
  until mysql -h mysql_principal -u root -e "SELECT 1;" &>/dev/null; do
    sleep 2
  done
  echo "=== [SLAVE SETUP] Conexión establecida con mysql_principal."

  # 3. Comprobar si la replicación ya está corriendo
  STATUS=$(mysql -h 127.0.0.1 -u root -e "SHOW REPLICA STATUS\G" | grep "Replica_IO_Running")
  if [ -n "$STATUS" ]; then
    echo "=== [SLAVE SETUP] La replicación ya está configurada e iniciada."
  else
    echo "=== [SLAVE SETUP] Configurando y arrancando replicación..."
    mysql -h 127.0.0.1 -u root <<EOF
STOP REPLICA;
CHANGE REPLICATION SOURCE TO
  SOURCE_HOST='mysql_principal',
  SOURCE_USER='replica_user',
  SOURCE_PASSWORD='replica_password',
  SOURCE_AUTO_POSITION=1,
  GET_SOURCE_PUBLIC_KEY=1;
START REPLICA;
EOF
    echo "=== [SLAVE SETUP] Comandos de replicación enviados."
    sleep 2
    mysql -h 127.0.0.1 -u root -e "SHOW REPLICA STATUS\G"
  fi
) &
