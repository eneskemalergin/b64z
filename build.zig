//! Builds the custom Base64 command and its self-contained tests: the public codec behavior
//! suite, the codec's private SIMD kernel tests, and the command-line suite, which runs the
//! executable built here.

const std = @import("std");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const strip = b.option(bool, "strip", "Strip the installed executable");
    const base64_module = b.addModule("base64", .{
        .root_source_file = b.path("src/base64.zig"),
        .target = target,
        .optimize = optimize,
    });

    const exe = b.addExecutable(.{
        .name = "custom-base64",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .strip = strip,
            .imports = &.{.{ .name = "base64", .module = base64_module }},
        }),
    });
    b.installArtifact(exe);

    const tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("tests/test_base64.zig"),
            .target = target,
            .optimize = optimize,
            .imports = &.{.{ .name = "base64", .module = base64_module }},
        }),
    });
    const codec_tests = b.addTest(.{ .root_module = base64_module });

    const cli_options = b.addOptions();
    cli_options.addOptionPath("exe_path", exe.getEmittedBin());
    const cli_tests = b.addTest(.{
        .root_module = b.createModule(.{
            .root_source_file = b.path("tests/test_cli.zig"),
            .target = target,
            .optimize = optimize,
            .imports = &.{.{ .name = "build_options", .module = cli_options.createModule() }},
        }),
    });

    const test_step = b.step("test", "Run Base64 tests");
    test_step.dependOn(&b.addRunArtifact(tests).step);
    test_step.dependOn(&b.addRunArtifact(codec_tests).step);
    test_step.dependOn(&b.addRunArtifact(cli_tests).step);
}
