from flask import Flask, render_template, request, redirect, session, url_for
import mysql.connector
import os

# Inicializar Flask apuntando al directorio de plantillas compartido en la raíz del proyecto
app = Flask(__name__, template_folder='../templates')
app.secret_key = os.environ.get("SECRET_KEY", "epn_distribuidas_2026_s4")

# Variables de Entorno para identificar el nodo actual
NODE_NAME  = os.environ.get("NODE_NAME", "Desarrollo Local")
NODE_PORT  = os.environ.get("NODE_PORT", "5000")
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "0") == "1"

# Función para conectarse al contenedor Maestro (Escrituras y lecturas críticas)
def conectar_master():
    return mysql.connector.connect(
        host="mysql_principal",
        user="root",
        password="root",
        database="informacion",
        charset="utf8mb4"
    )

# Función para conectarse al contenedor Réplica (Lecturas no críticas)
# Con fallback al Maestro si la réplica no está disponible
def conectar_replica():
    try:
        return mysql.connector.connect(
            host="mysql_replica",
            user="root",
            password="root",
            database="informacion",
            charset="utf8mb4"
        )
    except Exception as e:
        print(f"[{NODE_NAME}] ADVERTENCIA: Falló conexión a la réplica MySQL. Reanudando en Maestro. Detalle: {e}")
        return conectar_master()

# HEALTH CHECK — para pruebas de balanceo y monitoreo externo
@app.route("/health")
def health():
    return {"status": "ok", "node": NODE_NAME, "port": NODE_PORT}, 200

# 1. RUTA DE LOGIN (Lectura de Usuario)
@app.route("/login", methods=["GET", "POST"])
def login():
    # Si ya tiene una sesión iniciada, redirigir según su rol
    if "usuario_id" in session:
        if session.get("rol") == "admin":
            return redirect(url_for("admin_panel"))
        return redirect(url_for("index"))

    error_msg = None
    if request.method == "POST":
        correo = request.form["correo"].strip()

        # Lectura de login va a la réplica
        conexion = conectar_replica()
        cursor = conexion.cursor(dictionary=True)
        try:
            cursor.execute("SELECT * FROM usuarios WHERE correo = %s", (correo,))
            usuario = cursor.fetchone()
        except Exception as e:
            error_msg = f"Error de base de datos: {str(e)}"
            usuario = None
        finally:
            cursor.close()
            conexion.close()

        if usuario:
            session["usuario_id"] = usuario["id"]
            session["nombre"]     = usuario["nombre"]
            session["rol"]        = usuario["rol"]

            # Redirigir según el rol
            if usuario["rol"] == "admin":
                return redirect(url_for("admin_panel"))
            return redirect(url_for("index"))
        elif not error_msg:
            error_msg = "El correo no está registrado en el sistema."

    return render_template("login.html",
                           error=error_msg,
                           server_name=NODE_NAME,
                           server_port=NODE_PORT)

# 2. CONSULTAR TAREAS EN TIEMPO REAL - Estudiantes (Lectura mixta)
@app.route("/")
def index():
    if "usuario_id" not in session:
        return redirect(url_for("login"))

    # Si un admin intenta acceder al index de estudiantes, redirigir
    if session.get("rol") == "admin":
        return redirect(url_for("admin_panel"))

    # Lista de tareas disponibles: se lee desde la réplica (no es crítico post-entrega)
    conexion_replica = conectar_replica()
    cursor_replica   = conexion_replica.cursor(dictionary=True)
    cursor_replica.execute("SELECT id, codigo, titulo, descripcion, fecha_limite FROM tareas")
    tareas_disponibles = cursor_replica.fetchall()
    cursor_replica.close()
    conexion_replica.close()

    # IDs de tareas ya entregadas: se consultan en el maestro para evitar
    # que el usuario vea una tarea como "pendiente" justo después de entregarla
    conexion_master = conectar_master()
    cursor_master   = conexion_master.cursor(dictionary=True)
    cursor_master.execute(
        "SELECT tarea_id FROM entregas WHERE usuario_id = %s",
        (session["usuario_id"],)
    )
    entregadas_ids = [row["tarea_id"] for row in cursor_master.fetchall()]
    cursor_master.close()
    conexion_master.close()

    from datetime import datetime
    ahora = datetime.now()

    return render_template("index.html",
                           tareas=tareas_disponibles,
                           entregadas=entregadas_ids,
                           nombre=session["nombre"],
                           ahora=ahora,
                           server_name=NODE_NAME,
                           server_port=NODE_PORT)

