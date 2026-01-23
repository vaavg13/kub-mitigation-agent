#!/bin/bash
set -euo pipefail

# Usage:
#   ./isolate_cores.sh apply [CORES] [IRQ_CPUS]
#   ./isolate_cores.sh verify
#   ./isolate_cores.sh revert [CORES] [IRQ_CPUS]
#
# Defaults match your selected layout on a 48-thread CPU:
#   CORES    = 16-23,40-47  (isolated CPU set)
#   IRQ_CPUS = 0-15,24-39   (keep IRQs off isolated CPUs)

SUBCMD=${1:-}

case "$SUBCMD" in
  apply)
    CORES=${2:-"16-23,40-47"}
    IRQ_CPUS=${3:-"0-15,24-39"}
    echo "Applying CPU isolation: isolcpus=$CORES nohz_full=$CORES rcu_nocbs=$CORES irqaffinity=$IRQ_CPUS"
    sudo grubby --update-kernel=ALL --args="isolcpus=${CORES} nohz_full=${CORES} rcu_nocbs=${CORES} irqaffinity=${IRQ_CPUS}"
    echo "Done. Reboot is required to take effect."
    ;;

  verify)
    echo "Kernel cmdline:"
    cat /proc/cmdline || true
    echo
    echo "Isolated CPUs (after reboot):"
    cat /sys/devices/system/cpu/isolated || true
    ;;

  revert)
    CORES=${2:-"16-23,40-47"}
    IRQ_CPUS=${3:-"0-15,24-39"}
    echo "Reverting CPU isolation for: isolcpus=$CORES nohz_full=$CORES rcu_nocbs=$CORES irqaffinity=$IRQ_CPUS"
    sudo grubby --update-kernel=ALL --remove-args="isolcpus=${CORES} nohz_full=${CORES} rcu_nocbs=${CORES} irqaffinity=${IRQ_CPUS}"
    echo "Done. Reboot is required to take effect."
    ;;

  *)
    echo "Usage: $0 {apply [CORES] [IRQ_CPUS] | verify | revert [CORES] [IRQ_CPUS]}" >&2
    exit 1
    ;;
esac


