#!/bin/bash
set -e

: "${ADMIN_USERNAME:?ADMIN_USERNAME must be set}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD must be set}"
: "${ADMIN_EMAIL:?ADMIN_EMAIL must be set}"

# Start uvicorn in the background
uvicorn app.main:app --host 0.0.0.0 --port 8001 &
UVICORN_PID=$!

# Wait for the server to be ready
for i in $(seq 1 30); do
    if python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8001/health', timeout=2)" 2>/dev/null; then
        break
    fi
    sleep 1
done

# Seed admin user using env vars
python3 -c "
import urllib.request, json, os

data = json.dumps({
    'username': os.environ['ADMIN_USERNAME'],
    'email': os.environ['ADMIN_EMAIL'],
    'password': os.environ['ADMIN_PASSWORD'],
    'role': 'ADMIN'
}).encode()
req = urllib.request.Request(
    'http://localhost:8001/api/v1/register',
    data=data,
    headers={'Content-Type': 'application/json'}
)
try:
    resp = urllib.request.urlopen(req)
    print('Admin user created.')
except Exception as e:
    if hasattr(e, 'read'):
        body = e.read().decode()
        if 'already' in body.lower():
            print('Admin user already exists.')
        else:
            print(f'Seed warning: {e.code} {body}')
    else:
        print(f'Seed warning: {e}')
"

# Keep running and wait for uvicorn
wait $UVICORN_PID
