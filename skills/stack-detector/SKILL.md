---
name: stack-detector
description: |
  Scans the project to detect tech stack — languages, frameworks, test runners, build tools, conventions —
  then matches detected signals against installed skills (plugin-bundled, user-level, marketplace) and writes
  per-agent skill recommendations to `.happysquad/stack-profile.md`. Triggers: /squad-detect, "detect the stack",
  "what tech is this project", "which skills should we use", "scan stack signals", "stack profile",
  "tech stack detection". Also auto-invoked by /happysquad-loop and /brainstorm on first run in a project
  (when no stack-profile.md exists).
---

# Stack Detector

Reads the project's manifest files, configs, and folder structure to produce a `stack-profile.md` that tells the squad how to specialize itself for *this* project. The profile drives skill loading per agent and surfaces gaps where no skill covers a detected pattern.

## Why this exists

The squad is generic by design — works with any stack. But "generic" leaves performance on the table: a `fastendpoints` skill knows the REPR pattern and validation conventions; a `react-vite-frontend` skill knows the TanStack Query / Zustand split. Without a stack profile, the architecter might propose a controller-based design in a FastEndpoints repo, or the implementer might reach for Redux when the codebase uses Zustand. The profile fixes that with a one-time scan.

## Where the profile lives

```
.happysquad/stack-profile.md          # human-readable, agent-readable
.happysquad/stack-profile.json        # structured signals, parseable
```

Both are written by every detection run. Agents read the markdown for context; orchestrators read the JSON to pick per-agent skill assignments.

## Refresh policy

- **First run** — when `/happysquad-loop` or `/brainstorm` starts and `stack-profile.md` does not exist, auto-run detection. Tell the user "Scanning project stack — one-time setup."
- **Stale check** — at each subsequent loop/brainstorm start, compare `stack-profile.json` generated_at against the last-modified time of any manifest file (package.json, *.csproj, go.mod, etc.). If a manifest changed after profile generation, prompt: "Project manifests changed since last scan. Refresh stack profile? — yes / no / never-ask-again".
- **Manual** — `/squad-detect` always runs a fresh scan, even if a profile exists. Archive the old profile to `.happysquad/stack-profile-<timestamp>.md` for diff.

## Detection signals

The scan looks at three layers in order: **manifests**, **configs**, **conventions**.

### Layer 1 — Manifest files (authoritative)

Manifest presence is high-signal. Read each that exists.

| File                                 | Tells you                                                |
|--------------------------------------|----------------------------------------------------------|
| `package.json`                       | Node / JS / TS — dependencies list the framework         |
| `pnpm-lock.yaml` / `yarn.lock` / `package-lock.json` | Package manager choice                   |
| `*.csproj`, `*.sln`, `Directory.Build.props` | .NET — read `<PackageReference>` for frameworks  |
| `pyproject.toml`, `requirements.txt`, `Pipfile`, `setup.py` | Python — dependencies                |
| `poetry.lock`, `Pipfile.lock`        | Python package manager                                   |
| `go.mod`                             | Go — required modules                                    |
| `Cargo.toml`                         | Rust — dependencies                                      |
| `Gemfile`, `Gemfile.lock`            | Ruby — dependencies                                      |
| `composer.json`                      | PHP                                                      |
| `pom.xml`, `build.gradle`, `build.gradle.kts` | Java / Kotlin                                   |
| `mix.exs`                            | Elixir                                                   |
| `Package.swift`                      | Swift                                                    |
| `pubspec.yaml`                       | Dart / Flutter                                           |

### Layer 2 — Configuration files (framework signals)

