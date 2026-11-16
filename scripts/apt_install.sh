#!/usr/bin/env bash
# Install apt packages, keeping the runner's original mirror until it fails.
#
# GitHub-hosted Ubuntu points apt at azure.archive.ubuntu.com. That name
# sometimes fails to resolve and apt-get exits 100 before tests start.
# Try the configured sources first. Only after update or install fails,
# switch to the architecture's public mirror and retry: archive.ubuntu.com
# on x86, ports.ubuntu.com/ubuntu-ports on ARM64.
set -euo pipefail

rewrite_only=0
if [ "${1:-}" = "--rewrite-only" ]; then
  rewrite_only=1
  shift
fi

if [ "$rewrite_only" -eq 0 ] && [ "$#" -lt 1 ]; then
  echo "usage: apt_install.sh [--rewrite-only] PACKAGE..." >&2
  exit 2
fi

config_root="${APT_CONFIG_ROOT:-}"
if [ -n "$config_root" ] || [ "$(id -u)" -eq 0 ]; then
  run() { "$@"; }
else
  run() { sudo "$@"; }
fi

if [ -n "$config_root" ]; then
  apt_dir="${config_root}/etc/apt"
else
  apt_dir="/etc/apt"
fi

fallback_mirror() {
  local machine="${APT_FALLBACK_ARCH:-$(uname -m)}"
  case "$machine" in
    aarch64|arm64) printf '%s\n' "https://ports.ubuntu.com/ubuntu-ports" ;;
    *) printf '%s\n' "https://archive.ubuntu.com/ubuntu" ;;
  esac
}

rewrite_mirrors() {
  local mirror_url="$1"
  local mirror_file="${apt_dir}/apt-mirrors.txt"
  if [ -f "$mirror_file" ]; then
    printf '%s\n' "${mirror_url}/" | run tee "$mirror_file" >/dev/null
  fi

  shopt -s nullglob
  local sources
  for sources in \
    "${apt_dir}/sources.list" \
    "${apt_dir}/sources.list.d/"*.list \
    "${apt_dir}/sources.list.d/"*.sources
  do
    run sed -i \
      -e "s|http://azure.archive.ubuntu.com/ubuntu|${mirror_url}|g" \
      -e "s|https://azure.archive.ubuntu.com/ubuntu|${mirror_url}|g" \
      -e "s|http://azure.ports.ubuntu.com/ubuntu-ports|${mirror_url}|g" \
      -e "s|https://azure.ports.ubuntu.com/ubuntu-ports|${mirror_url}|g" \
      -e "s|mirror+file:/etc/apt/apt-mirrors.txt|${mirror_url}|g" \
      "$sources"
  done
}

invoke_apt_get() {
  if [ -n "${APT_GET_BIN:-}" ]; then
    "${APT_GET_BIN}" "$@"
    return
  fi
  run apt-get "$@"
}

try_install() {
  invoke_apt_get update && invoke_apt_get install -y "$@"
}

mirror_url="$(fallback_mirror)"
if [ "$rewrite_only" -eq 1 ]; then
  rewrite_mirrors "$mirror_url"
  exit 0
fi

if try_install "$@"; then
  exit 0
fi

echo "apt failed; retrying with ${mirror_url}" >&2
rewrite_mirrors "$mirror_url"

attempts=4
for attempt in 1 2 3 4; do
  if try_install "$@"; then
    exit 0
  fi
  if [ "$attempt" -eq "$attempts" ]; then
    echo "apt install failed after ${attempts} fallback attempts" >&2
    exit 1
  fi
  sleep $((attempt * 5))
done
