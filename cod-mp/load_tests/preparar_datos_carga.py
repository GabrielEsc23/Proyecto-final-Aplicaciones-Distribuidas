"""
preparar_datos_carga.py — Crea 200 usuarios de prueba para Locust

FUNCIONAMIENTO:
  1. Inserta 200 usuarios directamente en el maestro MySQL (puerto 3308).
  2. Espera hasta 60 s a que la réplica (puerto 3309) los sincronice.
  3. Escribe los correos en load_tests/usuarios_carga.txt para que Locust los lea.

Ejecución:
  python load_tests/preparar_datos_carga.py
"""

import os
import time
import mysql.connector

TOTAL_USUARIOS  = 200
PREFIJO_CORREO  = "carga"
DOMINIO         = "@epn.edu.ec"
TIMEOUT_REPLICA = 60          # segundos máximos de espera

MASTER_CONFIG = dict(host="localhost", port=3308,
                     user="root", password="root", database="informacion")
REPLICA_CONFIG = dict(host="localhost", port=3309,
                      user="root", password="root", database="informacion")

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_USUARIOS = os.path.join(SCRIPT_DIR, "usuarios_carga.txt")


# ---------------------------------------------------------------------------
# Insertar usuarios en el maestro
# ---------------------------------------------------------------------------

def insertar_usuarios():
    conn   = mysql.connector.connect(**MASTER_CONFIG)
    cursor = conn.cursor()

    correos = []
    insertados = 0
    for i in range(1, TOTAL_USUARIOS + 1):
        nombre = f"Estudiante Carga {i:03d}"
        correo = f"{PREFIJO_CORREO}{i:03d}{DOMINIO}"
        try:
            cursor.execute(
                "INSERT IGNORE INTO usuarios (nombre, correo, rol) VALUES (%s, %s, 'estudiante')",
                (nombre, correo)
            )
            insertados += cursor.rowcount
        except mysql.connector.Error as e:
            print(f"  [WARN] No se pudo insertar {correo}: {e}")
        correos.append(correo)

    conn.commit()
    cursor.close()
    conn.close()

    print(f"Usuarios insertados/ignorados en maestro: {insertados} nuevos "
          f"({TOTAL_USUARIOS - insertados} ya existían)")
    return correos


# ---------------------------------------------------------------------------
# Esperar sincronización en réplica
# ---------------------------------------------------------------------------

def esperar_replica(total_esperado: int):
    print(f"Esperando replicación en réplica (máximo {TIMEOUT_REPLICA} s)...")
    limite = time.time() + TIMEOUT_REPLICA

    while time.time() < limite:
        try:
            conn   = mysql.connector.connect(**REPLICA_CONFIG)
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT COUNT(*) FROM usuarios "
                f"WHERE correo LIKE '{PREFIJO_CORREO}%{DOMINIO}'"
            )
            total_replica = cursor.fetchone()[0]
            cursor.close()
            conn.close()

            print(f"  Réplica tiene {total_replica}/{total_esperado} usuarios...", end="\r")
            if total_replica >= total_esperado:
                print(f"\nRéplica sincronizada: {total_replica} usuarios. ✓")
                return
        except mysql.connector.Error:
            pass   # Réplica aún no disponible, reintentar

        time.sleep(2)

    raise RuntimeError(
        "La réplica no sincronizó los usuarios dentro del tiempo esperado. "
        "Verifica que docker compose esté corriendo y la replicación esté activa."
    )


# ---------------------------------------------------------------------------
# Guardar lista de correos para Locust
# ---------------------------------------------------------------------------

def guardar_correos(correos: list):
    with open(ARCHIVO_USUARIOS, "w", encoding="utf-8") as f:
        for correo in correos:
            f.write(correo + "\n")
    print(f"Lista de correos guardada en: {ARCHIVO_USUARIOS}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 55)
    print("  PREPARAR DATOS DE CARGA — Parche Estudiante 4")
    print("=" * 55 + "\n")

    correos = insertar_usuarios()
    esperar_replica(TOTAL_USUARIOS)
    guardar_correos(correos)

    print("\nListo. Puedes ejecutar Locust:")
    print("  locust -f load_tests/locustfile.py --host http://localhost")


if __name__ == "__main__":
    main()
