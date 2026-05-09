#!/usr/bin/env bash
set -e

echo "Iniciando Xvfb em ${DISPLAY} ..."
Xvfb ${DISPLAY} -screen 0 1920x1080x24 -ac +extension RANDR >/tmp/xvfb.log 2>&1 &
sleep 2

echo "Validando Chromium..."
which chromium || true
which chromedriver || true
python --version

echo "Iniciando scheduler Railway com Xvfb..."
python railway_scheduler_headless.py
