# SEC axis checklist

Scope: security only. Every finding needs `file:line` and a concrete mechanism; no "consider hardening".

1. **Authentication** — credential handling, session lifetime, timing-safe token compare, password hashing (salted, modern), MFA flow integrity.
2. **Authorization** — permission check at every entry point, IDOR, tenant isolation, privilege escalation paths.
3. **Input validation** — every external input validated for type/range/length/format; allowlist over denylist; schema validation on bodies.
4. **Injection** — SQL/NoSQL/command/LDAP/XSS/XXE/SSRF; parameterised queries; output encoding at the right layer.
5. **Secrets** — none hardcoded, none in logs or client-facing errors; sourced from env/KMS.
6. **Sensitive logging** — PII, tokens, full request bodies.
7. **Dependencies** — new deps checked for known CVEs; versions pinned.
8. **Transport** — HTTPS enforced, cert validation not disabled, cookies Secure/HttpOnly/SameSite.
9. **Headers** — CORS not permissive on credentialed endpoints; CSP/HSTS/X-Content-Type-Options where HTML is rendered.
10. **Crypto** — modern algorithms only, no key/IV reuse, CSPRNG.

Severity: `blocker` = exploitable now or violates a recorded wiki lesson; `major` = defence-in-depth gap; `minor` = hardening idea.

Read `knowledge/wiki/lessons/` first if it exists: a diff that repeats a recorded lesson is a blocker regardless.
