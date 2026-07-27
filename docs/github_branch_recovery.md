# GitHub Branch Recovery Note

As confirmed on 27 July 2026, the remote repository contained:

- `main` at `83e5bd4`;
- `objective2-locked-reporting`;
- `v2-residual-gated`;
- `v3-node`;
- `v4-grande`.

Recent Objective 2, Objective 3, and CERT r6.2 work existed on local branches and worktrees but had not been pushed.

Do not use `git push --all`. Review and push selected branches individually after checking for datasets, answer files, credentials, checkpoints, prediction arrays, and large blobs.

## High-risk lineage

The following branches require separate review before any push:

- `objective2-r52-odst-8tree-ablation`;
- `objective2-r52-component-latency-audit`.

The eight-tree history includes force-tracked checkpoints and prediction artefacts. A descendant branch can transmit those blobs to GitHub even when its latest commit contains only an audit report.
