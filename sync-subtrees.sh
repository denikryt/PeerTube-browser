#!/usr/bin/env bash
set -euo pipefail

# Sync engine/client prefixes to dedicated subtree remotes.
# The script assumes remotes and target branches are already bootstrapped.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${SCRIPT_DIR}"

ENGINE_PREFIX="engine"
CLIENT_PREFIX="client"

ENGINE_REMOTE="${ENGINE_REMOTE:-engine-remote}"
CLIENT_REMOTE="${CLIENT_REMOTE:-client-remote}"
ENGINE_BRANCH="${ENGINE_BRANCH:-main}"
CLIENT_BRANCH="${CLIENT_BRANCH:-main}"

ENGINE_ONLY=0
CLIENT_ONLY=0
DRY_RUN=0
REQUIRE_CLEAN=0

# Prints CLI help and bootstrap commands.
print_usage() {
  cat <<'EOF_USAGE'
Usage: ./sync-subtrees.sh [options]

Split current branch HEAD for engine/client prefixes and push to subtree remotes.

Bootstrap (required before first sync):
  1) Add remotes:
       git remote add engine-remote <engine_repo_url>
       git remote add client-remote <client_repo_url>
  2) Create initial target branches:
       git subtree split --prefix=engine -b split-engine
       git push engine-remote split-engine:main
       git branch -D split-engine

       git subtree split --prefix=client -b split-client
       git push client-remote split-client:main
       git branch -D split-client

Options:
  --engine-remote <name>   Engine remote name (default: engine-remote)
  --client-remote <name>   Client remote name (default: client-remote)
  --engine-branch <name>   Engine branch name (default: main)
  --client-branch <name>   Client branch name (default: main)

  --engine-only            Sync only engine subtree
  --client-only            Sync only client subtree
  --require-clean          Fail if worktree has uncommitted/untracked files
  --dry-run                Print split/push commands; do not push
  -h, --help               Show this help
EOF_USAGE
}

# Prints fatal error and exits non-zero.
fail() {
  echo "ERROR: $*" >&2
  exit 1
}

# Verifies required executable availability.
require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

# Quotes command arguments for readable logs/dry-run output.
quoted_cmd() {
  local out=""
  local arg
  for arg in "$@"; do
    out+="$(printf '%q' "${arg}") "
  done
  printf '%s' "${out% }"
}

# Prints bootstrap instructions for one subtree remote/branch.
bootstrap_hint() {
  local prefix="$1"
  local remote="$2"
  local branch="$3"
  cat >&2 <<EOF_HINT
Bootstrap commands for ${prefix}:
  git remote add ${remote} <${prefix}_repo_url>
  git subtree split --prefix=${prefix} -b split-${prefix}
  git push ${remote} split-${prefix}:${branch}
  git branch -D split-${prefix}
EOF_HINT
}

# Ensures script is executed against a valid git repository.
ensure_git_repo() {
  git -C "${PROJECT_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "Not a git repository: ${PROJECT_DIR}"
}

# Returns current branch name or empty value on detached HEAD.
current_branch() {
  git -C "${PROJECT_DIR}" symbolic-ref --quiet --short HEAD 2>/dev/null || true
}

# Fails on detached HEAD and logs current source branch.
ensure_branch_context() {
  local branch
  branch="$(current_branch)"
  [[ -n "${branch}" ]] || fail "Detached HEAD is not supported. Checkout a branch and retry."
  echo "[sync-subtrees] source branch=${branch}"
}

# Ensures subtree prefix directory exists in repository.
ensure_prefix_exists() {
  local prefix="$1"
  [[ -d "${PROJECT_DIR}/${prefix}" ]] || fail "Missing subtree prefix directory: ${prefix}"
}

# Ensures configured remote exists; prints bootstrap hint on failure.
ensure_remote_exists() {
  local remote="$1"
  local prefix="$2"
  local branch="$3"
  if ! git -C "${PROJECT_DIR}" remote get-url "${remote}" >/dev/null 2>&1; then
    echo "ERROR: Missing git remote '${remote}'." >&2
    bootstrap_hint "${prefix}" "${remote}" "${branch}"
    exit 1
  fi
}

