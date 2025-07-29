# docker/Dockerfile

FROM python:3.12-slim

# Install envsubst (Teil von gettext)
RUN apt-get update && \
    apt-get install -y gettext && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Arbeitsverzeichnis im Container
WORKDIR /app

# Zuerst den gesamten Code kopieren (inkl. Unterordner)
COPY . .

# Dann requirements installieren
RUN pip install --no-cache-dir -r requirements.txt

# Template der config.yml als config.template.yml erwarten
ENV CONFIG_TEMPLATE=/app/config.yml.template
ENV CONFIG_OUTPUT=/app/config.yml

# Entrypoint-Skript kopieren
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
