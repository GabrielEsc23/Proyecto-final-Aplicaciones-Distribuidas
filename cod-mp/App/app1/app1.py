from flask import Flask, render_template, request, redirect, session, url_for
import mysql.connector

app = Flask(__name__)
# Definimos una secret_key en Flask para poder usar sesiones de usuario
app.secret_key = "infraestructura_distribuida_secret_key"

# Función reutilizable para conectarse al contenedor Maestro de MySQL
def conectar_bd():
    return mysql.connector.connect(
        host="mysql_principal", # Nombre del servicio en tu docker-compose
        user="root",
        password="root",
        database="informacion"
    )

# 1. RUTA DE LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form["correo"]
        
        conexion = conectar_bd()
        cursor = conexion.cursor(dictionary=True)
        # Buscamos si el estudiante ya esta registrado en la BD
        cursor.execute("SELECT * FROM estudiantes WHERE correo = %s", (correo,))
        estudiante = cursor.fetchone()
        cursor.close()
        conexion.close()

        if estudiante:
            # Guardamos los datos del alumno en la sesion del navegador
            session["estudiante_id"] = estudiante["id"]
            session["nombre"] = estudiante["nombre"]
            return redirect(url_for("index"))
        else:
            return "<h3>Error: El correo no esta registrado como estudiante.</h3><a href='/login'>Volver</a>"
            
    return render_template("login.html")

# 2. CONSULTAR TAREAS EN TIEMPO REAL
@app.route("/")
def index():
    # Si el alumno no ha iniciado sesion, lo redirigimos al login
    if "estudiante_id" not in session:
        return redirect(url_for("login"))
    
    conexion = conectar_bd()
    cursor = conexion.cursor(dictionary=True)
    # Obtenemos todas las tareas previamente registradas en la base de datos
    cursor.execute("SELECT id, codigo, titulo, descripcion, fecha_limite FROM tareas")
    tareas_disponibles = cursor.fetchall()
    cursor.close()
    conexion.close()
    
    return render_template("index.html", tareas=tareas_disponibles, nombre=session["nombre"])

# 3. VISUALIZAR TAREAS ENVIADAS (Entregas realizadas)
@app.route("/mis-entregas")
def mis_entregas():
    if "estudiante_id" not in session:
        return redirect(url_for("login"))
        
    conexion = conectar_bd()
    cursor = conexion.cursor(dictionary=True)
    # Relacionamos las entregas del alumno con el titulo de la tarea correspondiente
    query = """
        SELECT t.titulo, e.respuesta 
        FROM entregas e
        JOIN tareas t ON e.tarea_id = t.id
        WHERE e.estudiante_id = %s
    """
    cursor.execute(query, (session["estudiante_id"],))
    entregas_alumno = cursor.fetchall()
    cursor.close()
    conexion.close()
    
    return render_template("mis_entregas.html", entregas=entregas_alumno)

# Ruta para cerrar sesion
@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

if __name__ == "__main__":
    # Mantienes el puerto configurado en tu docker-compose 
    app.run(host="0.0.0.0", port=5001, debug=True)