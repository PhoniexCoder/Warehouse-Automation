#!/bin/sh
set -e

NVR_HOST="${NVR_HOST:-192.168.1.35}"
NVR_PORT="${NVR_PORT:-34567}"
NVR_USER="${NVR_USER:-uxdp}"
NVR_PASS="${NVR_PASS:-cw8adc}"

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

echo "--- Generated go2rtc.yaml ---"
cat /config/go2rtc.yaml
echo "--- Starting go2rtc ---"

exec /usr/local/bin/go2rtc
