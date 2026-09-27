//! Exports the Base64 module and builds the CLI, its tests, and the Zig source package.

const std = @import("std");

const PACKAGE = @import("build.zig.zon");

pub fn build(b: *std.Build) void {
    const target = b.standardTargetOptions(.{});
    const optimize = b.standardOptimizeOption(.{});
    const strip = b.option(bool, "strip", "Strip the installed executable");
    const base64_module = b.addModule("base64", .{
        .root_source_file = b.path("src/base64.zig"),
        .target = target,
        .optimize = optimize,
    });

    const cli_build_options = b.addOptions();
    cli_build_options.addOption([]const u8, "version", PACKAGE.version);
    const exe = b.addExecutable(.{
        .name = "custom-base64",
        .root_module = b.createModule(.{
            .root_source_file = b.path("src/main.zig"),
            .target = target,
            .optimize = optimize,
            .strip = strip,
            .imports = &.{
                .{ .name = "base64", .module = base64_module },
                .{ .name = "build_options", .module = cli_build_options.createModule() },
            },
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

    const source_name = b.fmt("b64z-{s}-source", .{PACKAGE.version});
    const source_files = b.addWriteFiles();
    inline for (PACKAGE.paths) |path| {
        _ = source_files.addCopyFile(b.path(path), b.fmt("{s}/{s}", .{ source_name, path }));
    }
    const archive = b.addSystemCommand(&.{ "tar", "-czf" });
    const archive_name = b.fmt("{s}.tar.gz", .{source_name});
    const archive_file = archive.addOutputFileArg(archive_name);
    archive.addArg("-C");
    archive.addDirectoryArg(source_files.getDirectory());
    archive.addArg(source_name);
    const install_archive = b.addInstallFileWithDir(archive_file, .prefix, archive_name);
    b.step("source", "Package Zig source and licenses").dependOn(&install_archive.step);
}
