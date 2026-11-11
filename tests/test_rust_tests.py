from __future__ import annotations

import random
import time

import pytest

from tallyman.rust_tests import rust_test_lines


def _parse(snippet: str) -> tuple[str, frozenset[int]]:
    """Split a marked snippet into Rust text and the lines expected to drop.

    Each line starts with a marker and a space: ``T`` for a line of test code,
    ``.`` for a line that counts. A marker alone stands for a blank line.
    """
    lines = snippet.strip('\n').split('\n')
    expected = frozenset(i for i, line in enumerate(lines) if line[:1] == 'T')
    for line in lines:
        assert line[:1] in ('T', '.'), f'unmarked line: {line!r}'
    return '\n'.join(line[2:] for line in lines) + '\n', expected


def _check(snippet: str) -> None:
    text, expected = _parse(snippet)
    assert rust_test_lines(text) == expected


CASES: dict[str, str] = {
    # ---- Basics -------------------------------------------------------------------------------------
    'no cfg at all': """
. pub fn parse(input: &str) -> u32 {
.     input.len() as u32
. }
""",
    'test module at the bottom': """
. pub fn parse(input: &str) -> u32 {
.     input.len() as u32
. }
.
T #[cfg(test)]
T mod tests {
T     use super::*;
T
T     #[test]
T     fn parses() {
T         assert_eq!(parse("ab"), 2);
T     }
T }
""",
    'code after the test module counts': """
. fn a() {}
T #[cfg(test)]
T mod tests {
T     fn t() {}
T }
.
. fn after() {
.     a();
. }
""",
    'two test modules and a test fn between real fns': """
. fn a() {}
T #[cfg(test)]
T fn helper() -> u8 { 1 }
. fn b() {}
T #[cfg(test)]
T mod one { fn t() {} }
. fn c() {}
T #[cfg(test)]
T mod two {
T }
""",
    'mod tests; declaration': """
. mod real;
T #[cfg(test)]
T mod tests;
. pub use real::*;
""",
    'one-line declaration': """
. mod real;
T #[cfg(test)] mod tests;
. pub use real::*;
""",
    'use': """
T #[cfg(test)]
T use std::collections::HashMap;
. use std::fmt;
""",
    'use group': """
T #[cfg(test)]
T use std::{
T     collections::HashMap,
T     fmt::Debug,
T };
. use std::io;
""",
    'const with a struct literal': """
T #[cfg(test)]
T const X: S = S {
T     a: 1,
T };
. const Y: u8 = 2;
""",
    'static': """
T #[cfg(test)]
T static NAMES: &[&str] = &["a", "b"];
. static OTHER: u8 = 1;
""",
    'tuple struct': """
T #[cfg(test)]
T struct Wrapper(u8);
. struct Real(u8);
""",
    'struct, enum, impl, trait': """
T #[cfg(test)]
T struct Fake {
T     a: u8,
T }
T #[cfg(test)]
T enum E { A, B }
T #[cfg(test)]
T impl Fake {
T     fn new() -> Self { Fake { a: 0 } }
T }
T #[cfg(test)]
T trait Mock {
T     fn mock(&self);
T }
. struct Real;
""",
    'type alias with braces': """
T #[cfg(test)]
T type Arr = [u8; { 2 + 2 }];
. type Real = u8;
""",
    'macro_rules with braces and parens': """
T #[cfg(test)]
T macro_rules! check {
T     ($e:expr) => { assert!($e) };
T }
T #[cfg(test)]
T macro_rules! other (
T     () => {}
T );
. macro_rules! real { () => {} }
""",
    'macro invocation item': """
T #[cfg(test)]
T proptest! {
T     fn t(x in 0..10u8) {}
T }
T #[cfg(test)]
T thread_local!(static N: u8 = 1);
. lazy_static! { static ref R: u8 = 1; }
""",
    'test fn inside impl and trait': """
. impl Thing {
.     pub fn real(&self) {}
T     #[cfg(test)]
T     pub fn helper(&self) -> u8 {
T         1
T     }
.     pub fn also_real(&self) {}
. }
. trait Api {
T     #[cfg(test)]
T     fn fake();
.     fn real();
. }
""",
    'test module nested in a module': """
. mod outer {
.     pub fn f() {}
T     #[cfg(test)]
T     mod tests {
T         fn t() {}
T     }
. }
""",
    'visibility and modifiers': """
T #[cfg(test)]
T pub(crate) mod tests {
T     fn t() {}
T }
. pub(in crate::a) unsafe impl Send for X {
T     #[cfg(test)]
T     const fn helper() -> u8 { 1 }
. }
. unsafe extern "C" {
T     #[cfg(test)]
T     fn fake_c();
.     fn real_c();
. }
. extern "C" fn callback() {
.     #[cfg(test)]
.     let x = 1;
. }
""",
    'const trait and const impl are not const items': """
T #[cfg(test)]
T const trait Fake {
T     fn f();
T }
. fn real() {
.     work();
. }
. static X: u8 = 1;
T #[cfg(test)]
T const impl Foo for Bar {
T }
. pub fn more() -> u8 {
.     1
. }
. use a::b;
""",
    'const items with a name or underscore end at the semicolon': """
T #[cfg(test)]
T const _: () = {
T     assert!(true);
T };
T #[cfg(test)]
T const fn helper() -> u8 { 1 }
. const REAL: u8 = 1;
""",
    'more item kinds': """
T #[cfg(test)]
T union U { a: u8, b: u16 }
T #[cfg(test)]
T async fn a() {}
T #[cfg(test)]
T unsafe fn b() {}
T #[cfg(test)]
T unsafe auto trait Marker {}
T #[cfg(test)]
T static mut COUNTER: u32 = 0;
. impl<T> Default for X<T> {
T     #[cfg(test)]
T     default fn helper() {}
T     #[cfg(test)]
T     type Probe = u8;
.     fn real() {}
. }
. unsafe extern "C" {
T     #[cfg(test)]
T     safe fn fake_c();
T     #[cfg(test)]
T     unsafe static FAKE: u8;
.     fn real_c();
. }
""",
    'lexing traps in real code before a test item': """
. fn real() {
.     'outer: for _ in 0..1 { break 'outer; }
.     let a = b"\\"}";
.     let b = r"\\";
.     let c = '"';
.     let d = "{";
.     let e = '}';
. }
T #[cfg(test)]
T mod tests {
T     fn t() {}
T }
. fn after() {}
""",
    'extern crate': """
T #[cfg(test)]
T extern crate quickcheck;
. extern crate core;
""",
    # ---- Attributes ---------------------------------------------------------------------------------
    'spacing inside the attribute': """
T #[cfg( test )]
T fn a() {}
T # [ cfg ( test ) ]
T fn b() {}
""",
    'attribute over several lines with a comment': """
T #[cfg(
T     // only for tests
T     test
T )]
T fn a() {}
T #[cfg(/* c */ test)]
T fn b() {}
. fn real() {}
""",
    'all with test': """
T #[cfg(all(test, feature = "x"))]
T fn a() {}
T #[cfg(all(feature = "x", test))]
T fn b() {}
T #[cfg(all(test,))]
T fn c() {}
T #[cfg(all(unix, all(test)))]
T fn d() {}
. fn real() {}
""",
    'trailing comma in cfg': """
T #[cfg(test,)]
T fn a() {}
. fn real() {}
""",
    'any where every branch is test-only': """
T #[cfg(any(test))]
T fn a() {}
T #[cfg(any(all(test, unix), all(test, windows)))]
T fn b() {}
""",
    'not test-only': """
. #[cfg(any(test, feature = "mock"))]
. fn a() {}
. #[cfg(not(test))]
. fn b() {}
. #[cfg(testing)]
. fn c() {}
. #[cfg(feature = "test")]
. fn d() {}
. #[cfg_attr(test, derive(Debug))]
. struct S;
. #[test]
. fn e() {}
. #[cfg(all())]
. fn f() {}
. #[cfg(any())]
. fn g() {}
. #[cfg(all(not(unix)))]
. fn h() {}
""",
    'stacked attributes and doc comments drop with the item': """
. // A plain comment stays (it is a comment either way)
T /// Helpers for the tests below.
T #[allow(dead_code)]
T #[cfg(test)]
T #[allow(unused)]
T /// More docs.
T mod tests {
T     fn t() {}
T }
. fn real() {}
""",
    'block doc comment before the attribute': """
T /** Test helpers.
T  * Several lines.
T  */
T #[cfg(test)]
T fn helper() {}
""",
    # ---- Inner attributes ---------------------------------------------------------------------------
    'inner cfg(test) makes the whole file test-only': """
T //! Tests for the parser.
T
T #![cfg(test)]
T
T use super::*;
T
T #[test]
T fn t() {}
T
""",
    'inner cfg(test) after other inner attributes and a shebang': """
T #!/usr/bin/env run-cargo-script
T #![allow(dead_code)]
T #![cfg(test)]
T fn t() {}
""",
    'inner cfg(test) in a mod body': """
. fn real() {}
T mod tests {
T     #![cfg(test)]
T     fn t() {}
T }
. fn after() {}
""",
    'inner cfg(test) in impl and trait bodies': """
. fn real() {}
T impl X {
T     #![cfg(test)]
T     fn t() {}
T }
T trait Y {
T     #![cfg(test)]
T     fn t();
T }
. fn after() {}
""",
    'inner cfg(not(test))': """
. #![cfg(not(test))]
. fn real() {}
""",
    'inner attribute after an item is ignored': """
. fn real() {}
. #![cfg(test)]
. fn more() {}
""",
    # ---- Lexing traps -------------------------------------------------------------------------------
    'braces in strings': """
. fn real() -> &'static str {
.     "}}}"
. }
T #[cfg(test)]
T mod tests {
T     const A: &str = "{";
T     const B: &str = "\\"{";
T     const C: &str = "a
T }
T b";
T }
. fn after() -> &'static str { "{" }
""",
    'raw strings': """
T #[cfg(test)]
T mod tests {
T     const A: &str = r"{";
T     const B: &str = r#"}"#;
T     const C: &str = r##"a "# b } "##;
T     const D: &[u8] = br#"{"#;
T     const E: &CStr = c"{";
T     const F: &CStr = cr"}";
T     const G: &[u8] = b"}";
T }
. fn after() {}
""",
    'char literals': """
T #[cfg(test)]
T mod tests {
T     const A: char = '{';
T     const B: char = '}';
T     const C: char = '\\'';
T     const D: char = '\\\\';
T     const E: char = '\\u{7B}';
T     const F: u8 = b'{';
T     const G: char = 'é';
T     const H: char = '"';
T }
. fn after() {}
""",
    'lifetimes and labels': """
. fn f<'a>(x: &'a str) -> &'a str {
.     'outer: loop {
.         break 'outer;
.     }
.     x
. }
T #[cfg(test)]
T mod tests {
T     impl<'a> X<'a> {
T         fn g(&'a self) { 'l: loop { break 'l; } }
T     }
T }
. impl<'a> Real<'a> {}
""",
    'raw identifiers': """
T #[cfg(test)]
T mod tests {
T     fn r#type() -> u8 { r#match() }
T }
. fn r#loop() {}
""",
    'comments containing brackets and markers': """
T #[cfg(test)]
T mod tests {
T     /* } /* nested { */ still a comment } */
T     // }
T     const A: &str = "*/";
T     const B: &str = "//";
T }
. fn after() {}
""",
    'cfg(test) inside strings and comments drops nothing': """
. const S: &str = "#[cfg(test)] mod t {}";
. // #[cfg(test)]
. /// #[cfg(test)]
. /* #[cfg(test)] */
. fn real() {}
""",
    'statement position, fields, variants and macro bodies stay': """
. fn f() {
.     #[cfg(test)]
.     let x = 1;
.     #[cfg(test)]
.     {
.         helper();
.     }
. }
. struct S {
.     #[cfg(test)]
.     probe: u8,
. }
. enum E {
.     #[cfg(test)]
.     Fake,
.     Real,
. }
. macro_rules! m {
.     () => {
.         #[cfg(test)]
.         mod generated {}
.     };
. }
""",
    # ---- Lines --------------------------------------------------------------------------------------
    'code before the test item on the same line stays': """
. fn a() {} #[cfg(test)] fn b() {}
. fn c() {}
""",
    'closing line with a comment drops, with code stays': """
T #[cfg(test)]
T mod tests {
T } // end tests
T #[cfg(test)]
T mod more {
. } fn after() {}
""",
    'blank lines inside drop, blank lines after stay': """
. fn a() {}
.
T #[cfg(test)]
T mod tests {
T
T     fn t() {}
T
T }
.
.
. fn b() {}
""",
}


