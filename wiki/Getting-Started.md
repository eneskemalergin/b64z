# Getting started

Build `custom-base64` from the repository root with Zig 0.16.0.

The codec and command need no third-party runtime library. The commands below use a POSIX shell and describe the tested Linux x86-64 build.

## Choose an archive

When using a packaged version, choose the archive for your use:

- `b64z-VERSION-source.tar.gz`: Zig source for the [library API](Library-Guide#add-as-a-dependency).
- `b64z-VERSION-linux-x86-scalar.tar.gz`: command-line executable for Linux x86-64.
- `b64z-VERSION-linux-x86-avx2.tar.gz`: command-line executable for Linux x86-64 with a Haswell-compatible CPU and AVX2. It does not fall back to scalar on older CPUs.

`VERSION` is the package version. Each CLI archive contains `custom-base64` and the license notices; running that executable does not require Zig. To build from a checkout, use the commands below.

## Build for this machine

```sh
zig version
zig build -Dcpu=native -Doptimize=ReleaseFast -Dstrip=true
./zig-out/bin/custom-base64 --version
```

Check that `zig version` prints `0.16.0`. The program's version line names its version, selected backend, optimization mode, and target architecture. On an AVX2-capable x86-64 host, this build reports `backend=avx2` and `optimize=ReleaseFast`.

`-Dcpu=native` permits instructions available on the build machine. Do not assume that binary will run on an older CPU. To select B64Z's scalar backend on x86-64, build with:

```sh
zig build -Dcpu=x86_64 -Doptimize=ReleaseFast -Dstrip=true
./zig-out/bin/custom-base64 --version
```

That command replaces the installed executable and reports `backend=scalar`. It changes the CPU requirement, not the operating system or executable format. The library's [backend selection](API#backend-selection) happens at compile time.

## Convert a file

Use new filenames for this example:

```sh
printf 'hello' > hello.bin
./zig-out/bin/custom-base64 --mode encode-streaming hello.bin > hello.b64
./zig-out/bin/custom-base64 --mode decode-streaming hello.b64 > hello.decoded
cmp hello.bin hello.decoded
```

`hello.b64` contains exactly `aGVsbG8=`, without a newline. `cmp` exits successfully without printing anything when the decoded bytes match. Do not redirect output to the input path: the shell truncates that file before the converter opens it.

Read [Command line](Command-Line) for the four modes, `--chunk`, and partial-output behavior. Read [Library guide](Library-Guide) to call the codec from Zig.

For source changes, see [Development](Development#run-the-tests) for the test commands.