# 3. ENTREGAR TAREA - Estudiantes (Escritura atómica en el Maestro)
@app.route("/agregar", methods=["POST"])
def agregar_entrega():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
    if session.get("rol") == "admin":
        return redirect(url_for("admin_panel"))

    usuario_id = session["usuario_id"]

    # Validar tarea_id: debe ser un entero positivo.
    # Evita ValueError, entradas malformadas y HTTP 500 cuando el
    # identificador no es numérico o es menor o igual a cero.
    try:
        tarea_id = int(request.form["tarea_id"])
        if tarea_id <= 0:
            raise ValueError
    except (KeyError, ValueError, TypeError):
        return render_template("resultado.html",
                               status="error",
                               mensaje="Identificador de tarea inválido.",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 400

    respuesta = request.form.get("respuesta", "").strip()

    # Validar que la respuesta no esté vacía
    if not respuesta:
        return render_template("resultado.html",
                               status="error",
                               mensaje="La respuesta no puede estar vacía.",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 400

    # Limitar la respuesta a 5 000 caracteres
    if len(respuesta) > 5000:
        return render_template("resultado.html",
                               status="error",
                               mensaje="La respuesta no puede superar los 5 000 caracteres.",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 400

    # INSERCIÓN ATÓMICA en el Maestro:
    # - Valida que la tarea exista (JOIN implícito con WHERE t.id = %s)
    # - Valida que el plazo no haya vencido (NOW() <= fecha_limite)
    # - La restricción UNIQUE KEY unica_entrega(usuario_id, tarea_id) impide
    #   duplicados y lanza IntegrityError (código 1062) → HTTP 409
    conexion       = conectar_master()
    cursor         = conexion.cursor()
    affected_rows  = 0
    integrity_error = False

    try:
        cursor.execute(
            """
            INSERT INTO entregas (usuario_id, tarea_id, respuesta, fecha_entrega)
            SELECT %s, t.id, %s, NOW()
            FROM   tareas AS t
            WHERE  t.id = %s
              AND  NOW() <= t.fecha_limite
            """,
            (usuario_id, respuesta, tarea_id)
        )
        conexion.commit()
        affected_rows = cursor.rowcount
    except mysql.connector.IntegrityError as e:
        conexion.rollback()
        if e.errno == 1062:          # Duplicate entry — UNIQUE KEY violado
            integrity_error = True
        else:
            cursor.close()
            conexion.close()
            return render_template("resultado.html",
                                   status="error",
                                   mensaje=f"Error de integridad en la base de datos: {e}",
                                   server_name=NODE_NAME,
                                   server_port=NODE_PORT), 500
    except Exception as e:
        conexion.rollback()
        cursor.close()
        conexion.close()
        return render_template("resultado.html",
                               status="error",
                               mensaje=f"Error en la base de datos: {e}",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 500
    finally:
        cursor.close()
        conexion.close()

    # Duplicado detectado por la restricción UNIQUE (concurrencia extrema)
    if integrity_error:
        return render_template("resultado.html",
                               status="error",
                               mensaje="Ya has realizado una entrega para esta tarea. Solo se permite una entrega.",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 409

    # INSERT afectó 0 filas: tarea inexistente o plazo vencido.
    # Se hace una segunda consulta al Maestro para distinguir el motivo.
    if affected_rows == 0:
        conexion_diag = conectar_master()
        cursor_diag   = conexion_diag.cursor(dictionary=True)
        try:
            cursor_diag.execute(
                "SELECT id, fecha_limite FROM tareas WHERE id = %s",
                (tarea_id,)
            )
            tarea = cursor_diag.fetchone()
        finally:
            cursor_diag.close()
            conexion_diag.close()

        if not tarea:
            return render_template("resultado.html",
                                   status="error",
                                   mensaje="La tarea especificada no existe.",
                                   server_name=NODE_NAME,
                                   server_port=NODE_PORT), 404

        # La tarea existe pero el plazo ya venció
        fecha_limite = tarea["fecha_limite"]
        return render_template("resultado.html",
                               status="error",
                               mensaje=f"Plazo vencido. No se permiten entregas después de: {fecha_limite.strftime('%Y-%m-%d %H:%M:%S')}",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 422

    # Éxito: redirigir a mis-entregas (que lee del maestro para consistencia inmediata)
    return redirect(url_for("mis_entregas"))

# 4. VISUALIZAR TAREAS ENVIADAS - Estudiantes
# Lee desde el Maestro para garantizar consistencia inmediata después de entregar
@app.route("/mis-entregas")
def mis_entregas():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
    if session.get("rol") == "admin":
        return redirect(url_for("admin_panel"))

    # Se usa el maestro para garantizar lectura inmediata
    # después de registrar una entrega.
    conexion = conectar_master()
    cursor   = conexion.cursor(dictionary=True)
    query = """
        SELECT t.titulo, e.respuesta, e.fecha_entrega
        FROM   entregas AS e
        INNER JOIN tareas AS t ON t.id = e.tarea_id
        WHERE  e.usuario_id = %s
        ORDER  BY e.fecha_entrega DESC
    """
    cursor.execute(query, (session["usuario_id"],))
    entregas_alumno = cursor.fetchall()
    cursor.close()
    conexion.close()

    return render_template("mis_entregas.html",
                           entregas=entregas_alumno,
                           nombre=session["nombre"],
                           server_name=NODE_NAME,
                           server_port=NODE_PORT)

# ================= RUTAS DE ADMINISTRADOR =================

# 5. PANEL DE ADMINISTRADOR (Lectura)
@app.route("/admin")
def admin_panel():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
    if session.get("rol") != "admin":
        return redirect(url_for("index"))

    # Leer lista de usuarios y tareas registrados desde la réplica
    conexion = conectar_replica()
    cursor   = conexion.cursor(dictionary=True)

    cursor.execute("SELECT id, nombre, correo, rol FROM usuarios ORDER BY id DESC")
    lista_usuarios = cursor.fetchall()

    cursor.execute("SELECT id, codigo, titulo, fecha_limite FROM tareas ORDER BY id DESC")
    lista_tareas = cursor.fetchall()

    cursor.close()
    conexion.close()

    return render_template("admin.html",
                           usuarios=lista_usuarios,
                           tareas=lista_tareas,
                           nombre=session["nombre"],
                           server_name=NODE_NAME,
                           server_port=NODE_PORT)

# 6. CREAR USUARIOS - Administrador (Escritura - Master)
@app.route("/admin/crear-usuario", methods=["POST"])
def crear_usuario():
    if "usuario_id" not in session or session.get("rol") != "admin":
        return redirect(url_for("login"))

    nombre = request.form["nombre"].strip()
    correo = request.form["correo"].strip()
    rol    = request.form["rol"].strip()

    if not nombre or not correo or not rol:
        return render_template("resultado.html",
                               status="error",
                               mensaje="Todos los campos del usuario son requeridos.",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 400

    # ESCRITURA: Conexión directa al Master
    conexion = conectar_master()
    cursor   = conexion.cursor()
    success  = False
    error_db = ""
    try:
        cursor.execute(
            "INSERT INTO usuarios (nombre, correo, rol) VALUES (%s, %s, %s)",
            (nombre, correo, rol)
        )
        conexion.commit()
        success = True
    except Exception as e:
        conexion.rollback()
        error_db = str(e)
    finally:
        cursor.close()
        conexion.close()

    if success:
        return redirect(url_for("admin_panel"))
    else:
        return render_template("resultado.html",
                               status="error",
                               mensaje=f"Error al registrar usuario: {error_db}",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 500

# 7. CREAR TAREAS - Administrador (Escritura - Master)
@app.route("/admin/crear-tarea", methods=["POST"])
def crear_tarea():
    if "usuario_id" not in session or session.get("rol") != "admin":
        return redirect(url_for("login"))

    codigo           = request.form["codigo"].strip().upper()
    titulo           = request.form["titulo"].strip()
    descripcion      = request.form["descripcion"].strip()
    fecha_limite_raw = request.form["fecha_limite"].strip()  # formato datetime-local: 2026-07-20T23:59

    if not codigo or not titulo or not descripcion or not fecha_limite_raw:
        return render_template("resultado.html",
                               status="error",
                               mensaje="Todos los campos de la tarea son requeridos.",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 400

    # Convertir el formato del input datetime-local a formato MySQL DATETIME YYYY-MM-DD HH:MM:SS
    from datetime import datetime
    try:
        fecha_limite = datetime.strptime(fecha_limite_raw, "%Y-%m-%dT%H:%M")
    except Exception:
        return render_template("resultado.html",
                               status="error",
                               mensaje="Formato de fecha inválido.",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 400

    # ESCRITURA: Conexión directa al Master
    conexion = conectar_master()
    cursor   = conexion.cursor()
    success  = False
    error_db = ""
    try:
        cursor.execute(
            "INSERT INTO tareas (codigo, titulo, descripcion, fecha_limite) VALUES (%s, %s, %s, %s)",
            (codigo, titulo, descripcion, fecha_limite)
        )
        conexion.commit()
        success = True
    except Exception as e:
        conexion.rollback()
        error_db = str(e)
    finally:
        cursor.close()
        conexion.close()

    if success:
        return redirect(url_for("admin_panel"))
    else:
        return render_template("resultado.html",
                               status="error",
                               mensaje=f"Error al registrar la tarea: {error_db}",
                               server_name=NODE_NAME,
                               server_port=NODE_PORT), 500

# Cerrar Sesión
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    port = int(NODE_PORT)
    app.run(host="0.0.0.0", port=port, debug=FLASK_DEBUG)
