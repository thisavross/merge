#!/usr/bin/env bash
# Jalankan dari mana saja; otomatis pindah ke root repo Moodle.
set -euo pipefail

# Docker Desktop on Mac: CLI may not be in PATH until "cli symlinks" are installed.
if ! command -v docker >/dev/null 2>&1; then
  for _docker_bin in \
    "/Applications/Docker.app/Contents/Resources/bin" \
    "${HOME}/.docker/bin"; do
    if [[ -x "${_docker_bin}/docker" ]]; then
      export PATH="${_docker_bin}:${PATH}"
      break
    fi
  done
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "Error: perintah 'docker' tidak ditemukan."
  echo "  - Pastikan Docker Desktop terbuka dan status 'Engine running'."
  echo "  - Di Docker Desktop: Settings → Advanced → centang CLI / symlink, lalu restart app."
  echo "  - Atau buka terminal baru setelah Docker Desktop fully started."
  exit 127
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
ENV_FILE="${SCRIPT_DIR}/.env"

cd "${REPO_ROOT}"

if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${SCRIPT_DIR}/.env.example" ]]; then
    cp "${SCRIPT_DIR}/.env.example" "${ENV_FILE}"
    echo "File dibuat: ${ENV_FILE}"
    echo "Edit MYSQL_PASSWORD dan MOODLE_DATAROOT_HOST, lalu jalankan lagi."
    exit 1
  fi
  echo "Error: ${ENV_FILE} tidak ada. Copy dari .env.example dulu."
  exit 1
fi

exec docker compose -f "${COMPOSE_FILE}" --env-file "${ENV_FILE}" "$@"
