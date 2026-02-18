#!/usr/bin/env bash
set -euo pipefail

show_help() {
  cat <<'EOF'
Usage:
  watch-engine-logs.sh
  watch-engine-logs.sh MODE UNIT [SINCE]
  watch-engine-logs.sh --mode MODE --unit UNIT [--since SINCE]

Arguments:
  MODE   Log view mode: focused | verbose (default: focused)
  UNIT   systemd unit name (default: peertube-engine)
  SINCE  Optional journalctl --since value (example: "10 min ago", "today")

Examples:
  bash engine/watch-engine-logs.sh
  bash engine/watch-engine-logs.sh focused peertube-engine-dev.service
  bash engine/watch-engine-logs.sh focused peertube-engine "10 min ago"
  bash engine/watch-engine-logs.sh --mode focused --unit peertube-engine-dev.service --since "30 min ago"

Notes:
  - Argument order is strict. Mixed formats are rejected.
  - Reads live logs from journalctl and filters JSON records by .modes.
  - WARNING/ERROR/CRITICAL are shown in all modes.
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  show_help
  exit 0
fi

MODE="focused"
UNIT="peertube-engine"
SINCE=""

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
  MODE="focused"
  UNIT="peertube-engine"
  SINCE=""
elif [[ "$1" == "--"* ]]; then
  if [[ $# -lt 4 ]]; then
    echo "Invalid args. Required: --mode MODE --unit UNIT [--since SINCE]" >&2
    echo "Use --help for usage." >&2
    exit 1
  fi
  if [[ "$1" != "--mode" || "$3" != "--unit" ]]; then
    echo "Invalid flag order. Required: --mode MODE --unit UNIT [--since SINCE]" >&2
    echo "Use --help for usage." >&2
    exit 1
  fi
  MODE="$2"
  UNIT="$4"
  shift 4
  if [[ $# -eq 0 ]]; then
    SINCE=""
  elif [[ $# -eq 2 && "$1" == "--since" ]]; then
    SINCE="$2"
  else
    echo "Invalid trailing args. Allowed only: --since SINCE" >&2
    echo "Use --help for usage." >&2
    exit 1
  fi
else
  if [[ $# -ne 2 && $# -ne 3 ]]; then
    echo "Invalid positional args. Required: MODE UNIT [SINCE]" >&2
    echo "Use --help for usage." >&2
    exit 1
  fi
  MODE="$1"
  UNIT="$2"
  SINCE="${3:-}"
fi

if ! command -v journalctl >/dev/null 2>&1; then
  echo "journalctl is required." >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required." >&2
  exit 1
fi

if [[ -z "${MODE}" || -z "${UNIT}" ]]; then
  echo "MODE and UNIT must be non-empty." >&2
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
