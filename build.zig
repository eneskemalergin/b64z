//! Builds the custom Base64 command and its self-contained test executable.

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
            .root_source_file = b.path("test/base64_test.zig"),
            .target = target,
            .optimize = optimize,
            .imports = &.{.{ .name = "base64", .module = base64_module }},
        }),
    });
    b.step("test", "Run Base64 tests").dependOn(&b.addRunArtifact(tests).step);
}
