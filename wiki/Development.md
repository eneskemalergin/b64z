# Development

Build, check, and contribute changes to B64Z.

## Source files

- `src/base64.zig`: public API, scalar codec, and AVX2 kernels.
- `src/main.zig`: command-line parsing and file conversion.
- `tests/test_base64.zig` and `tests/test_cli.zig`: public API and command-line tests. Private AVX2 tests live beside the kernels in `src/base64.zig`.

## Run the tests

Use Zig 0.16.0. From the repository root on Linux x86-64, check formatting and test the scalar build:

```sh
zig fmt --check build.zig build.zig.zon src tests tools/wrappers/zig_std_base64.zig
zig build test -Dcpu=x86_64 --summary all
zig build test -Dcpu=x86_64 -Doptimize=ReleaseFast --summary all
```

On a Haswell-compatible CPU with AVX2, also run:

```sh
zig build test -Dcpu=haswell --summary all
zig build test -Dcpu=haswell -Doptimize=ReleaseFast --summary all
```

The test step runs the public codec tests, private AVX2 tests, and command-line tests. Scalar builds skip the two AVX2 tests. No benchmark data or peer executables are needed. [CI](https://github.com/eneskemalergin/b64z/blob/main/.github/workflows/ci.yml) checks both backends on Linux x86-64 and checks the distribution archives.

For a bug fix, include a small example that reproduces the problem and a test for the corrected behavior. For a speed or memory claim, include before-and-after measurements with the same inputs and settings; [Benchmarking](Benchmarking) describes the method.

## Edit the documentation

Edit pages in `wiki/` through the main repository. Changes merged into `main` are published to GitHub Wiki automatically; edits made directly in the wiki are overwritten by the next sync.

Keep pages directly inside `wiki/`. Use page names without `.md` for links between wiki pages, such as `API#backend-selection`. Update `_Sidebar.md` when adding or removing a page, then check the links:

```sh
bash .github/scripts/wiki_check.sh wiki
```