# Ensures configured remote branch exists; prints bootstrap hint on failure.
ensure_remote_branch_exists() {
  local remote="$1"
  local branch="$2"
  local prefix="$3"
  if ! git -C "${PROJECT_DIR}" ls-remote --exit-code --heads "${remote}" "${branch}" >/dev/null 2>&1; then
    echo "ERROR: Missing remote branch '${remote}/${branch}'." >&2
    bootstrap_hint "${prefix}" "${remote}" "${branch}"
    exit 1
  fi
}

# Optionally enforces a clean worktree before sync.
ensure_clean_worktree_if_required() {
  if (( REQUIRE_CLEAN == 0 )); then
    return
  fi
  local dirty
  dirty="$(git -C "${PROJECT_DIR}" status --porcelain)"
  if [[ -n "${dirty}" ]]; then
    fail "Worktree is not clean; commit/stash changes or rerun without --require-clean."
  fi
}

# Splits one prefix from current HEAD and pushes split commit to target branch.
sync_one_subtree() {
  local prefix="$1"
  local remote="$2"
  local branch="$3"
  local split_cmd=(git -C "${PROJECT_DIR}" subtree split --prefix="${prefix}" HEAD)
  local split_commit
  local push_cmd

  if (( DRY_RUN == 1 )); then
    echo "[dry-run] $(quoted_cmd "${split_cmd[@]}")"
    split_commit="$("${split_cmd[@]}")"
    push_cmd="$(quoted_cmd git -C "${PROJECT_DIR}" push "${remote}" "${split_commit}:refs/heads/${branch}")"
    echo "[dry-run] ${push_cmd}"
    return 0
  fi

  split_commit="$("${split_cmd[@]}")"
  push_cmd="$(quoted_cmd git -C "${PROJECT_DIR}" push "${remote}" "${split_commit}:refs/heads/${branch}")"
  echo "[sync-subtrees] ${push_cmd}"
  git -C "${PROJECT_DIR}" push "${remote}" "${split_commit}:refs/heads/${branch}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --engine-remote)
      ENGINE_REMOTE="${2:-}"
      shift 2
      ;;
    --client-remote)
      CLIENT_REMOTE="${2:-}"
      shift 2
      ;;
    --engine-branch)
      ENGINE_BRANCH="${2:-}"
      shift 2
      ;;
    --client-branch)
      CLIENT_BRANCH="${2:-}"
      shift 2
      ;;
    --engine-only)
      ENGINE_ONLY=1
      shift
      ;;
    --client-only)
      CLIENT_ONLY=1
      shift
      ;;
    --require-clean)
      REQUIRE_CLEAN=1
      shift
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    -h|--help)
      print_usage
      exit 0
      ;;
    *)
      fail "Unknown option: $1"
      ;;
  esac
done

require_cmd git
ensure_git_repo
ensure_branch_context
ensure_clean_worktree_if_required

if (( ENGINE_ONLY == 1 && CLIENT_ONLY == 1 )); then
  fail "Use either --engine-only or --client-only, not both."
fi

sync_engine=1
sync_client=1
if (( ENGINE_ONLY == 1 )); then
  sync_client=0
fi
if (( CLIENT_ONLY == 1 )); then
  sync_engine=0
fi

if (( sync_engine == 1 )); then
  ensure_prefix_exists "${ENGINE_PREFIX}"
  ensure_remote_exists "${ENGINE_REMOTE}" "${ENGINE_PREFIX}" "${ENGINE_BRANCH}"
  ensure_remote_branch_exists "${ENGINE_REMOTE}" "${ENGINE_BRANCH}" "${ENGINE_PREFIX}"
  sync_one_subtree "${ENGINE_PREFIX}" "${ENGINE_REMOTE}" "${ENGINE_BRANCH}"
fi

if (( sync_client == 1 )); then
  ensure_prefix_exists "${CLIENT_PREFIX}"
  ensure_remote_exists "${CLIENT_REMOTE}" "${CLIENT_PREFIX}" "${CLIENT_BRANCH}"
  ensure_remote_branch_exists "${CLIENT_REMOTE}" "${CLIENT_BRANCH}" "${CLIENT_PREFIX}"
  sync_one_subtree "${CLIENT_PREFIX}" "${CLIENT_REMOTE}" "${CLIENT_BRANCH}"
fi

echo "[sync-subtrees] done"
