#!/usr/bin/env bash
set -euo pipefail

# Stream client service logs from journalctl and pretty-print JSON records.
# Non-JSON lines are preserved as {"raw": "..."} so jq never fails on mixed output.

show_help() {
  cat <<'EOF'
Usage:
  watch-client-logs.sh -dev [--since SINCE]
  watch-client-logs.sh -prod [--since SINCE]

Environment flags (required):
  -dev, --dev    Use peertube-client-dev.service
  -prod, --prod  Use peertube-client.service

Options:
  --since SINCE  Optional journalctl --since value (example: "10 min ago", "today")

Examples:
  bash client/watch-client-logs.sh -dev
  bash client/watch-client-logs.sh -prod
  bash client/watch-client-logs.sh -prod --since "30 min ago"
  bash client/watch-client-logs.sh --dev --since "10 min ago"
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

MODE=""
UNIT=""
SINCE=""
SINCE_SET=0

if [[ $# -eq 0 ]]; then
  echo "Missing environment flag: choose -dev or -prod. Use --help for usage." >&2
  exit 1
fi

while [[ $# -gt 0 ]]; do
  case "${1}" in
    -dev|--dev)
      if [[ -n "${MODE}" ]]; then
        echo "Only one environment flag is allowed: -dev or -prod." >&2
        exit 1
      fi
      MODE="dev"
      UNIT="peertube-client-dev.service"
      shift
      ;;
    -prod|--prod)
      if [[ -n "${MODE}" ]]; then
        echo "Only one environment flag is allowed: -dev or -prod." >&2
        exit 1
      fi
      MODE="prod"
      UNIT="peertube-client.service"
      shift
      ;;
    --since)
      if [[ $# -lt 2 ]]; then
        echo "Option --since requires a value. Use --help for usage." >&2
        exit 1
      fi
      if [[ ${SINCE_SET} -eq 1 ]]; then
        echo "Option --since can be provided only once." >&2
        exit 1
      fi
      SINCE="${2}"
      SINCE_SET=1
      shift 2
      ;;
    *)
      echo "Invalid args. Use --help for usage." >&2
      exit 1
      ;;
  esac
done

if [[ -z "${MODE}" ]]; then
  echo "Missing environment flag: choose -dev or -prod. Use --help for usage." >&2
  exit 1
fi

if ! command -v journalctl >/dev/null 2>&1; then
  echo "journalctl is required." >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required." >&2
  exit 1
fi

if [[ -n "${SINCE}" ]]; then
  journalctl -u "${UNIT}" -f -o cat --since "${SINCE}" \
    | jq -R 'fromjson? // {"raw": .}'
else
  journalctl -u "${UNIT}" -f -o cat \
    | jq -R 'fromjson? // {"raw": .}'
fi
