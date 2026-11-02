# Repository consolidation, 2026-11-02

Workspace development uses one checkout, on `main`:
`C:\Users\Jim.Lundin\Projects\workspace`. `/home/jim/workspace` is a symlink to
that checkout. The Downloads installation and distribution ZIP remain deployment
artifacts, with their existing Python/Qt runtime.

`main` was advanced from `d5f4aef` to the current product history at `6768f74`
before recording the consolidation. This preserves all 81 newer commits from
`feature/liquid-glass-native` without changing their source or replaying retired
prototypes. The repository now has only local `main` and remote `origin/main`;
the three Liquid Glass milestone tags remain.

## Recovery archive

Retired Git histories are stored in:
`C:\Users\Jim.Lundin\Projects\Archives\workspace-retired-20261102.zip`.
The archive contains complete Git bundles, original branch/worktree inventories,
exact source snapshots for the previously dirty checkouts and SHA-256 checksums.
Each bundle was restored into a disposable bare repository and checked with
`git fsck --full` before removing its checkout.

`workspace.bundle` contains all original local branches, tags, remote refs and
detached worktree heads. Twelve local branches were removed:

| Retired branch | Original tip | Disposition |
| --- | --- | --- |
| `cleanup/typing-suppressions` | `4da0028` | Already in product history |
| `feature/liquid-glass-native` | `6768f74` | Advanced onto `main` |
| `feature/shared-workspaces-20261025` | `ac9e45c` | Already in product history |
| `integration/qt-and-typing` | `1390e09` | Already in product history |
| `investigate/qt-stalls` | `7e24d3f` | Already in product history |
| `investigate/qt-stalls-before-latest-rebase` | `f91c82c` | Archived pre-rebase snapshot |
| `investigate/qt-stalls-test-speed-base` | `1a1cafe` | Already in product history |
| `prototype/liquid-glass-20261031` | `8e349d9` | Already in product history |
| `prototype/unified-work-conversation-20261026` | `52c447a` | Archived interaction prototype |
| `prototype/work-thread-representation-20261029` | `57e161b` | Archived representation prototype |
| `spike/island-glass` | `604435e` | Archived glass benchmark |
| `workspace/tool-presentation` | `fb2224b` | Archived earlier implementation snapshot |

The three remaining non-main GitHub branches were removed after pushing the
consolidated `main`: `feature/liquid-glass-native`,
`prototype/liquid-glass-20261031` and `spike/island-glass`. Remote refs for five
branches already deleted on GitHub were pruned.

`linux-reference.bundle` preserves the obsolete Linux checkout, its prototype
worktree and a separate commit of its previously uncommitted source. Additional
bundles preserve four abandoned Windows Temp review/check candidates; the two
candidates with uncommitted source received separate snapshot commits before
archiving. Generated caches, bytecode and virtual environments are disposable
and are excluded from these source histories.

Nine extra checkouts were removed:

- `C:\Users\Jim.Lundin\Projects\workspace-qt-stalls`
- `C:\Users\Jim.Lundin\Projects\Archives\workspace-work-thread-study`
- `%LOCALAPPDATA%\Temp\workspace-qt-stalls-latest-base`
- `/home/jim/workspace-linux-reference`
- `/home/jim/toolkit-prototypes/unified-work-conversation-20261026`
- `%LOCALAPPDATA%\Temp\toolkit-review-vkbz45k9`
- `%LOCALAPPDATA%\Temp\workspace-policy-candidate-tlnf_iu2`
- `%LOCALAPPDATA%\Temp\workspace-tool-review`
- `%LOCALAPPDATA%\Temp\workspace-voice-candidate-1793139030620991962`

The native development `.venv` was preserved; retired junctions pointing to it
were removed separately. Shared Workspace, Liquid Glass and other repositories
retain their own checkouts. Deployment stages and investigation evidence in Temp
retain their existing lifecycle.

To inspect retired work, extract the ZIP to a temporary folder and restore only
the desired branch outside the active checkout:

```powershell
git clone --single-branch --branch prototype/work-thread-representation-20261029 .\workspace.bundle .\workspace-retired-review
```

Remove that disposable review checkout after inspection. Continue product work
on `main` in the canonical Windows checkout.
