# Phase 1 - The Rust Test-Code Scanner

Covers decisions 2, 3, 4, 8 and 9 from `00-plan-introduction.plan.md`. Nothing calls the scanner yet; phase 2 wires it into counting.

## Goal

A new module, `src/tallyman/rust_tests.py`, with one public function:

```python
def rust_test_lines(text: str) -> frozenset[int]:
    """0-based indexes of the lines in *text* that belong to test-only Rust code."""
```

*text* is already decoded and newline-normalised (only `\n` separates lines), exactly as `count_lines()` splits it, so the indexes line up with `count_lines()`'s `lines` list. An empty result means "count everything". The function never raises on any input.

(The name was `test_code_lines()` in the first draft. pytest collects any function named `test*` in a test module, imported ones included, so the tests would have tried to run it.)

## Fast path

Most `.rs` files have no test code. Before scanning, check that the text contains both `cfg` and `test` (two substring searches). If not, return the empty set. This keeps the cost of the option close to zero on files without tests. (A regex for `#[cfg(` would miss an attribute with a comment between its tokens; substrings can't miss.) The full scan still has to handle a match that turns out to sit in a string or comment.

## Scanner design

Scan the text once, left to right. Prefer a tokenising regex (`re.finditer` over the characters that matter) to a per-character Python loop; a 1 MB file must not take noticeably longer than `count_lines()` already does. Speed matters less than correctness, but measure it on a large real file before finishing.

### Lexing: what is *not* a bracket

The scanner tracks `(`, `[` and `{` depth. These never count as brackets:

| Construct | Notes |
|---|---|
| `// ...` to end of line | includes `///` and `//!` doc comments |
| `/* ... */` | **nests**: `/* a /* b */ still comment */`; includes `/** */` and `/*! */` |
| `"..."` | backslash escapes, may span lines |
| `r"..."`, `r#"..."#`, `r##"..."##` | no escapes; ends at `"` followed by the same number of `#` |
| `b"..."`, `br#"..."#`, `c"..."`, `cr#"..."#` | byte and C strings, same rules as above |
| `'x'`, `'\''`, `'\n'`, `'\u{7B}'`, `b'{'` | char literals |
| `'a`, `'static`, `'outer: loop {` | lifetimes and labels: **not** char literals |
| `r#type`, `r#match` | raw identifiers: `r#` followed by an identifier character, not `"` or `#` |

Telling a char literal from a lifetime: after `'`, if the next character is `\`, it is a char literal (read the escape, including `\u{...}`, then the closing `'`). Otherwise, if the character after the next one is `'`, it is a char literal. Otherwise it is a lifetime or label. Python's `str` indexes code points, so a multi-byte char like `'é'` works with this rule.

A shebang (`#!` on line 1 not followed by optional whitespace and `[`) is a line comment.

### Item positions: where an attribute can drop code

Only attributes in **item position** drop code. The scanner keeps a stack of open `{` brackets, each marked as an *item container* or not:

- The file's top level is an item container.
- A `{` that opens the body of a `mod`, `impl`, `trait` (including `unsafe trait`, `auto trait`) or `extern` block (`extern "C" { ... }`, not `extern "C" fn`) is an item container.
- Every other `{` (fn bodies, struct and enum bodies, macro bodies, `use` groups, struct literals, closures) is not. Attributes inside it are ignored and only its brackets are tracked.

To know what a `{` opens, record the item's **kind** when an item starts in a container: the first keyword after the modifiers `pub`, `pub(...)`, `unsafe`, `default`, `async`, `const` (only when followed by `fn`/`unsafe`/`async`/`extern`), and `extern "ABI"` (only when followed by `fn`). So `pub(crate) unsafe impl<T> Send for X<T> {` is an `impl`, and `const fn f() {` is a `fn`.

This is why statements, fields, variants and match arms are out of scope (decision 3): they sit inside non-container brackets, and finding where a statement ends needs a real expression parser.

### Which attributes are test-only

At item position, an outer attribute is `#` `[` ... `]` (whitespace and comments allowed between the tokens; the body may span lines and contain strings). Read the body with the same bracket and string rules, then strip whitespace and comments and parse it as a cfg predicate:

- The attribute must be `cfg(<predicate>)`. `cfg_attr(...)`, `test`, `allow(...)` and every other attribute are not test-only.
- `<predicate>` is test-only if it is:
  - the bare identifier `test` (not `testing`, not `feature = "test"`);
  - `all(p1, p2, ...)` where **at least one** `pi` is test-only;
  - `any(p1, p2, ...)` where **every** `pi` is test-only (so `any(test, feature = "x")` is not);
  - never `not(...)`.
- Split arguments on commas at depth 0 of the predicate. A trailing comma is allowed (`all(test,)`). Anything unparseable is not test-only.

### Outer attributes: the item's extent

A test-only outer attribute drops the **whole item it is attached to**, from the item's first attribute or doc comment to the item's end:

- **Start.** The item starts at the first of the consecutive outer attributes and outer doc comments (`///`, `/** */`) before its first keyword. So in

  ```rust
  /// Helpers for the tests below.
  #[allow(dead_code)]
  #[cfg(test)]
  mod tests {
  ```

  all four lines drop. A plain `//` comment above them is not part of the item and stays (it is a comment either way).
- **End.** Scanning from the item's first keyword, with depth measured relative to the item:
  - Kinds `use`, `const`, `static`, `type`, `extern crate`: the first `;` at relative depth 0. (`use a::{b, c};` and `const X: S = S { a: 1 };` contain a depth-0 `{`.)
  - Every other kind (`mod`, `fn`, `impl`, `trait`, `struct`, `enum`, `union`, `macro_rules!`, macro invocations like `foo! { }`, and anything unrecognised): the first `;` at relative depth 0, or the `}` that closes the item's first depth-0 `{`, whichever comes first. So `mod tests;`, `struct S(u8);` and `fn f();` end at `;`, and `fn f() -> [u8; 4] { }` is not fooled by the `;` inside `[...]`.
  - A closing bracket that would take relative depth below 0 means the enclosing block ended first: the item is malformed (decision 9).

### Inner `#![cfg(test)]`

An inner attribute `#![...]` with a test-only predicate makes its **enclosing container** test-only:

- At the top of the file (after an optional BOM, shebang, comments, `//!` docs and other inner attributes): every line of the file.
- As the first thing in a `mod`, `impl`, `trait` or `extern` body: that whole item, from its outer attributes to its closing `}`. (rustc removes an `impl` or `trait` under an inner `#![cfg(test)]` too; checked in the phase 1 review.)

An inner attribute anywhere else is not valid Rust; ignore it.

### From character ranges to lines

Collect the dropped regions as character ranges. A line is test code when:

- it overlaps a dropped region, and
- none of its *code* lies outside the regions: every non-whitespace character outside a region is inside a comment.

So blank and comment lines inside a test module drop with it, the line `#[cfg(test)] mod tests;` drops, and `fn a() {} #[cfg(test)] fn b() {}` on one line stays (it has real code). A trailing `} // end tests` line drops, since only a comment follows the region. Blank lines after a test module are outside every region and stay.

Nested regions (a `#[cfg(test)] fn` inside a `#[cfg(test)] mod`) need no special handling: merge overlapping ranges.

### When in doubt, count (decision 9)

Return the empty set (count the whole file normally) when the scan:

- reaches the end of the text inside a string, char literal or block comment;
- finds brackets anywhere in the file that don't balance or don't pair up (`(]`), outside strings and comments;
- reaches the end of the text (or of the enclosing block) inside a test item with no `;` or body to end it. This cancels the whole file, not just that item.

Real Rust always balances: every source file, macro bodies included, is a sequence of balanced token trees. So the scanner pairs every bracket up front and bails out on the whole file if it can't, instead of guessing which brackets are wrong. (Rule of thumb: the scanner may miss test code; it must never drop real code.)

## Tests

New file `tests/test_rust_tests.py`. Most tests are one table (`pytest.mark.parametrize`) of Rust snippets with the expected dropped line numbers. Write the snippets with a marker so the table stays readable, e.g. each test line ends in `  // T` and the helper computes the expected set from the markers (stripping them before the call, or keeping them where a comment is harmless). Cover at least:

**Basics**
- No `cfg` at all: empty set (fast path).
- The canonical layout: code, blank, `#[cfg(test)]`, `mod tests { ... }` at the bottom.
- Code after the test module still counts.
- Two test modules in one file; a `#[cfg(test)] fn` between two real fns.
- `#[cfg(test)] mod tests;` drops one line.
- `#[cfg(test)]` on `use`, `use a::{b, c};`, `const X: S = S { a: 1 };`, `static`, `struct S(u8);`, `struct S { .. }`, `enum`, `impl`, `trait`, `macro_rules! m { }`, `macro_rules! m ( );`, `foo! { }`.
- `#[cfg(test)] fn helper()` inside an `impl` block and inside a `trait` block; the rest of the impl counts.
- A test module inside a `mod outer { ... }`; `outer` itself counts.
- `pub(crate) mod tests`, `unsafe impl`, `extern "C" { }` with a test-only item inside.

**Attributes**
- `#[cfg( test )]`, `# [cfg(test)]`, an attribute split over lines, a comment inside it.
- `cfg(all(test, feature = "x"))`, `cfg(all(feature = "x", test))`, `cfg(all(test,))`, `cfg(all(unix, all(test)))`: test-only.
- `cfg(any(test))`, `cfg(any(all(test, a), all(test, b)))`: test-only.
- `cfg(any(test, feature = "mock"))`, `cfg(not(test))`, `cfg(testing)`, `cfg(feature = "test")`, `cfg_attr(test, derive(Debug))`, `#[test]`: not test-only, nothing drops.
- Stacked attributes and doc comments before and after the `#[cfg(test)]` line drop with the item; a plain `//` comment above them stays.

**Inner attributes**
- `#![cfg(test)]` at the top of a file: every line drops, including leading `//!` docs.
- `#![cfg(test)]` after `#![allow(...)]` and a shebang: every line drops.
- `#![cfg(test)]` as the first thing inside `mod m { }`: the whole `mod` drops, code outside counts.
- `#![cfg(not(test))]`: nothing drops.

**Lexing traps** (each inside a test module and inside real code, checking the right lines drop)
- Braces in strings, escaped quotes (`"\"{"`), multi-line strings.
- Raw strings `r"{"`, `r#"}"#`, `r##"a "# b"##`, `br#"{"#`, `c"{"`, `cr"}"`.
- Chars `'{'`, `'}'`, `'\''`, `'\\'`, `'\u{7B}'`, `b'{'`, `'é'`.
- Lifetimes and labels next to braces: `fn f<'a>(x: &'a str) {`, `'outer: loop { break 'outer; }`, `impl<'a> X<'a> {`.
- Raw identifiers `r#type`, `r#match` not read as raw strings.
- Nested block comments containing braces, `*/` inside a string, `//` inside a string.
- `#[cfg(test)]` inside a string, a comment or a doc comment: nothing drops.
- `#[cfg(test)]` inside a fn body (statement position), on a struct field, on an enum variant, inside a `macro_rules!` body: nothing drops.

**Lines**
- `fn a() {} #[cfg(test)] fn b() {}` on one line: stays.
- `} // end tests` drops; `} fn after() {}` on the closing line stays.
- Blank lines inside the module drop; blank lines after it stay.

**When in doubt, count**
- Unterminated string, char or block comment anywhere: empty set.
- A test module missing its closing `}` at end of file: empty set.
- Unbalanced brackets in real code outside any test item (a stray `{` or `}` before the test module): no exception and no real code dropped. Dropping nothing is fine; a stray bracket can hide the container the test module sits in.

**Robustness**
- Property-style check: for a few hundred random strings built from Rust-ish fragments (`{`, `}`, `"`, `'`, `r#"`, `/*`, `#[cfg(test)]`, `mod t`, newlines), `rust_test_lines()` never raises and returns indexes within range.

## Review findings (phase 1, 2026-11-11)

The architect review built a reference with syn 2 (Rust's own parser crate, with span locations) that finds the same regions, and compared it with `rust_test_lines()`. On 41,390 files from the local cargo registry (18.8M lines) the two agreed exactly: 995,370 lines, no extra lines dropped, none missed. On 20,000 generated files they also agreed exactly, and a second fuzz set with items sharing lines produced no false drops. This is a scratchpad tool, not a test dependency, but it is the way to re-check the scanner after any change to its lexing or item rules.

Fixed from the review:
- `#[cfg(test)] const trait` / `const impl` (nightly syntax) were read as `const` items, which end only at `;`, so the real items after them were dropped. `const` is now a const item only when a name or `_` follows it; after a keyword it is a modifier. A wrong semicolon kind drops real code, while a wrong brace kind only misses test code, so that rule leans to brace kinds.
- `#[cfg(test,)]` (valid Rust) is test-only.

Known safe misses, left alone: const-generic braces before an item's body (`impl Foo<{ N }> {`) end the item early, and nesting deeper than about 500 levels gives up on the file. Speed: about 0.3 s per MB, roughly 4x `count_lines()` on files that contain both `cfg` and `test`; tens of milliseconds on a typical workspace. A single master regex could speed up `_tokenize()` if it ever matters.

## Done when

- `rust_test_lines()` passes the table above.
- On a real Rust file of about 1 MB (generate one by concatenating snippets if no real one is to hand), it runs in well under a second; note the time in the commit message.
- All checks in "Rules for every phase" are clean, and the architect review's valid findings are addressed.
- Commit: `Plan 013 phase 1: Rust test-code scanner`.
