#!/bin/bash
set -e

: "${ADMIN_USERNAME:?ADMIN_USERNAME must be set}"
: "${ADMIN_PASSWORD:?ADMIN_PASSWORD must be set}"
: "${ADMIN_EMAIL:?ADMIN_EMAIL must be set}"

echo "Waiting for business-backend to be ready..."
until python3 -c "import urllib.request; urllib.request.urlopen('http://business:8001/health')" 2>/dev/null; do
  sleep 2
done
echo "Business backend is up."

echo "Creating admin user..."
python3 -c "
import urllib.request, json, sys, os

data = json.dumps({
    'username': os.environ['ADMIN_USERNAME'],
    'email': os.environ['ADMIN_EMAIL'],
    'password': os.environ['ADMIN_PASSWORD'],
    'warehouse_id': None
}).encode()
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
