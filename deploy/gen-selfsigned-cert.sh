#!/usr/bin/env bash
# Generate a self-signed TLS cert + key for the RADONAIX nginx proxy.
# For internal / IP-based deployments where Let's Encrypt isn't an option.
#
# Usage:
#   deploy/gen-selfsigned-cert.sh [HOST_OR_IP] [OUT_DIR]
#     HOST_OR_IP  default: 10.200.36.156
#     OUT_DIR     default: /etc/nginx/certs   (use deploy/nginx/certs for Docker)
#
# Examples:
#   sudo deploy/gen-selfsigned-cert.sh                      # bare VM, default IP
#   deploy/gen-selfsigned-cert.sh 10.200.36.156 deploy/nginx/certs   # Docker
set -euo pipefail

HOST="${1:-10.200.36.156}"
OUT="${2:-/etc/nginx/certs}"

# IP address → IP SAN, otherwise DNS SAN (browsers validate against the SAN).
if [[ "$HOST" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    SAN="IP:$HOST"
else
    SAN="DNS:$HOST"
fi

mkdir -p "$OUT"
openssl req -x509 -nodes -days 825 -newkey rsa:2048 \
    -keyout "$OUT/radonaix.key" \
    -out    "$OUT/radonaix.crt" \
    -subj   "/CN=$HOST" \
    -addext "subjectAltName=$SAN"
chmod 600 "$OUT/radonaix.key"

echo "Wrote:"
echo "  $OUT/radonaix.crt"
echo "  $OUT/radonaix.key   (CN=$HOST, SAN=$SAN, valid 825 days)"
echo "Reload nginx to pick it up:  sudo nginx -t && sudo systemctl reload nginx"
