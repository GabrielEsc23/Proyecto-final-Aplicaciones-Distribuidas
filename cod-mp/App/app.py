from flask import Flask, render_template, request, redirect, session, url_for
import mysql.connector
import os
from datetime import datetime

# Inicializar Flask apuntando al directorio de plantillas compartido en la raíz del proyecto
app = Flask(__name__, template_folder='../templates')
app.secret_key = "infraestructura_distribuida_secret_key"

# Variables de Entorno para identificar el nodo actual
NODE_NAME = os.environ.get("NODE_NAME", "Desarrollo Local")
NODE_PORT = os.environ.get("NODE_PORT", "5000")

# Función para conectarse al contenedor Maestro (Escrituras)
def conectar_master():
    return mysql.connector.connect(
        host="mysql_principal",
        user="root",
        password="root",
        database="informacion",
        charset="utf8mb4"
    )

# Función para conectarse al contenedor Réplica (Lecturas)
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
        password = request.form["password"].strip()
        
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

        # Validar existencia de usuario y contraseña
        if usuario and usuario.get("password") == password:
            session["usuario_id"] = usuario["id"]
            session["nombre"] = usuario["nombre"]
            session["rol"] = usuario["rol"]
            
            # Redirigir según el rol
            if usuario["rol"] == "admin":
                return redirect(url_for("admin_panel"))
            return redirect(url_for("index"))
        elif not error_msg:
            error_msg = "Correo o contraseña incorrectos."
            
    return render_template("login.html", 
                           error=error_msg, 
                           server_name=NODE_NAME, 
                           server_port=NODE_PORT)

# 2. CONSULTAR TAREAS EN TIEMPO REAL - Estudiantes (Lectura)
@app.route("/")
def index():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
    
    # Si un admin intenta acceder al index de estudiantes, redirigir
    if session.get("rol") == "admin":
        return redirect(url_for("admin_panel"))
    
    # Lectura de tareas, va a la réplica
    conexion = conectar_replica()
    cursor = conexion.cursor(dictionary=True)
    cursor.execute("SELECT id, codigo, titulo, descripcion, fecha_limite FROM tareas")
    tareas_disponibles = cursor.fetchall()
    
    # Obtener qué tareas ya han sido entregadas por este alumno
    cursor.execute("SELECT tarea_id FROM entregas WHERE usuario_id = %s", (session["usuario_id"],))
    entregadas_ids = [row["tarea_id"] for row in cursor.fetchall()]
    
    cursor.close()
    conexion.close()
    
    ahora = datetime.now()
    
    return render_template("index.html", 
                           tareas=tareas_disponibles, 
                           entregadas=entregadas_ids,
                           nombre=session["nombre"], 
                           ahora=ahora,
                           server_name=NODE_NAME, 
                           server_port=NODE_PORT)