| File / pattern                       | Indicates                                                |
|--------------------------------------|----------------------------------------------------------|
| `tsconfig.json`                      | TypeScript                                               |
| `vite.config.*`                      | Vite build                                               |
| `next.config.*`                      | Next.js                                                  |
| `nuxt.config.*`                      | Nuxt                                                     |
| `astro.config.*`                     | Astro                                                    |
| `remix.config.*`                     | Remix                                                    |
| `webpack.config.*`                   | Webpack                                                  |
| `rollup.config.*`                    | Rollup                                                   |
| `tailwind.config.*`                  | Tailwind CSS                                             |
| `jest.config.*`                      | Jest test runner                                         |
| `vitest.config.*`                    | Vitest                                                   |
| `playwright.config.*`                | Playwright e2e                                           |
| `cypress.config.*`                   | Cypress e2e                                              |
| `pytest.ini`, `[tool.pytest]` in pyproject.toml | pytest                                       |
| `Dockerfile`                         | Containerized build                                      |
| `docker-compose.yml`                 | Multi-service local dev                                  |
| `.github/workflows/*.yml`            | GitHub Actions CI                                        |
| `.gitlab-ci.yml`                     | GitLab CI                                                |
| `Procfile`                           | Heroku-style deployment                                  |
| `terraform/`, `*.tf`                 | Terraform infra                                          |
| `kubernetes/`, `*.k8s.yaml`          | Kubernetes manifests                                     |
| `prisma/schema.prisma`               | Prisma ORM                                               |
| `alembic/`                           | SQLAlchemy + Alembic migrations                          |
| `migrations/`                        | Generic migrations directory — inspect to identify ORM   |

### Layer 3 — Framework-specific deep signals

These need code inspection beyond manifests.

| Signal                                          | Framework / pattern              |
|-------------------------------------------------|----------------------------------|
| `Program.cs` containing `AddFastEndpoints()`    | FastEndpoints (.NET REPR)        |
| `Program.cs` containing `MapControllers()`      | ASP.NET MVC                      |
| `*.cs` files extending `Endpoint<,>`            | FastEndpoints (confirms above)   |
| `manage.py` + `settings.py`                     | Django                           |
| `main.py` with `from fastapi import FastAPI`    | FastAPI                          |
| `app/controllers/` + Gemfile with `rails`       | Rails                            |
| `application.properties` / `application.yml` + Spring deps | Spring Boot               |
| `pages/` or `app/` with React components        | Next.js (confirms config)        |
| `app.module.ts` with `@NgModule`                | Angular                          |
| `pubspec.yaml` with `flutter:` section          | Flutter                          |
| `*.tsx` files importing from `@tanstack/react-query` | TanStack Query              |
| `*.ts` files importing from `zustand`           | Zustand state                    |
| `*.ts` files importing from `redux`             | Redux state                      |

### Layer 4 — Conventions (best-effort)

These are heuristic. Surface them in the profile, do not gate the loop on them.

- Test file naming: `*.test.ts`, `*.spec.ts`, `tests/`, `__tests__/`, `Tests/` directory
- Naming style: PascalCase / camelCase / snake_case (sample a few source files)
- Lint config presence: `.eslintrc`, `.prettierrc`, `.editorconfig`, `pyproject.toml [tool.ruff]`, `rustfmt.toml`
- Error handling style (sample): try/catch density, Result-type usage, error wrappers
- Logging library (grep for common imports: pino, winston, serilog, structlog, logrus, zap)

## Skill mapping

After detection, match signals to capability requirements. Output two columns: **what the project needs** and **which installed skills cover it**. Use the available-skills list that's surfaced to Claude at runtime — do not hardcode a registry here.

### Mapping rules

These are starting heuristics. The skill writer should extend them as new stack-specific skills become available.

| Detected signal                           | Capability needed                                | Installed skill candidates (check at run time) |
|-------------------------------------------|--------------------------------------------------|-----------------------------------------------|
| FastEndpoints + .NET                      | REPR endpoint creation, FluentValidation, processors | `fastendpoints`                          |
| ASP.NET MVC                               | Controller/Action design                         | (no specific skill — use engineering:system-design) |
| React + Vite + TS                         | SPA conventions, TanStack Query, Zustand, i18n   | `react-vite-frontend`, `wai-relay:react-vite-frontend` |
| Next.js                                   | App router, server components, RSC patterns      | (suggest installing a Next.js skill if available) |
| Any HTTP API                              | OpenAPI contract design                          | `wai-relay:api-contract-design`               |
| Has migrations directory (any ORM)        | Zero-downtime schema migration                   | `wai-relay:migration-planner`                 |
| Database schema present                   | Schema docs / data dictionary                    | `wai-relay:data-documentation`                |
| Has tests + CI                            | Testing strategy                                 | `engineering:testing-strategy`                |
| Any production code                       | Code review (security/perf/correctness)          | `engineering:code-review`, `security-review`  |
| New requirement (no specific stack)       | PRD writing                                      | `prd-writer`                                  |
| Project has user stories                  | Story quality scoring                            | `user-story-review`                           |

