SET NAMES 'utf8mb4';

-- Crear base de datos si no existe
CREATE DATABASE IF NOT EXISTS informacion;
USE informacion;

-- 1. Tabla Usuarios (unificada para Estudiantes y Administradores con Contraseña)
CREATE TABLE IF NOT EXISTS usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    correo VARCHAR(100) UNIQUE NOT NULL,
    password VARCHAR(255) NOT NULL DEFAULT '123456',
    rol VARCHAR(20) DEFAULT 'estudiante'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 2. Tabla Tareas
CREATE TABLE IF NOT EXISTS tareas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    codigo VARCHAR(20) UNIQUE NOT NULL,
    titulo VARCHAR(150) NOT NULL,
    descripcion TEXT NOT NULL,
    fecha_limite DATETIME NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- 3. Tabla Entregas (Relación Usuario - Tarea con Respuesta)
CREATE TABLE IF NOT EXISTS entregas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    usuario_id INT NOT NULL,
    tarea_id INT NOT NULL,
    respuesta TEXT NOT NULL,
    fecha_entrega DATETIME NOT NULL,
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE CASCADE,
    FOREIGN KEY (tarea_id) REFERENCES tareas(id) ON DELETE CASCADE,
    UNIQUE KEY unica_entrega (usuario_id, tarea_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Datos Semilla: Usuarios de prueba con contraseña (Estudiantes y Administrador)
INSERT IGNORE INTO usuarios (id, nombre, correo, password, rol) VALUES
(1, 'Gabriel Escobar', 'gabriel.escobar@epn.edu.ec', '123456', 'estudiante'),
(2, 'Ana Belén Guevara', 'ana.belen@epn.edu.ec', '123456', 'estudiante'),
(3, 'Estudiante de Prueba', 'prueba@epn.edu.ec', '123456', 'estudiante'),
(4, 'Administrador EPN', 'admin@epn.edu.ec', 'admin123', 'admin');

-- Datos Semilla: Tareas del período (con plazos válidos y uno ya expirado para validaciones)
INSERT IGNORE INTO tareas (id, codigo, titulo, descripcion, fecha_limite) VALUES
(1, 'TAREA-01', 'Configuración del Balanceador NGINX', 'Diseñar y configurar NGINX como un balanceador de carga distribuido por pesos.', '2026-08-30 23:59:59'),
(2, 'TAREA-02', 'Replicación Master-Slave en MySQL', 'Implementar y demostrar un esquema de replicación de bases de datos por GTID.', '2026-08-31 23:59:59'),
(3, 'TAREA-03', 'Expirada: Setup Inicial Docker', 'Tarea del primer bimestre para probar que el sistema no permita subir entregas atrasadas.', '2026-07-10 12:00:00');

-- Configuración del usuario para la replicación del Slave
CREATE USER IF NOT EXISTS 'replica_user'@'%' IDENTIFIED WITH mysql_native_password BY 'replica_password';
GRANT REPLICATION SLAVE ON *.* TO 'replica_user'@'%';
FLUSH PRIVILEGES;
