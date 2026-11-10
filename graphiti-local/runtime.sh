#!/usr/bin/env bash
# Reusable runtime checks. No package installation or model downloads here.
start_docker() {
  if docker info >/dev/null 2>&1; then return; fi
  if [[ "$(uname -s)" == Darwin ]] && command -v colima >/dev/null; then
    colima start --cpu 4 --memory 4 >&2
  elif [[ "$(uname -s)" == Linux ]] && command -v systemctl >/dev/null; then
    systemctl --user start docker.service || true
  fi
  if ! docker info >/dev/null 2>&1; then
    printf 'Docker is unavailable. Start your Docker daemon and check user access with docker info.\n' >&2
    return 1
  fi
}
