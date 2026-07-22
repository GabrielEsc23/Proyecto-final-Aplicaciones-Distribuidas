"""
test_concurrencia.py — Prueba de concurrencia del Parche Estudiante 4

Envía 20 solicitudes simultáneas del MISMO estudiante para la MISMA tarea.
Resultado esperado:
  - Exactamente 1 respuesta HTTP 303
  - Exactamente 19 respuestas HTTP 409
  - Exactamente 1 fila en la tabla entregas del maestro

Requisitos previos:
  - docker compose up --build -d  (todos los servicios healthy)
  - pip install -r requirements-test.txt

Ejecución:
  python tests/test_concurrencia.py
"""

import sys
import requests
import mysql.connector
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE_URL        = "http://localhost"
DB_HOST         = "localhost"
DB_PORT         = 3308
DB_USER         = "root"
DB_PASS         = "root"
DB_NAME         = "informacion"

CORREO_PRUEBA   = "prueba@epn.edu.ec"
CODIGO_VALIDA   = "TAREA-01"
TOTAL_HILOS     = 20


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def conectar_maestro():
    return mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASS,
        database=DB_NAME
    )


def resolver_ids():
    conn   = conectar_maestro()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM usuarios WHERE correo = %s", (CORREO_PRUEBA,))
    fila = cursor.fetchone()
    if not fila:
        sys.exit(f"[ERROR] Usuario '{CORREO_PRUEBA}' no encontrado.")
    usuario_id = fila[0]

    cursor.execute("SELECT id FROM tareas WHERE codigo = %s", (CODIGO_VALIDA,))
    fila = cursor.fetchone()
    if not fila:
        sys.exit(f"[ERROR] Tarea '{CODIGO_VALIDA}' no encontrada.")
    tarea_id = fila[0]

    cursor.close()
    conn.close()
    return usuario_id, tarea_id


def limpiar_entrega(usuario_id, tarea_id):
    conn   = conectar_maestro()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM entregas WHERE usuario_id = %s AND tarea_id = %s",
        (usuario_id, tarea_id)
    )
    conn.commit()
    cursor.close()
    conn.close()


def contar_entregas_maestro(usuario_id, tarea_id) -> int:
    conn   = conectar_maestro()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) FROM entregas WHERE usuario_id = %s AND tarea_id = %s",
        (usuario_id, tarea_id)
    )
    total = cursor.fetchone()[0]
    cursor.close()
    conn.close()
    return total


def hacer_login(session: requests.Session) -> bool:
    resp = session.post(
        f"{BASE_URL}/login",
        data={"correo": CORREO_PRUEBA},
        allow_redirects=False,
    )
    return resp.status_code in (302, 303)


def enviar_entrega(session: requests.Session, tarea_id: int) -> int:
    resp = session.post(
        f"{BASE_URL}/agregar",
        data={"tarea_id": tarea_id, "respuesta": "Respuesta de prueba concurrente."},
        allow_redirects=False,
    )
    return resp.status_code


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 55)
    print("  PRUEBA DE CONCURRENCIA — Parche Estudiante 4")
    print("=" * 55)

    usuario_id, tarea_id = resolver_ids()
    print(f"\nIDs resueltos: usuario={usuario_id}, tarea={tarea_id}")

    # Limpiar entrega previa para partir desde cero
    limpiar_entrega(usuario_id, tarea_id)
    print(f"Entrega previa eliminada. Enviando {TOTAL_HILOS} solicitudes simultáneas...\n")

    # Crear una sesión con login previo para cada hilo
    sessions = []
    for _ in range(TOTAL_HILOS):
        s = requests.Session()
        if not hacer_login(s):
            sys.exit("[ERROR] Login fallido. Verifica que la aplicación esté corriendo.")
        sessions.append(s)

    # Enviar todas las solicitudes en paralelo
    codigos_http = []
    with ThreadPoolExecutor(max_workers=TOTAL_HILOS) as executor:
        futuros = [
            executor.submit(enviar_entrega, s, tarea_id)
            for s in sessions
        ]
        for futuro in as_completed(futuros):
            codigos_http.append(futuro.result())

    # Contar resultados
    count_303  = sum(1 for c in codigos_http if c in (302, 303))
    count_409  = sum(1 for c in codigos_http if c == 409)
    otros      = [(c) for c in codigos_http if c not in (302, 303, 409)]

    filas_db = contar_entregas_maestro(usuario_id, tarea_id)

    # Mostrar resultados
    print("Distribución de respuestas HTTP:")
    print(f"  HTTP 303 (éxito)    : {count_303}")
    print(f"  HTTP 409 (duplicado): {count_409}")
    if otros:
        print(f"  Otros               : {otros}")

    print(f"\nFilas en la tabla entregas (maestro): {filas_db}")

    # Validar
    print("\nVerificación:")
    exito = True

    if count_303 == 1:
        print("  [PASS] Exactamente 1 entrega exitosa (HTTP 303)")
    else:
        print(f"  [FAIL] Se esperaba 1 HTTP 303, se obtuvo {count_303}")
        exito = False

    if count_409 == TOTAL_HILOS - 1:
        print(f"  [PASS] Exactamente {TOTAL_HILOS - 1} duplicados rechazados (HTTP 409)")
    else:
        print(f"  [FAIL] Se esperaba {TOTAL_HILOS - 1} HTTP 409, se obtuvo {count_409}")
        exito = False

    if filas_db == 1:
        print("  [PASS] Exactamente 1 fila almacenada en MySQL (maestro)")
    else:
        print(f"  [FAIL] Se esperaba 1 fila en DB, se encontraron {filas_db}")
        exito = False

    # Limpiar al final
    limpiar_entrega(usuario_id, tarea_id)

    print("\n" + "=" * 55)
    print(f"  Resultado: {'PASS' if exito else 'FAIL'}")
    print("=" * 55)

    sys.exit(0 if exito else 1)


if __name__ == "__main__":
    main()
