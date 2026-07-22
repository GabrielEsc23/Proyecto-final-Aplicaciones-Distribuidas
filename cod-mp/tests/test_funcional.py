"""
test_funcional.py — Prueba funcional E2E del Parche Estudiante 4

Valida los 8 escenarios documentados contra la aplicación en http://localhost.
Los IDs se resuelven por correo/código para no depender de valores hardcodeados.

Requisitos previos:
  - docker compose up --build -d  (todos los servicios healthy)
  - pip install -r requirements-test.txt

Ejecución:
  python tests/test_funcional.py
"""

import sys
import requests
import mysql.connector

BASE_URL = "http://localhost"
DB_HOST  = "localhost"
DB_PORT  = 3308          # puerto expuesto del maestro
DB_USER  = "root"
DB_PASS  = "root"
DB_NAME  = "informacion"

CORREO_PRUEBA   = "prueba@epn.edu.ec"
CODIGO_VALIDA   = "TAREA-01"
CODIGO_EXPIRADA = "TAREA-03"


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
    """Busca IDs por correo y código en lugar de hardcodearlos."""
    conn   = conectar_maestro()
    cursor = conn.cursor()

    cursor.execute("SELECT id FROM usuarios WHERE correo = %s", (CORREO_PRUEBA,))
    fila = cursor.fetchone()
    if not fila:
        sys.exit(f"[ERROR] Usuario '{CORREO_PRUEBA}' no encontrado en la base de datos.")
    usuario_id = fila[0]

    cursor.execute("SELECT id FROM tareas WHERE codigo = %s", (CODIGO_VALIDA,))
    fila = cursor.fetchone()
    if not fila:
        sys.exit(f"[ERROR] Tarea con código '{CODIGO_VALIDA}' no encontrada.")
    tarea_valida_id = fila[0]

    cursor.execute("SELECT id FROM tareas WHERE codigo = %s", (CODIGO_EXPIRADA,))
    fila = cursor.fetchone()
    if not fila:
        sys.exit(f"[ERROR] Tarea con código '{CODIGO_EXPIRADA}' no encontrada.")
    tarea_expirada_id = fila[0]

    cursor.close()
    conn.close()
    return usuario_id, tarea_valida_id, tarea_expirada_id


def limpiar_entrega(usuario_id, tarea_id):
    """Elimina una entrega del maestro para poder repetir la prueba."""
    conn   = conectar_maestro()
    cursor = conn.cursor()
    cursor.execute(
        "DELETE FROM entregas WHERE usuario_id = %s AND tarea_id = %s",
        (usuario_id, tarea_id)
    )
    conn.commit()
    cursor.close()
    conn.close()


def iniciar_sesion(session: requests.Session) -> bool:
    """Hace login y verifica que la sesión sea válida (espera 302/303)."""
    resp = session.post(
        f"{BASE_URL}/login",
        data={"correo": CORREO_PRUEBA},
        allow_redirects=False,
    )
    return resp.status_code in (302, 303)


def ok(nombre):
    print(f"  [PASS] {nombre}")


def fallo(nombre, detalle):
    print(f"  [FAIL] {nombre} — {detalle}")


# ---------------------------------------------------------------------------
# Escenarios
# ---------------------------------------------------------------------------

def test_login_correcto(session):
    print("1. Login correcto")
    resultado = iniciar_sesion(session)
    if resultado:
        ok("Redirección 302/303 tras login válido")
    else:
        fallo("Login correcto", "No se recibió 302/303")


def test_respuesta_vacia(session, tarea_valida_id):
    print("2. Rechazo por respuesta vacía")
    resp = session.post(
        f"{BASE_URL}/agregar",
        data={"tarea_id": tarea_valida_id, "respuesta": ""},
        allow_redirects=False,
    )
    if resp.status_code == 400:
        ok(f"HTTP 400 para respuesta vacía")
    else:
        fallo("Respuesta vacía", f"Se esperaba 400, se obtuvo {resp.status_code}")