@pytest.mark.parametrize('snippet', CASES.values(), ids=CASES.keys())
def test_cases(snippet: str) -> None:
    _check(snippet)


class TestWhenInDoubtCount:
    @pytest.mark.parametrize(
        'text',
        [
            '#[cfg(test)]\nmod tests {\n    const S: &str = "unterminated;\n}\n',
            '#[cfg(test)]\nmod tests {\n    const S: &str = r#"unterminated";\n}\n',
            '#[cfg(test)]\nmod tests {\n    /* unterminated /* nested */\n}\n',
            "#[cfg(test)]\nmod tests {\n    const C: char = '\\u{7B;\n}\n",
            '#[cfg(test)]\nmod tests {\n    fn t() {}\n',  # missing the closing brace
            '#[cfg(test)]\nmod tests\n',  # no body and no semicolon
            '#[cfg(test)]\nfn a() {}\n#[cfg(test)]\nmod b\n',  # an unfinished test item cancels the earlier ones too
            "#[cfg(test)]\nmod tests {\n    const B: u8 = b'ab;\n}\n",  # a byte literal is never a lifetime
            'fn a() {\n}\n}\n#[cfg(test)]\nmod tests {}\n',  # a stray closing brace before the module
            'fn a() {\n\n#[cfg(test)]\nmod tests {}\n',  # a stray opening brace before the module
            'fn a() { (] }\n#[cfg(test)]\nmod tests {}\n',  # mismatched brackets
        ],
    )
    def test_nothing_drops(self, text: str) -> None:
        assert rust_test_lines(text) == frozenset()


