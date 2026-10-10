#!/usr/bin/env bash
set -euo pipefail

scenario="${1:-}"
duration_seconds="${2:-300}"
interval_seconds="${3:-5}"

if [[ "$scenario" != "baseline" && "$scenario" != "otel" ]]; then
  echo "Uso: $0 baseline|otel [duracion_segundos] [intervalo_segundos]" >&2
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/.." && pwd)"
cd "$repo_root"
mkdir -p "$script_dir/results"
out_file="$script_dir/results/${scenario}-resources.csv"

memory_to_bytes() {
  local raw="$1"
  local number unit
  if [[ ! "$raw" =~ ^([0-9]+([.][0-9]+)?)[[:space:]]*([KMGT]i?B|B)$ ]]; then
    echo "No se pudo interpretar la memoria '$raw'" >&2
    exit 1
  fi
  number="${BASH_REMATCH[1]}"
  unit="${BASH_REMATCH[3]}"
  awk -v n="$number" -v u="$unit" 'BEGIN {
    mult["B"]=1
    mult["KiB"]=1024
    mult["MiB"]=1024*1024
    mult["GiB"]=1024*1024*1024
    mult["TiB"]=1024*1024*1024*1024
    mult["KB"]=1000
    mult["MB"]=1000000
    mult["GB"]=1000000000
    mult["TB"]=1000000000000
    printf "%.0f\n", n * mult[u]
  }'
}

declare -A names=()
while IFS= read -r line; do
  [[ -z "$line" ]] && continue
  service="$(printf '%s' "$line" | sed -n 's/.*"Service":"\([^"]*\)".*/\1/p')"
  container="$(printf '%s' "$line" | sed -n 's/.*"Name":"\([^"]*\)".*/\1/p')"
  if [[ "$service" == "service-a" || "$service" == "service-b" ]]; then
    names["$service"]="$container"
  fi
done < <(docker compose ps --format json)

if [[ -z "${names[service-a]:-}" || -z "${names[service-b]:-}" ]]; then
  echo "No están los contenedores service-a y service-b." >&2
  exit 1
fi

printf 'timestamp,service,cpu_percent,memory_bytes\n' > "$out_file"
started="$(date +%s)"
while true; do
  now="$(date +%s)"
  elapsed="$((now - started))"
  if (( elapsed >= duration_seconds )); then
    break
  fi
  stamp="$(date -u +%Y-%m-%dT%H:%M:%S.000Z)"
  while IFS=$'\t' read -r container cpu memory; do
    [[ -z "$container" ]] && continue
    service=""
    if [[ "$container" == "${names[service-a]}" ]]; then
      service="service-a"
    elif [[ "$container" == "${names[service-b]}" ]]; then
      service="service-b"
    else
      echo "Contenedor no esperado en docker stats: $container" >&2
      exit 1
    fi
    cpu="${cpu%%%}"
    memory="${memory%%/*}"
    memory="$(echo "$memory" | xargs)"
    bytes="$(memory_to_bytes "$memory")"
    printf '%s,%s,%s,%s\n' "$stamp" "$service" "$cpu" "$bytes" >> "$out_file"
  done < <(docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}' "${names[service-a]}" "${names[service-b]}")
  now="$(date +%s)"
  elapsed="$((now - started))"
  remaining="$((duration_seconds - elapsed))"
  if (( remaining <= 0 )); then
    break
  fi
  if (( remaining < interval_seconds )); then
    sleep "$remaining"
    break
  fi
  sleep "$interval_seconds"
done

echo "Recursos guardados en $out_file"