# 3. ENTREGAR TAREA - Estudiantes (Escritura - Master)
@app.route("/agregar", methods=["POST"])
def agregar_entrega():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
    if session.get("rol") == "admin":
        return redirect(url_for("admin_panel"))
        
    usuario_id = session["usuario_id"]
    tarea_id = int(request.form["tarea_id"])
    respuesta = request.form["respuesta"].strip()
    
    if not respuesta:
        return render_template("resultado.html", 
                               status="error", 
                               mensaje="La respuesta no puede estar vacía.", 
                               server_name=NODE_NAME, 
                               server_port=NODE_PORT), 400

    # Comprobar la tarea en la réplica
    conexion_lectura = conectar_replica()
    cursor_lectura = conexion_lectura.cursor(dictionary=True)
    cursor_lectura.execute("SELECT titulo, fecha_limite FROM tareas WHERE id = %s", (tarea_id,))
    tarea = cursor_lectura.fetchone()
    
    if not tarea:
        cursor_lectura.close()
        conexion_lectura.close()
        return render_template("resultado.html", 
                               status="error", 
                               mensaje="La tarea especificada no existe.", 
                               server_name=NODE_NAME, 
                               server_port=NODE_PORT), 404
                               
    # VALIDACIÓN 1: Fecha y hora límite
    ahora = datetime.now()
    fecha_limite = tarea["fecha_limite"]
    if ahora > fecha_limite:
        cursor_lectura.close()
        conexion_lectura.close()
        return render_template("resultado.html", 
                               status="error", 
                               mensaje=f"Plazo vencido. No se permiten entregas después de: {fecha_limite.strftime('%Y-%m-%d %H:%M:%S')}", 
                               server_name=NODE_NAME, 
                               server_port=NODE_PORT), 400

    # VALIDACIÓN 2: Entrega duplicada
    cursor_lectura.execute("SELECT id FROM entregas WHERE usuario_id = %s AND tarea_id = %s", (usuario_id, tarea_id))
    ya_entregado = cursor_lectura.fetchone()
    cursor_lectura.close()
    conexion_lectura.close()

    if ya_entregado:
        return render_template("resultado.html", 
                               status="error", 
                               mensaje="Ya has realizado una entrega para esta tarea. Solo se permite una entrega.", 
                               server_name=NODE_NAME, 
                               server_port=NODE_PORT), 400

    # ESCRITURA: Conectamos directamente al Master
    conexion_escritura = conectar_master()
    cursor_escritura = conexion_escritura.cursor()
    success = False
    error_db = ""
    try:
        cursor_escritura.execute(
            "INSERT INTO entregas (usuario_id, tarea_id, respuesta, fecha_entrega) VALUES (%s, %s, %s, %s)",
            (usuario_id, tarea_id, respuesta, ahora)
        )
        conexion_escritura.commit()
        success = True
    except Exception as e:
        conexion_escritura.rollback()
        error_db = str(e)
    finally:
        cursor_escritura.close()
        conexion_escritura.close()

    if success:
        return redirect(url_for("mis_entregas"))
    else:
        return render_template("resultado.html", 
                               status="error", 
                               mensaje=f"Error en la base de datos al guardar la tarea: {error_db}", 
                               server_name=NODE_NAME, 
                               server_port=NODE_PORT), 500

# 4. VISUALIZAR TAREAS ENVIADAS - Estudiantes (Lectura)
@app.route("/mis-entregas")
def mis_entregas():
    if "usuario_id" not in session:
        return redirect(url_for("login"))
    if session.get("rol") == "admin":
        return redirect(url_for("admin_panel"))
        
    # Lectura, va a la réplica
    conexion = conectar_replica()
    cursor = conexion.cursor(dictionary=True)
    query = """
        SELECT t.titulo, e.respuesta, e.fecha_entrega
        FROM entregas e
        JOIN tareas t ON e.tarea_id = t.id
        WHERE e.usuario_id = %s
        ORDER BY e.fecha_entrega DESC
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
    cursor = conexion.cursor(dictionary=True)
    
    cursor.execute("SELECT id, nombre, correo, password, rol FROM usuarios ORDER BY id DESC")
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
    password = request.form["password"].strip()
    rol = request.form["rol"].strip()
    
    if not nombre or not correo or not password or not rol:
        return render_template("resultado.html", 
                               status="error", 
                               mensaje="Todos los campos del usuario (incluyendo la contraseña) son requeridos.", 
                               server_name=NODE_NAME, 
                               server_port=NODE_PORT), 400
                               
    # ESCRITURA: Conexión directa al Master
    conexion = conectar_master()
    cursor = conexion.cursor()
    success = False
    error_db = ""
    try:
        cursor.execute(
            "INSERT INTO usuarios (nombre, correo, password, rol) VALUES (%s, %s, %s, %s)",
            (nombre, correo, password, rol)
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
        
    codigo = request.form["codigo"].strip().upper()
    titulo = request.form["titulo"].strip()
    descripcion = request.form["descripcion"].strip()
    fecha_limite_raw = request.form["fecha_limite"].strip() # Recibe formato datetime-local: 2026-07-20T23:59
    
    if not codigo or not titulo or not descripcion or not fecha_limite_raw:
        return render_template("resultado.html", 
                               status="error", 
                               mensaje="Todos los campos de la tarea son requeridos.", 
                               server_name=NODE_NAME, 
                               server_port=NODE_PORT), 400
                               
    # Convertir el formato del input datetime-local a formato MySQL DATETIME YYYY-MM-DD HH:MM:SS
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
    cursor = conexion.cursor()
    success = False
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
    app.run(host="0.0.0.0", port=port, debug=True)
