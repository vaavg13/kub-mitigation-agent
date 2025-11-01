#!/bin/bash
set -euo pipefail

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
CHAOSD_VERSION="${CHAOSD_VERSION:-v1.4.0}"; CHAOSD_PORT="${CHAOSD_PORT:-31767}"

print_status(){ echo -e "${GREEN}[✓]${NC} $1"; }
print_warn(){ echo -e "${YELLOW}[⚠]${NC} $1"; }
print_error(){ echo -e "${RED}[✗]${NC} $1"; }

vagrant_run(){ local out; if out=$(vagrant "$@" 2>&1); then printf '%s\n' "$out" | sed '/^\[fog\]\[WARNING\]/d'; else local s=$?; printf '%s\n' "$out" | sed '/^\[fog\]\[WARNING\]/d'; return $s; fi }

running_vms(){ vagrant_run status --machine-readable | awk -F, '$3=="state"&&$4=="running"{print $2}'; }

install_on_vm(){
  local vm="$1"
  print_status "Installing Chaosd ${CHAOSD_VERSION} on ${vm}"
  vagrant_run ssh "$vm" -c "sudo bash -s" <<EOF
set -euo pipefail
CHAOSD_VERSION='${CHAOSD_VERSION}'; CHAOSD_PORT='${CHAOSD_PORT}'
ARCHIVE="chaosd-\${CHAOSD_VERSION}-linux-amd64.tar.gz"
INSTALL_ROOT="/usr/local"; TARGET_DIR="\${INSTALL_ROOT}/chaosd-\${CHAOSD_VERSION}-linux-amd64"
if [ "\${CHAOSD_VERSION}" = "latest" ]; then URL="https://mirrors.chaos-mesh.org/chaosd-latest-linux-amd64.tar.gz"; else URL="https://mirrors.chaos-mesh.org/\${ARCHIVE}"; fi
apt-get update -y >/dev/null 2>&1 || true; apt-get install -y curl tar stress-ng >/dev/null 2>&1 || true
if [ ! -d "\${TARGET_DIR}" ]; then tmpdir=\$(mktemp -d); trap 'rm -rf "\$tmpdir"' EXIT; curl -fsSL "\${URL}" -o "\$tmpdir/\${ARCHIVE}"; tar -xzf "\$tmpdir/\${ARCHIVE}" -C "\$tmpdir"; mv "\$tmpdir/chaosd-\${CHAOSD_VERSION}-linux-amd64" "\${TARGET_DIR}"; fi
ln -snf "\${TARGET_DIR}/chaosd" /usr/local/bin/chaosd
mkdir -p /var/lib/chaosd /var/log/chaosd
cat >/etc/systemd/system/chaosd.service <<SERVICE
[Unit]
Description=Chaosd
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/chaosd server --host 0.0.0.0 --port ${CHAOSD_PORT}
Restart=on-failure
RestartSec=5
User=root
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
SERVICE
systemctl daemon-reload
systemctl enable chaosd.service >/dev/null 2>&1 || true
systemctl restart chaosd.service
systemctl is-active --quiet chaosd.service
EOF
}

main(){
  local targets=("$@")
  if [ ${#targets[@]} -eq 0 ]; then
    mapfile -t targets < <(running_vms)
  fi
  if [ ${#targets[@]} -eq 0 ]; then print_warn "No running VMs found"; exit 0; fi
  for vm in "${targets[@]}"; do install_on_vm "$vm"; done
  print_status "Chaosd installed on: ${targets[*]}"
}

main "$@"


