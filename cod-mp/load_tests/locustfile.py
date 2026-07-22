"""
locustfile.py — Escenario de carga real para el Parche Estudiante 4

Flujo de cada usuario virtual:
  1. on_start: login con allow_redirects=False para detectar fallos reales.
  2. Tarea GET / : verificar que la sesión sea válida.
  3. Tarea POST /agregar: intentar entregar una tarea (puede ser 303 o 409).
  4. Tarea GET /mis-entregas: verificar la lista de entregas.

Los correos se leen de load_tests/usuarios_carga.txt (generado por preparar_datos_carga.py).

Escenarios recomendados:
  Bajo   : 25 usuarios,  5/s, 2 min
  Medio  : 50 usuarios, 10/s, 2 min
  Alto   : 100 usuarios, 10/s, 3 min
  Estrés : 200 usuarios, 20/s, 3 min

Ejecución interactiva:
  locust -f load_tests/locustfile.py --host http://localhost

Ejecución automática (ejemplo Alto):
  locust -f load_tests/locustfile.py --headless -u 100 -r 10 -t 3m \
    --host http://localhost --csv resultados/locust_100
"""

import os
import queue
import random
import mysql.connector
from locust import HttpUser, task, between, events

# ---------------------------------------------------------------------------
# Cargar correos y tarea destino
# ---------------------------------------------------------------------------

SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
ARCHIVO_USUARIOS = os.path.join(SCRIPT_DIR, "usuarios_carga.txt")

DB_MASTER = dict(host="localhost", port=3308,
                 user="root", password="root", database="informacion")

# Cola thread-safe de correos disponibles
usuarios: queue.Queue = queue.Queue()

# ID de tarea para las entregas (se resuelve por código)
CODIGO_TAREA_CARGA = "TAREA-01"
_tarea_id_cache: int | None = None


def cargar_correos():
    if not os.path.exists(ARCHIVO_USUARIOS):
        print(f"[WARN] {ARCHIVO_USUARIOS} no encontrado. "
              "Ejecuta primero: python load_tests/preparar_datos_carga.py")
        return
    with open(ARCHIVO_USUARIOS, encoding="utf-8") as f:
        for linea in f:
            correo = linea.strip()
            if correo:
                usuarios.put(correo)
    print(f"[INFO] {usuarios.qsize()} correos cargados en cola.")


def obtener_tarea_id() -> int:
    global _tarea_id_cache
    if _tarea_id_cache is not None:
        return _tarea_id_cache
    try:
        conn   = mysql.connector.connect(**DB_MASTER)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM tareas WHERE codigo = %s", (CODIGO_TAREA_CARGA,))
        fila = cursor.fetchone()
        cursor.close()
        conn.close()
        _tarea_id_cache = fila[0] if fila else 1
    except Exception:
        _tarea_id_cache = 1
    return _tarea_id_cache


@events.init.add_listener
def on_locust_init(environment, **kwargs):
    cargar_correos()
    obtener_tarea_id()


# ---------------------------------------------------------------------------
# Usuario virtual
# ---------------------------------------------------------------------------

class EstudianteVirtual(HttpUser):
    wait_time = between(1, 3)

    def on_start(self):
        """Login inicial. Detecta fallos reales con allow_redirects=False."""
        if usuarios.empty():
            self.environment.runner.quit()
            return

        self.correo          = usuarios.get()
        self.entrega_realizada = False
        self.tarea_id        = obtener_tarea_id()

        with self.client.post(
            "/login",
            data={"correo": self.correo},
            name="POST /login",
            allow_redirects=False,
            catch_response=True,
        ) as resp:
            if resp.status_code in (302, 303):
                resp.success()
            else:
                resp.failure(
                    f"Login fallido para {self.correo}: HTTP {resp.status_code}"
                )

    def on_stop(self):
        """Devolver el correo a la cola si el runner sigue activo."""
        try:
            if self.correo:
                usuarios.put(self.correo)
        except AttributeError:
            pass

    # ---- Tareas ----

    @task(3)
    def ver_dashboard(self):
        """GET / — verifica que la sesión sea válida."""
        with self.client.get(
            "/",
            name="GET /",
            allow_redirects=False,
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code in (302, 303):
                resp.failure("Sesión no válida; redirigido al login.")
            else:
                resp.failure(f"HTTP inesperado: {resp.status_code}")

    @task(2)
    def entregar_tarea(self):
        """POST /agregar — entrega válida (303) o duplicado (409), ambos son correctos."""
        respuesta_texto = f"Respuesta de carga del usuario {self.correo} — {random.randint(1, 9999)}"
        with self.client.post(
            "/agregar",
            data={"tarea_id": self.tarea_id, "respuesta": respuesta_texto},
            name="POST /agregar",
            allow_redirects=False,
            catch_response=True,
        ) as resp:
            if resp.status_code in (302, 303):
                resp.success()
                self.entrega_realizada = True
            elif resp.status_code == 409:
                resp.success()   # Duplicado esperado — no es un error de Locust
            elif resp.status_code == 422:
                resp.success()   # Plazo vencido — esperado para TAREA-03
            else:
                resp.failure(f"HTTP inesperado al entregar: {resp.status_code}")

    @task(1)
    def ver_mis_entregas(self):
        """GET /mis-entregas — verifica consistencia post-entrega."""
        with self.client.get(
            "/mis-entregas",
            name="GET /mis-entregas",
            allow_redirects=False,
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                resp.success()
            elif resp.status_code in (302, 303):
                resp.failure("Sesión no válida; redirigido al login.")
            else:
                resp.failure(f"HTTP inesperado: {resp.status_code}")
