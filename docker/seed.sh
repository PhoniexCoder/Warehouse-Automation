#!/bin/bash
set -e

echo "Waiting for business-backend to be ready..."
until python3 -c "import urllib.request; urllib.request.urlopen('http://business:8001/health')" 2>/dev/null; do
  sleep 2
done
echo "Business backend is up."

echo "Creating admin user..."
python3 -c "
import urllib.request, json, sys

data = json.dumps({'username': 'admin', 'email': 'admin@warehouse.local', 'password': 'admin', 'warehouse_id': None}).encode()
req = urllib.request.Request(
    'http://business:8001/api/v1/register',
    data=data,
    headers={'Content-Type': 'application/json'}
)
try:
    resp = urllib.request.urlopen(req)
    print('Admin user created successfully.')
except urllib.error.HTTPError as e:
    body = e.read().decode()
    if 'already registered' in body or 'already exists' in body:
        print('Admin user already exists, skipping.')
    else:
        print(f'Unexpected error: {e.code} {body}')
        sys.exit(1)
"
echo "Seed complete."
