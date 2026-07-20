FROM python:3.10-slim

WORKDIR /app

# Instalar dependencias necesarias
COPY App/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el directorio de la aplicación y las plantillas compartidas
COPY App/ ./App/
COPY templates/ ./templates/

# El puerto expuesto y el comando final se sobreescriben en el docker-compose.yaml
