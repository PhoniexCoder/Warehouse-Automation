#!/bin/sh
set -e

: "${NVR_HOST:?NVR_HOST must be set}"
: "${NVR_PORT:=34567}"
: "${NVR_USER:?NVR_USER must be set}"
: "${NVR_PASS:?NVR_PASS must be set}"

cat > /config/go2rtc.yaml <<EOF
log:
  level: trace

api:
  listen: ":1984"

rtsp:
  listen: ":8554"

webrtc:
  listen: ":8555"

streams:
EOF

for i in $(seq 0 8); do
  cat >> /config/go2rtc.yaml <<EOF
  ch${i}:
    - "dvrip://${NVR_USER}:${NVR_PASS}@${NVR_HOST}:${NVR_PORT}?channel=${i}&subtype=1"
EOF
done

echo "go2rtc config generated. Starting go2rtc..."

exec /usr/local/bin/go2rtc
