#!/bin/bash
set -euo pipefail

: "${CHAOSD_VERSION:?CHAOSD_VERSION is required}"
: "${CHAOSD_PORT:?CHAOSD_PORT is required}"

need_update=0
if ! command -v curl >/dev/null 2>&1; then
    need_update=1
fi

if ! command -v tar >/dev/null 2>&1; then
    need_update=1
fi

if [[ "${need_update}" -eq 1 ]]; then
    apt-get update -y >/dev/null
fi

if ! command -v curl >/dev/null 2>&1; then
    apt-get install -y curl >/dev/null
fi

if ! command -v tar >/dev/null 2>&1; then
    apt-get install -y tar >/dev/null
fi

tmp_dir=$(mktemp -d)
trap 'rm -rf "${tmp_dir}"' EXIT
tarball="chaosd-${CHAOSD_VERSION}-linux-amd64.tar.gz"
url="https://mirrors.chaos-mesh.org/${tarball}"

cd "${tmp_dir}"
curl -fsSLO "${url}"
tar -xzf "${tarball}"

if systemctl list-unit-files | grep -q '^chaosd.service'; then
    systemctl stop chaosd >/dev/null 2>&1 || true
fi

rm -rf /usr/local/chaosd
mv "chaosd-${CHAOSD_VERSION}-linux-amd64" /usr/local/chaosd
ln -sf /usr/local/chaosd/chaosd /usr/local/bin/chaosd

cat >/etc/systemd/system/chaosd.service <<SERVICE
[Unit]
Description=Chaosd Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/chaosd/chaosd server --port ${CHAOSD_PORT}
Restart=always
RestartSec=5
User=root
WorkingDirectory=/usr/local/chaosd

[Install]
WantedBy=multi-user.target
SERVICE

systemctl daemon-reload
systemctl enable --now chaosd >/dev/null