def test_respuesta_muy_larga(session, tarea_valida_id):
    print("3. Rechazo por respuesta > 5 000 caracteres")
    resp = session.post(
        f"{BASE_URL}/agregar",
        data={"tarea_id": tarea_valida_id, "respuesta": "X" * 5001},
        allow_redirects=False,
    )
    if resp.status_code == 400:
        ok("HTTP 400 para respuesta de 5 001 caracteres")
    else:
        fallo("Respuesta muy larga", f"Se esperaba 400, se obtuvo {resp.status_code}")


def test_tarea_id_invalido(session):
    print("4. Rechazo por tarea_id inválido (no numérico)")
    resp = session.post(
        f"{BASE_URL}/agregar",
        data={"tarea_id": "abc", "respuesta": "respuesta válida"},
        allow_redirects=False,
    )
    if resp.status_code == 400:
        ok("HTTP 400 para tarea_id no numérico")
    else:
        fallo("tarea_id inválido", f"Se esperaba 400, se obtuvo {resp.status_code}")


def test_tarea_inexistente(session):
    print("5. Rechazo por tarea inexistente")
    resp = session.post(
        f"{BASE_URL}/agregar",
        data={"tarea_id": 99999, "respuesta": "respuesta válida"},
        allow_redirects=False,
    )
    if resp.status_code == 404:
        ok("HTTP 404 para tarea_id que no existe")
    else:
        fallo("Tarea inexistente", f"Se esperaba 404, se obtuvo {resp.status_code}")


def test_tarea_vencida(session, tarea_expirada_id):
    print("6. Rechazo por tarea vencida")
    resp = session.post(
        f"{BASE_URL}/agregar",
        data={"tarea_id": tarea_expirada_id, "respuesta": "respuesta válida"},
        allow_redirects=False,
    )
    if resp.status_code == 422:
        ok("HTTP 422 para tarea con plazo vencido")
    else:
        fallo("Tarea vencida", f"Se esperaba 422, se obtuvo {resp.status_code}")


def test_entrega_valida(session, tarea_valida_id):
    print("7. Entrega válida")
    resp = session.post(
        f"{BASE_URL}/agregar",
        data={"tarea_id": tarea_valida_id, "respuesta": "Respuesta de prueba funcional."},
        allow_redirects=False,
    )
    if resp.status_code in (302, 303):
        ok("HTTP 303 (redirección) tras entrega exitosa")
    else:
        fallo("Entrega válida", f"Se esperaba 303, se obtuvo {resp.status_code}")


def test_entrega_duplicada(session, tarea_valida_id):
    print("8. Rechazo por entrega duplicada")
    resp = session.post(
        f"{BASE_URL}/agregar",
        data={"tarea_id": tarea_valida_id, "respuesta": "Intento duplicado."},
        allow_redirects=False,
    )
    if resp.status_code == 409:
        ok("HTTP 409 para entrega duplicada")
    else:
        fallo("Entrega duplicada", f"Se esperaba 409, se obtuvo {resp.status_code}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 55)
    print("  PRUEBA FUNCIONAL — Parche Estudiante 4")
    print("=" * 55)

    usuario_id, tarea_valida_id, tarea_expirada_id = resolver_ids()
    print(f"\nIDs resueltos: usuario={usuario_id}, "
          f"tarea_valida={tarea_valida_id}, tarea_expirada={tarea_expirada_id}\n")

    # Limpiar posible entrega anterior del usuario de prueba
    limpiar_entrega(usuario_id, tarea_valida_id)

    session = requests.Session()

    test_login_correcto(session)
    test_respuesta_vacia(session, tarea_valida_id)
    test_respuesta_muy_larga(session, tarea_valida_id)
    test_tarea_id_invalido(session)
    test_tarea_inexistente(session)
    test_tarea_vencida(session, tarea_expirada_id)
    test_entrega_valida(session, tarea_valida_id)
    test_entrega_duplicada(session, tarea_valida_id)

    # Limpiar al final para no dejar rastro en la DB de pruebas
    limpiar_entrega(usuario_id, tarea_valida_id)

    print("\n" + "=" * 55)
    print("  Prueba funcional completada.")
    print("=" * 55)


if __name__ == "__main__":
    main()