| React / Vue / Svelte frontend             | Component, hook, perf, a11y frontend review      | `react-reviewer`, `ui-ux-pro-max:ui-ux-pro-max` |
| Node / Next.js / Express / NestJS backend | API routes, middleware, auth, DB backend review  | `backend-reviewer`, `nextjs-backend`          |
| Auth / payment / secrets surface          | Dedicated security pass on the diff              | `security-review`                             |
| Has a test suite                          | Test-first authoring, red→green rigor            | `tdd`                                         |
| Frontend app (Vite / Next / CRA)          | Run + probe the live app (Playwright)            | `webapp-testing`                              |
| Detected gap (capability, no skill)       | Author a new project-specific skill to cover it  | `skill-creator`                               |

For any detected signal where no installed skill is found, mark it under `## Gaps` in the profile. When a gap recurs across runs, recommend running `skill-creator` to close it rather than leaving the agent on generic defaults.

## Per-agent assignment

After mapping, output the skills each agent should load for *this* project.

```markdown
## Recommended skills per agent

### architecter
- `fastendpoints` — REPR architecture, vertical slice patterns
- `wai-relay:api-contract-design` — OpenAPI spec before endpoints
- `wai-relay:react-vite-frontend` — frontend module conventions

### implementer
- `fastendpoints` — endpoint creation, FluentValidation
- `wai-relay:react-vite-frontend` — TanStack Query, Zustand patterns

### tester
- `engineering:testing-strategy` — test plan structure
- `tdd` — test-first authoring discipline; sharpens the red→green proof (failing tests that pin the AC, not after-snapshots)
- `webapp-testing` — Playwright to run + probe the live app for frontend slices (catches what unit tests miss)
- (frontend) Vitest patterns; (backend) xUnit fixtures — no specific skill

### reviewer
- `engineering:code-review` — six-axis review (REQ/SEC/PERF/STD/SIMPL/TEST)
- `react-reviewer` — frontend component/hook/perf/a11y axis (offloads the chief reviewer on FE slices)
- `backend-reviewer` / `nextjs-backend` — backend API/middleware/auth axis (offloads the chief reviewer on BE slices)
- `security-review` — dedicated security pass on auth/payment/secrets diffs
- (project-specific) FastEndpoints REPR adherence — covered by `fastendpoints`

### product
- (no stack-specific skills required)
```

Rules:
- Don't suggest a skill that isn't in the runtime `<available_skills>` list. If the user has the skill from one plugin (e.g. `react-vite-frontend` from `wai-relay`), list it. If they have both `react-vite-frontend` and `wai-relay:react-vite-frontend`, list both and note they may be equivalent.
- Don't pad. Better to recommend two strong skills than five weak matches.
- The stack-specialist reviewers (`react-reviewer`, `backend-reviewer`, `nextjs-backend`, `security-review`) are the chief reviewer's offload targets — recommending the one(s) matching the detected stack lets the orchestrator dispatch a frontend/backend specialist in parallel instead of the chief carrying every axis alone.
- If no skill covers a critical signal, the agent's section says `(no skill found — agent will use generic defaults)`.

## Output format

### stack-profile.md

```markdown
# Stack Profile

Generated: <YYYY-MM-DD HH:MM>
Detector version: 0.1
Project root: <path>

## Summary

<one paragraph: "This is a .NET 8 + FastEndpoints backend with a React 18 + Vite + TypeScript frontend. Tests via xUnit + Vitest. Deploys via Docker + GitHub Actions.">

## Languages
- C# (primary, backend)
- TypeScript (primary, frontend)

## Frameworks
- Backend: .NET 8, FastEndpoints 5.x, Entity Framework Core 8
- Frontend: React 18, Vite 5, TanStack Query 5, Zustand 4
- Testing: xUnit, Vitest, Playwright

## Conventions
- Backend follows REPR (Request-Endpoint-Response) — Endpoint<TRequest, TResponse> classes per vertical slice
- Frontend uses TanStack Query for server state, Zustand for client state
- Test naming: *.Tests.cs (backend), *.test.tsx (frontend)
- Migrations via EF Core CLI in `Backend/Migrations/`

## Recommended skills per agent

<table or bullet list as above>

## Gaps

- No skill found for Entity Framework Core migration patterns specifically. The general `wai-relay:migration-planner` covers the expand/contract pattern but doesn't know EF Core syntax. Consider creating one if migrations are frequent.

## Signal log

<list every detected signal with file path — used for debugging or to verify the scan was comprehensive>

- `package.json` → react 18.3.1, vite 5.4.1, @tanstack/react-query 5.x, zustand 4.x
- `Backend/Backend.csproj` → FastEndpoints 5.32.0, EFCore 8.0.10
- `vite.config.ts` → present
- `Backend/Program.cs` → AddFastEndpoints() at line 14 (confirms REPR)
- `.github/workflows/ci.yml` → present
- `Dockerfile` → present (multi-stage build)
- `migrations/` → 14 files, EF Core format
```

