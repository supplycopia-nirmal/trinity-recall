#!/bin/bash
# Startup script for Trinity Health Recall Management Platform on Port 8010
cd "$(dirname "$0")"
export PORT=8010
echo "=========================================================="
echo " Starting Trinity Health Recall Management Command Center"
echo " Host: http://localhost:8010"
echo " User: trinity.admin@trinity-health.org"
echo " Password: Trinity2026!"
echo "=========================================================="
python3 -m uvicorn main:app --host 0.0.0.0 --port 8010 --reload
