#!/bin/sh

# Prüfe, ob ip_address und password gesetzt sind
if [ -z "$IP_ADDRESS" ] || [ -z "$PASSWORD" ]; then
  echo "ERROR: IP_ADDRESS und PASSWORD müssen als Umgebungsvariablen gesetzt werden." >&2
  exit 1
fi

# Setze Variablen für envsubst
export ip_address="$IP_ADDRESS"
export password="$PASSWORD"

# Erzeuge die config.yml aus dem Template
envsubst < "$CONFIG_TEMPLATE" > "$CONFIG_OUTPUT"

# Starte das Python-Skript
exec python3 run.py "$CONFIG_OUTPUT"
