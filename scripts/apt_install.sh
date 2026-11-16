#!/usr/bin/env bash
# Install apt packages without depending on azure.archive.ubuntu.com.
#
# GitHub-hosted Ubuntu routes apt through that mirror. When the name fails to
# resolve, apt-get exits 100 before tests start and PR Tests / CI Gate fails.
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

mirror_url="https://archive.ubuntu.com/ubuntu"
mirror_file="${apt_dir}/apt-mirrors.txt"
if [ -f "$mirror_file" ]; then
  printf '%s\n' "${mirror_url}/" | run tee "$mirror_file" >/dev/null
fi

shopt -s nullglob
for sources in \
  "${apt_dir}/sources.list" \
  "${apt_dir}/sources.list.d/"*.list \
  "${apt_dir}/sources.list.d/"*.sources
do
  run sed -i \
    -e "s|http://azure.archive.ubuntu.com/ubuntu|${mirror_url}|g" \
    -e "s|https://azure.archive.ubuntu.com/ubuntu|${mirror_url}|g" \
    -e "s|mirror+file:/etc/apt/apt-mirrors.txt|${mirror_url}|g" \
    "$sources"
done

if [ "$rewrite_only" -eq 1 ]; then
  exit 0
fi

attempts=5
for attempt in 1 2 3 4 5; do
  if run apt-get update && run apt-get install -y "$@"; then
    exit 0
  fi
  if [ "$attempt" -eq "$attempts" ]; then
    echo "apt install failed after ${attempts} attempts" >&2
    exit 1
  fi
  sleep $((attempt * 5))
done