class TestLineIndexes:
    def test_no_final_newline(self) -> None:
        assert rust_test_lines('fn a() {}\n#[cfg(test)]\nmod t {}') == {1, 2}

    def test_whole_file_without_final_newline(self) -> None:
        assert rust_test_lines('#![cfg(test)]\nfn t() {}') == {0, 1}

    def test_whole_file_line_count_matches_counter(self) -> None:
        # count_lines() sees two lines here (the blank one and the last); no phantom line after the final newline
        assert rust_test_lines('#![cfg(test)]\n\n') == {0, 1}

    def test_byte_order_mark(self) -> None:
        assert rust_test_lines('\ufeff#![cfg(test)]\nfn t() {}\n') == {0, 1}

    def test_empty(self) -> None:
        assert rust_test_lines('') == frozenset()


_FRAGMENTS = [
    '{', '}', '(', ')', '[', ']', '"', "'", 'r#"', '"#', '/*', '*/', '//', '\n', ' ', ';', ',', '#[cfg(test)]',
    '#![cfg(test)]', 'mod t', 'fn f()', 'impl X', "'a", "'{'", 'b"', 'test', 'cfg', '\\', 'all(', '=',
]  # fmt: skip


def test_random_text_never_raises() -> None:
    rng = random.Random(8)
    for _ in range(500):
        text = ''.join(rng.choice(_FRAGMENTS) for _ in range(rng.randint(0, 60)))
        lines = rust_test_lines(text)
        line_count = len(text.split('\n')) - (1 if text.endswith('\n') or not text else 0)
        assert all(0 <= i < line_count for i in lines)


def test_large_file_is_fast() -> None:
    real = 'pub fn f(x: &str) -> Option<&str> {\n    if x.is_empty() { None } else { Some("{}") }\n}\n\n'
    tests = '#[cfg(test)]\nmod tests {\n    #[test]\n    fn t() {\n        assert_eq!(f("a"), Some("{}"));\n    }\n}\n'
    text = (real * 20 + tests) * 600  # about 1.1 MB
    start = time.perf_counter()
    lines = rust_test_lines(text)
    elapsed = time.perf_counter() - start
    assert len(lines) == 7 * 600
    assert elapsed < 2.0, f'{elapsed:.2f}s for {len(text):,} characters'
