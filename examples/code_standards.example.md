# Code Standards Corpus — Python / Flask / pytest

This is the canonical coding-standards corpus for the **Code Quality & Conventions**
deliberator (council slot `voice_identity`). It plays the role the voice recipe
plays for prose: a numbered rule set the deliberator cites at the line level.

Every violation the deliberator reports must name a **rule ID (C1–C30)**, a
**line number**, the **offending snippet**, and a **concrete fix**. "Make it
cleaner" is not a finding.

Target stack: Python 3.11+, Flask, pytest. Standard-library-first.

---

## 1. Naming (C1–C5)

- **C1** — `snake_case` for functions, methods, variables, modules.
- **C2** — `PascalCase` for classes; `UPPER_SNAKE_CASE` for module-level constants.
- **C3** — Leading `_` marks non-public API (`_helper`, `_Cache`). Don't reach into another module's `_names`.
- **C4** — Names describe intent, not type: `contacts_by_group`, not `dict1` / `data` / `tmp`. No 1–2 char names except loop indices (`i`, `k`, `v`).
- **C5** — No magic numbers or magic strings in logic. Extract to a named constant or enum (`HTTP_CONFLICT = 409`, `Status.ACTIVE`).

## 2. Types & Signatures (C6–C8)

- **C6** — Public functions/methods carry type hints on all params and the return (`def get_contacts_by_group(group_id: int) -> list[Contact]:`).
- **C7** — Prefer precise types (`list[Contact]`, `dict[str, int]`, `Optional[X]` / `X | None`) over bare `list`/`dict`/`Any`. `Any` in a public signature is a finding unless justified in a comment.
- **C8** — No mutable default arguments (`def f(items: list = [])` → use `None` sentinel + `items = items or []`). This is a hard block (C8 is a correctness bug, not style).

## 3. Error Handling (C9–C14)

- **C9** — No bare `except:` and no `except Exception: pass`. Catch the narrowest exception you can name. Swallowing errors silently is a **would_block** violation.
- **C10** — Don't catch what you can't handle. Let it propagate to a boundary (Flask error handler, service caller) that can respond meaningfully.
- **C11** — Re-raise with context (`raise ServiceError("loading contacts failed") from exc`); never discard the original (`raise X from exc`, not a bare new raise that loses the traceback).
- **C12** — Raise domain-specific exceptions from the service layer (`ContactNotFound`), not raw `ValueError`/`KeyError`, so routes can map them to status codes.
- **C13** — Log at the point you handle, with context (ids, operation), using `logging` / `current_app.logger` — never `print()` (C13 banned pattern).
- **C14** — Validate inputs at the boundary and fail fast with a clear error, rather than letting a bad value corrupt state deep in the call stack.

## 4. Functions & Structure (C15–C18)

- **C15** — One responsibility per function. A function doing fetch + transform + render + persist should be split. Rough smell: >40 logical lines or >3 levels of nesting.
- **C16** — Guard-clause early returns over deep `if/else` pyramids.
- **C17** — Public functions and modules have docstrings: one-line summary, then Args/Returns/Raises when non-obvious. Private one-liners are fine.
- **C18** — No dead code, no commented-out blocks, no `TODO` without a tracking reference.

## 5. Imports & Idioms (C19–C22)

- **C19** — Imports grouped stdlib / third-party / local, no wildcard imports (`from x import *` is banned — C19).
- **C20** — f-strings for interpolation, not `%` or `.format()`. Exception: logging calls use `logger.info("x=%s", x)` lazy form, not f-strings.
- **C21** — Use `pathlib.Path` over `os.path` string-mangling for filesystem work; context managers (`with open(...)`) for all resources.
- **C22** — Comparisons to `None`/`True`/`False` use `is`/`is not`, never `== None` (C22 banned pattern).

## 6. Flask (C23–C26)

- **C23** — Thin routes: a view function validates the request, calls a **service**, and shapes the response. Business logic and DB access do **not** live in the view (C23 — "fat route" is a would_block).
- **C24** — Return correct status codes explicitly (`201` create, `204` no-content, `404` not-found, `409` conflict, `422` validation). Don't return `200` for everything.
- **C25** — App-factory + blueprints for structure; read config via `app.config` / env, never hardcode secrets, hosts, or absolute paths in code (C25 — hardcoded secret/path is a would_block).
- **C26** — Register error handlers that map domain exceptions → JSON responses; don't leak stack traces to clients.

## 7. Data / SQL (C27–C28)

- **C27** — Parameterized queries only. String-built SQL (f-string / `%` / concatenation into a query) is a **would_block, irreducible-candidate** injection risk (C27).
- **C28** — Keep persistence behind a repository/service boundary; routes and templates never touch the DB cursor directly.

## 8. Tests — pytest (C29–C30)

- **C29** — Tests named `test_<behavior>`, one behavior per test, Arrange–Act–Assert shape, specific asserts (`assert resp.status_code == 409`, not `assert resp`). Use fixtures + `@pytest.mark.parametrize`, not `unittest.setUp` scaffolding, for new tests.
- **C30** — External I/O (network, real DB, clock, filesystem) is mocked/faked; a design that changes behavior must point at the test that covers the new path. "Add a test" with no named file/case is an Evidence-adjacent gap the Code Quality deliberator also flags.

---

## Banned patterns (fast-fire — each is at least a would_block in a load-bearing line)

1. `except:` / `except Exception: pass` — silent swallow (C9).
2. `print()` for diagnostics in library/app code (C13).
3. Mutable default argument (C8).
4. `== None` / `!= None` (C22).
5. `from module import *` (C19).
6. f-string / concatenated SQL (C27).
7. Hardcoded secret, token, host, or absolute path (C25).
8. Business logic or raw DB access inside a Flask view (C23).
9. `Any` in a public signature with no justification (C7).
10. Catch-and-rethrow that drops the original traceback (C11).

## Scoring anchor (1–5)

- **1** — Multiple banned patterns in load-bearing code; would not pass review.
- **2** — One banned pattern, or pervasive convention drift.
- **3** — Conventions mostly held; a few nameable fixes, none blocking.
- **4** — Idiomatic; only nits.
- **5** — Clean, idiomatic Python/Flask/pytest; nothing to change.
