---
description: Scan the project to detect its tech stack and write .happysquad/stack-profile.md with per-agent skill recommendations. Auto-runs on first /happysquad-loop or /brainstorm; use this command to refresh manually.
---

Load the `stack-detector` skill at `${CLAUDE_PLUGIN_ROOT}/skills/stack-detector/SKILL.md` and run the full scan procedure.

Steps:

1. Determine the project root. Default is the current working directory. If the user passed a path in `$ARGUMENTS`, use that instead.
2. Check if `.happysquad/stack-profile.md` exists and was written less than 24 hours ago. If yes, ask: "Recent profile exists (generated <X> ago). Overwrite? — yes / no / diff (show what would change)". Default to overwrite if older than 24h or if no profile exists.
3. If an existing profile is being overwritten, archive it to `.happysquad/stack-profile-<timestamp>.md` first.
4. Execute the scan in four layers per the skill:
   - **Layer 1** — glob for and read manifest files (package.json, *.csproj, pyproject.toml, go.mod, Cargo.toml, Gemfile, composer.json, pom.xml, build.gradle, mix.exs, Package.swift, pubspec.yaml). Extract direct dependencies.
   - **Layer 2** — glob for config files (tsconfig.json, vite.config.*, next.config.*, jest.config.*, vitest.config.*, pytest.ini, Dockerfile, .github/workflows/, prisma/, alembic/, migrations/).
   - **Layer 3** — for any framework signal that needs code inspection (Program.cs for FastEndpoints, main.py for FastAPI, manage.py for Django, etc.), read just enough to confirm.
   - **Layer 4** — sample at most 10 source files to infer naming style, test patterns, logger choice.
5. Map detected signals to capability requirements per the skill's mapping table.
6. Look up installed skills via the runtime `<available_skills>` list. Match capabilities to skills. List both plugin-namespaced (e.g. `wai-relay:react-vite-frontend`) and unprefixed (e.g. `fastendpoints`) skills when both exist.
7. Write `.happysquad/stack-profile.json` (structured) then `.happysquad/stack-profile.md` (human-readable) per the skill's output format.
8. Report a 5-line summary:
   - Primary stack (e.g. ".NET 8 + FastEndpoints / React + Vite")
   - N skills recommended across the squad
   - K gaps (capabilities with no skill match)
   - Paths to both files
   - Suggested next command — usually `/happysquad-loop` or `/brainstorm`

Use Read/Glob/Grep only — this is a read-only operation. Never modify project source files.
