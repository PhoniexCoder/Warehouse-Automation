#!/bin/bash
set -e

# Run seed script if present
if [ -f /app/seed.sh ]; then
  echo "Running seed script..."
  python3 -c "
import urllib.request, json, sys, time

# Wait for the API to be ready
for i in range(30):
    try:
        urllib.request.urlopen('http://localhost:8001/health', timeout=2)
        break
    except Exception:
        time.sleep(1)

# Create admin user
data = json.dumps({'username': 'admin', 'email': 'admin@warehouse.local', 'password': 'admin', 'warehouse_id': None}).encode()
req = urllib.request.Request(
    'http://localhost:8001/api/v1/register',
    data=data,
    headers={'Content-Type': 'application/json'}
)
try:
    resp = urllib.request.urlopen(req)
    print('Admin user created.')
except urllib.error.HTTPError as e:
    body = e.read().decode()
    if 'already' in body.lower():
        print('Admin user already exists.')
    else:
        print(f'Seed warning: {e.code} {body}')
" &
fi

# Start the server
exec uvicorn app.main:app --host 0.0.0.0 --port 8001
