# Identity policy

SyMoNeuRaL uses repo identity, not assistant-account identity.

## Canonical human

Garrett McDonald.

## Canonical Git author for this repo

gpmcdonald <garrettmcdonald87@gmail.com>

## Known account aliases

- garrettmcdonald87@gmail.com
- gmcdonald@symoneural.com
- symonsayadmin@symoneural.com
- garrett.mcdonald@symoneural.com

These are access surfaces, not separate project owners.

## Rule

Every sandbox must run:

```bash
./scripts/agent-bootstrap.sh
```

before editing files.

Commit rule

Use the repo-local Git identity unless a commit intentionally records an identity transition.

If an identity transition is intentional, state that in the commit body.

Worktree rule

Only one sandbox may commit to the main worktree at a time.

Other sandboxes must use branches or separate worktrees.
