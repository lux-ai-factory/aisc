# Migration guides

One file per released version hop: **`v<from>-to-v<to>.md`**. Each guide is written for two
readers:

- a **plugin author** (human or agent) who must update a plugin to keep working, and
- an **agent maintaining the platform** who needs the exact surface that changed.

The `from` version is always a **named release** (a `vX.Y.Z` tag — see `gh release list`).
The `to` version is the release the branch is heading for; while it is unreleased the guide
says so and points at the branch as the source of truth.

## Guides

| from | to | status |
|---|---|---|
| [v1.3.0](./v1.3.0-to-v1.4.0.md) | v1.4.0 (provisional) | upcoming — from `integration/int-01-frozen-unified-app` |

## Writing a new one

Start from the last released tag and diff every surface a plugin can see:

```bash
git ls-tree vX.Y.Z apps/backend apps/eval apps/webapp shared/plugin-interface shared/plugin-manager
git -C shared/plugin-interface diff <vX.Y.Z-pin> <new-pin>
git -C shared/plugin-manager   diff <vX.Y.Z-pin> <new-pin>
git -C apps/eval               diff <vX.Y.Z-pin> <new-pin>
```

Then separate **breaking** from **additive**, and for each breaking change give the plugin
author a concrete "do this instead". A change that only widens a signature (accepting a
`Path` as well as `bytes`, say) is additive — mark it as such so nobody rewrites working code.
