# Agent rules for lc_discovery

Read [README.md](README.md) before changing this package.
Then [docs/schema.md](docs/schema.md). Calibration changes go only in
the matching file under [docs/providers/](docs/providers/).

Use the project skills:

- `.cursor/skills/lc-discovery/SKILL.md` when calling the package or
  changing `api.py`, tests, or public behaviour.
- `.cursor/skills/lc-discovery-provider/SKILL.md` when adding or editing
  a mission plugin.

Do not implement code until the developer asks. Fail fast: no silent
defaults, no invented filter identifiers or zero points.
Do not commit or push unless the developer asks.
