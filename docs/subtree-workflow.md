# Subtree Workflow (Engine + Client)

This project keeps `engine/` and `client/` in one local repository, but syncs
them to separate remote repositories using `git subtree`.

Script:

```bash
bash ./sync-subtrees.sh --help
```

## 1) First-time manual bootstrap

Do this once per machine/repository.

1. Create split repositories from terminal (GitHub):

```bash
# One-time auth
gh auth login

# Create remote repositories
gh repo create <github_user>/PeerTube-browser-engine --public --confirm
gh repo create <github_user>/PeerTube-browser-client --public --confirm
```

2. Add remotes for split repositories:

```bash
git remote add engine-remote git@github.com:<github_user>/PeerTube-Browser-Engine.git
git remote add client-remote git@github.com:<github_user>/PeerTube-Browser-Client.git
```

3. Create initial `engine` branch manually:

```bash
git subtree split --prefix=engine -b split-engine
git push engine-remote split-engine:main
git branch -D split-engine
```

4. Create initial `client` branch manually:

```bash
git subtree split --prefix=client -b split-client
git push client-remote split-client:main
git branch -D split-client
```

After this, `engine-remote/main` and `client-remote/main` exist and can be
updated by `./sync-subtrees.sh`.

## 2) Regular sync flow

Sync both subtrees from current checked-out branch:

```bash
bash ./sync-subtrees.sh
```

Dry-run preview (prints split/push commands, no push):

```bash
bash ./sync-subtrees.sh --dry-run
```

## 3) Partial sync

Sync only Engine:

```bash
bash ./sync-subtrees.sh --engine-only
```

Sync only Client:

```bash
bash ./sync-subtrees.sh --client-only
```

## 4) Clean-worktree gate (optional)

If you want strict safety, require clean git status:

```bash
bash ./sync-subtrees.sh --require-clean
```

## 5) Custom remotes/branches

Use explicit remote/branch settings (for mirrors or non-`main` targets):

```bash
bash ./sync-subtrees.sh \
  --engine-remote my-engine \
  --engine-branch release \
  --client-remote my-client \
  --client-branch release
```

## 6) Hotfix backport flow (when needed)

Normal rule: commit in monorepo and sync out.

If a hotfix was committed directly in a split repo, pull it back:

```bash
git subtree pull --prefix=engine engine-remote main --squash
git subtree pull --prefix=client client-remote main --squash
```

Resolve conflicts if any, then continue normal monorepo-first flow.

## 7) Pull split branches

Recommended (apply remote split changes directly into monorepo folders):

```bash
git subtree pull --prefix=engine engine-remote main --squash
git subtree pull --prefix=client client-remote main --squash
```

If you need local technical split branches for inspection:

```bash
git fetch engine-remote main:split-engine
git fetch client-remote main:split-client

git log -1 --oneline split-engine
git log -1 --oneline split-client
```

Remove local technical branches when finished:

```bash
git branch -D split-engine split-client
```
