#!/usr/bin/env bash
set -euo pipefail

git config --local user.name "gpmcdonald"
git config --local user.email "garrettmcdonald87@gmail.com"

GIT_AUTHOR_NAME="gpmcdonald" \
GIT_AUTHOR_EMAIL="garrettmcdonald87@gmail.com" \
GIT_COMMITTER_NAME="gpmcdonald" \
GIT_COMMITTER_EMAIL="garrettmcdonald87@gmail.com" \
git commit "$@"
