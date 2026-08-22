# Code Standards Corpus — Go

This is the canonical coding-standards corpus for the **Go Code Quality & Idioms**
deliberator (council slot `voice_identity`, running the Go preset). It is the Go
counterpart of `code_standards.example.md`: a numbered rule set the deliberator
cites at the line level.

Every violation the deliberator reports must name a **rule ID (GQ-1..GQ-30)**, a
**line number**, the **offending snippet**, and a **concrete fix**. "Make it more
idiomatic" is not a finding.

Target stack: Go 1.21+, standard-library-first, `gofmt`/`go vet` clean, tested
with the `testing` package. The rules distill Effective Go, the Go Code Review
Comments wiki, the Google Go Style Guide, and the Uber Go Style Guide into
line-level checks. Swap in your team's overrides where they differ.

---

## 1. Formatting & Naming (GQ-1..GQ-5)

- **GQ-1** — Code is `gofmt`/`goimports` clean. Any manually-aligned or
  unformatted block is a finding; formatting is not a matter of taste in Go.
- **GQ-2** — `MixedCaps` / `mixedCaps`, never `snake_case` or `SCREAMING_SNAKE`.
  Exported identifiers start upper-case; unexported start lower-case. Constants
  follow the same casing (`MaxRetries`, not `MAX_RETRIES`).
- **GQ-3** — Short, contextual names: receivers are 1–2 chars (`c`, `srv`),
  loop indices are `i`/`k`/`v`. Longer names only where scope or ambiguity demands
  it. A name's length should scale with its scope.
- **GQ-4** — No stutter. A name is read with its package: `chart.New`, not
  `chart.NewChart`; `http.Server`, not `http.HTTPServer`. Don't repeat the package,
  receiver, or parameter type in a function name (`Parse`, not `ParseYAMLConfig`
  in package `yamlconfig`).
- **GQ-5** — Interface names for a single method end in `-er` (`Reader`,
  `Notifier`). Getters drop the `Get` prefix (`Name()`, not `GetName()`).

## 2. Errors (GQ-6..GQ-11)

- **GQ-6** — Never discard an error with `_` unless it is genuinely impossible to
  act on, and then say why in a comment. An unchecked error from a call that can
  fail is a **would_block**.
- **GQ-7** — Wrap with context using `fmt.Errorf("doing X: %w", err)` so the chain
  is inspectable via `errors.Is` / `errors.As`. Bare `return err` that loses the
  operation context up a deep stack is a finding (GQ-7).
- **GQ-8** — Compare errors with `errors.Is` and extract with `errors.As`; do not
  string-match on `err.Error()` (GQ-8 banned pattern).
- **GQ-9** — Error strings are lower-case, no trailing punctuation
  (`"parse config: %w"`, not `"Parse config failed."`), because they are usually
  wrapped.
- **GQ-10** — Sentinel errors are `var ErrX = errors.New(...)`; richer errors are
  custom types implementing `error`. Return the narrowest useful error; don't
  `panic` for ordinary failure paths (GQ-10). `panic` is for programmer bugs and
  truly unrecoverable state only.
- **GQ-11** — Handle an error once. Don't both log it and return it — that
  double-reports up the stack. Log at the boundary that decides, return everywhere
  else.

## 3. Interfaces & API shape (GQ-12..GQ-15)

- **GQ-12** — Accept interfaces, return concrete types. Functions take the
  narrowest interface they use (`io.Reader`, not `*os.File`) and return structs the
  caller can use directly.
- **GQ-13** — Define interfaces in the **consumer** package, not the producer.
  Keep them small; a one-method interface is a feature, a five-method one is a smell
  (GQ-12/GQ-13). Do not add a method to an interface "for later" (see non-goals).
- **GQ-14** — Don't take a `*T` when a `T` value is enough, and don't return a
  pointer to a small struct out of habit. Be deliberate about pointer vs value
  receivers and keep them consistent across a type's method set (GQ-14).
- **GQ-15** — Exported symbols carry a doc comment that begins with the symbol's
  name and is a full sentence (`// Encode writes ...`). Undocumented exported API is
  a finding (GQ-15).

## 4. Concurrency (GQ-16..GQ-21)

- **GQ-16** — Every goroutine has a known exit. A `go f()` with no way to signal
  completion or cancellation is a **goroutine-leak would_block** (GQ-16). Prefer
  `context.Context` cancellation or a closed channel to stop workers.
- **GQ-17** — `context.Context` is the first parameter (`ctx context.Context`), is
  passed explicitly down the call chain, and is never stored in a struct field
  (GQ-17). Never pass a `nil` Context; use `context.Background()`/`TODO()`.