### stack-profile.json

```json
{
  "generated_at": "2026-05-20T11:45:00Z",
  "detector_version": "0.1",
  "project_root": "/path/to/repo",
  "languages": ["C#", "TypeScript"],
  "frameworks": {
    "backend": ["dotnet@8", "fastendpoints@5.32.0", "efcore@8.0.10"],
    "frontend": ["react@18.3.1", "vite@5.4.1", "tanstack-query@5", "zustand@4"]
  },
  "test_frameworks": ["xunit", "vitest", "playwright"],
  "build_tools": ["vite", "dotnet"],
  "package_managers": ["pnpm", "nuget"],
  "infrastructure": ["docker", "github-actions"],
  "conventions": {
    "backend_pattern": "REPR",
    "frontend_server_state": "tanstack-query",
    "frontend_client_state": "zustand",
    "test_naming_backend": "*.Tests.cs",
    "test_naming_frontend": "*.test.tsx"
  },
  "recommended_skills": {
    "architecter": ["fastendpoints", "wai-relay:api-contract-design", "wai-relay:react-vite-frontend"],
    "implementer": ["fastendpoints", "wai-relay:react-vite-frontend"],
    "tester": ["engineering:testing-strategy", "tdd", "webapp-testing"],
    "reviewer": ["engineering:code-review", "security-review", "react-reviewer", "backend-reviewer"],
    "product": []
  },
  "gaps": [
    "no-skill-for-efcore-migrations"
  ],
  "signals": [
    { "file": "package.json", "type": "manifest", "extracted": { "react": "18.3.1", "vite": "5.4.1" } },
    { "file": "Backend/Backend.csproj", "type": "manifest", "extracted": { "FastEndpoints": "5.32.0" } }
  ]
}
```

## Scan procedure

1. Verify the project root has at least one recognizable manifest. If none, ask the user: "I can't detect any framework manifests. Is this the project root? — yes (continue with limited scan) / no (provide correct path)".
2. Read manifests bottom-up: parse every present manifest, extract direct dependencies and versions.
3. Probe configs: glob for the config files in Layer 2. Just file presence is enough for most; for `Program.cs` / `main.py` / `manage.py` style files, read and grep for framework calls.
4. Detect conventions: sample a small set of source files (≤10 across folders) to infer naming style, test patterns, error handling. Do not exhaustively scan.
5. Map signals → capabilities → installed skills via the rules in Skill Mapping above.
6. Write `stack-profile.json` first (canonical), then `stack-profile.md` (human-readable view).
7. Report a 5-line summary to the user with links to both files.

## What this skill must NOT do

- Do not modify project source files. Read-only.
- Do not install or fetch skills. Just recommend.
- Do not assume the user wants every recommended skill — flag them, let the user (or the orchestrator) decide.
- Do not run the framework's tooling (no `npm install`, no `dotnet build`). Detection is file-system + minimal parsing only.
- Do not silently overwrite a recent profile. If `stack-profile.md` is less than 24 hours old and the user runs `/squad-detect`, ask before overwriting.

## Token discipline

The whole detection pass should be under 30 tool calls and finish in a single agent invocation. Use `Glob` patterns first to confirm file presence cheaply, then `Read` only the manifests that exist. Sample source files — do not read everything.

## Completion signal

When the profile is written, your final message must include:

```
STACK_PROFILE_READY: .happysquad/stack-profile.md gaps=<N>
```
