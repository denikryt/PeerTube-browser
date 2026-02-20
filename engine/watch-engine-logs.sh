#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'EOF'
Usage:
  watch-engine-logs.sh -dev [--mode MODE] [--since SINCE]
  watch-engine-logs.sh -prod [--mode MODE] [--since SINCE]

Environment flags (required):
  -dev, --dev    Use peertube-engine-dev.service
  -prod, --prod  Use peertube-engine.service

Options:
  --mode MODE    Log view mode: focused | verbose (default: focused)
  --since SINCE  Optional journalctl --since value (example: "10 min ago", "today")

Examples:
  bash engine/watch-engine-logs.sh -dev
  bash engine/watch-engine-logs.sh -prod
  bash engine/watch-engine-logs.sh -prod --mode verbose
  bash engine/watch-engine-logs.sh --dev --since "30 min ago"

Notes:
  - Argument order is flexible.
  - Reads live logs from journalctl and filters JSON records by .modes.
  - WARNING/ERROR/CRITICAL are shown in all modes.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

MODE="focused"
UNIT=""
SINCE=""
SINCE_SET=0

KNOWN_MODES=("focused" "verbose")
is_known_mode() {
  local value="$1"
  for mode in "${KNOWN_MODES[@]}"; do
    if [[ "${value}" == "${mode}" ]]; then
      return 0
    fi
  done
  return 1
}

if [[ $# -eq 0 ]]; then
  echo "Missing environment flag: choose -dev or -prod. Use --help for usage." >&2
  exit 1
fi

while [[ $# -gt 0 ]]; do
  case "${1}" in
    -dev|--dev)
      if [[ -n "${UNIT}" ]]; then
        echo "Only one environment flag is allowed: -dev or -prod." >&2
        exit 1
      fi
      UNIT="peertube-engine-dev.service"
      shift
      ;;
    -prod|--prod)
      if [[ -n "${UNIT}" ]]; then
        echo "Only one environment flag is allowed: -dev or -prod." >&2
        exit 1
      fi
      UNIT="peertube-engine.service"
      shift
      ;;
    --mode)
      if [[ $# -lt 2 ]]; then
        echo "Option --mode requires a value. Use --help for usage." >&2
        exit 1
      fi
      MODE="${2}"
      shift 2
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

if [[ -z "${UNIT}" ]]; then
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

if [[ -z "${MODE}" ]]; then
  echo "MODE must be non-empty." >&2
  exit 1
fi

if ! is_known_mode "${MODE}"; then
  echo "Unsupported mode '${MODE}'. Supported: focused, verbose." >&2
  exit 1
fi

JQ_FILTER='
  fromjson?
  | select(. != null)
  | select(
      ((.modes // []) | index($mode)) != null
      or (.level == "WARNING" or .level == "ERROR" or .level == "CRITICAL")
    )
  | del(.modes)
  | if .event == "access" then
      .message |= sub("^\\[access\\]\\s*"; "")
    elif .event == "access.start" then
      .message |= sub("^\\[access\\.start\\]\\s*"; "")
    elif (.event | startswith("recommendations.")) then
      .message |= sub("^\\[recommendations\\]\\s*"; "")
    elif .event == "similarity.cache_hit" then
      .message |= sub("^\\[similar-cache\\]\\s*"; "")
    elif .event == "similarity.candidates" then
      .message |= sub("^\\[similar-server\\]\\s*"; "")
    else
      .
    end
'

if [[ -n "${SINCE}" ]]; then
  journalctl -u "${UNIT}" -f -o cat --since "${SINCE}" \
    | jq -R --arg mode "${MODE}" "${JQ_FILTER}"
else
  journalctl -u "${UNIT}" -f -o cat \
    | jq -R --arg mode "${MODE}" "${JQ_FILTER}"
fi