- **GQ-18** — The zero value of `sync.Mutex`/`sync.RWMutex` is ready to use — use
  `var mu sync.Mutex`, not `new(sync.Mutex)`. Do **not** embed the mutex in a
  struct; use a named field (`mu sync.Mutex`) so lock methods don't leak into the
  public API (GQ-18). Always `defer mu.Unlock()` right after locking.
- **GQ-19** — Don't copy a value whose methods take a pointer receiver (mutexes,
  `sync.WaitGroup`, `strings.Builder`, `bytes.Buffer`); `go vet` flags this. Copying
  a lock is a would_block (GQ-19).
- **GQ-20** — Close a channel from the sender side, exactly once; receivers never
  close. Unbounded/`fire-and-forget` fan-out with no concurrency limit (worker pool
  / semaphore) is a finding (GQ-20).
- **GQ-21** — Guard shared state with a mutex or confine it to one goroutine and
  communicate over channels. Assume the race detector will run: a data race is a
  hard block (GQ-21). No goroutines started in `init()`.

## 5. Data types, slices & maps (GQ-22..GQ-25)

- **GQ-22** — Declare an empty slice as `var t []T` (nil slice), not `t := []T{}`,
  unless a non-nil zero-length slice is specifically required (e.g. JSON `[]` vs
  `null`). Don't distinguish nil from empty in interfaces (GQ-22).
- **GQ-23** — Beware slice aliasing: a sub-slice shares the backing array; `append`
  can mutate the parent or retain a large array. Pre-size with `make([]T, 0, n)` when
  the length is known; copy out when you must detach (GQ-23).
- **GQ-24** — Map iteration order is random — never depend on it; sort keys when
  order matters. Reads of a missing key return the zero value, so use the
  `v, ok := m[k]` form when zero is a valid value (GQ-24).
- **GQ-25** — Don't take the address of a loop variable captured by a closure or
  goroutine without rebinding (`v := v`) on pre-1.22 code paths; and don't retain
  `&loopVar` past the iteration. Range-copy semantics for large structs are a
  performance finding (GQ-25).

## 6. Idioms, defer & stdlib (GQ-26..GQ-27)

- **GQ-26** — `defer` for cleanup (`defer f.Close()`) placed immediately after
  acquisition; but do not `defer` inside a hot loop (deferred calls accumulate until
  return) — close explicitly per iteration (GQ-26). Check the error from a deferred
  `Close()` on writers.
- **GQ-27** — Reach for the standard library before a dependency: `strings.Builder`
  for concatenation in loops, `strconv` over `fmt` for number conversion,
  `crypto/rand` (never `math/rand`) for keys/tokens, `time.Duration` for durations.
  Hand-rolling what stdlib provides is a finding (GQ-27).

## 7. Tests — `testing` (GQ-28..GQ-30)

- **GQ-28** — Table-driven tests with named cases; run subtests via `t.Run(name, …)`.
  A new/changed behavior with no test is a finding (GQ-28).
- **GQ-29** — Mark helpers with `t.Helper()`; use `t.Cleanup` for teardown; run
  independent cases with `t.Parallel()` where safe. Assert specific values, not just
  "no error" (GQ-29).
- **GQ-30** — Tests are deterministic and race-clean (`go test -race`); no reliance
  on wall-clock sleeps, real network, or map ordering. Inject clocks/IO via
  interfaces (GQ-30).

---

## Banned patterns (fast-fire — each is at least a would_block in a load-bearing line)

1. Ignored error via `_` (or no assignment) on a fallible call (GQ-6).
2. `go f()` with no cancellation / completion path — goroutine leak (GQ-16).
3. Copying a `sync.Mutex` / `WaitGroup` / value with a pointer-receiver method set (GQ-19).
4. String-matching on `err.Error()` instead of `errors.Is`/`As` (GQ-8).
5. `context.Context` stored in a struct field, or a `nil` ctx passed (GQ-17).
6. `panic` on an ordinary, recoverable error path (GQ-10).
7. `math/rand` used for keys, tokens, or secrets (GQ-27).
8. Data race on shared state / goroutine started in `init()` (GQ-21).
9. `defer` inside a hot loop holding a resource until function return (GQ-26).
10. Unformatted code (not `gofmt`-clean) or a `go vet` failure left in (GQ-1).

## Scoring anchor (1–5)

- **1** — Multiple banned patterns in load-bearing code (a goroutine leak, a data
  race, a copied lock); would not pass `go vet` / review.
- **2** — One banned pattern, or pervasive idiom drift (unwrapped errors, stutter,
  ignored errors).
- **3** — Idioms mostly held; a few nameable fixes, none blocking.
- **4** — Idiomatic Go; only nits.
- **5** — Clean, idiomatic, `gofmt`/`vet`/`-race` clean; nothing to change.
