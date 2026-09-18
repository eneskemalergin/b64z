use std::{env, ffi::OsStr, fs, io, io::Write, mem::MaybeUninit, process};

use base64_simd::{AsOut, STANDARD};

fn fail(message: &str) -> ! {
    eprintln!("rust-base64-simd-crate: {message}");
    process::exit(1);
}

fn input_path() -> (bool, std::ffi::OsString) {
    let mut args = env::args_os();
    let _program = args.next();
    let first = args.next().unwrap_or_else(|| process::exit(2));
    let second = args.next();
    if args.next().is_some() {
        process::exit(2);
    }

    match (first.as_os_str(), second) {
        (flag, Some(path)) if flag == OsStr::new("--decode") => (true, path),
        (flag, Some(path)) if flag == OsStr::new("--encode") => (false, path),
        (path, None) => (false, path.to_owned()),
        _ => process::exit(2),
    }
}

fn main() {
    let (decode, path) = input_path();
    let input = fs::read(path).unwrap_or_else(|error| fail(&format!("cannot read input: {error}")));
    let output_capacity = if decode {
        STANDARD.estimated_decoded_length(input.len())
    } else {
        STANDARD.encoded_length(input.len())
    };
    let mut output = vec![MaybeUninit::<u8>::uninit(); output_capacity];

    let output_bytes = if decode {
        match STANDARD.decode(&input, output.as_mut_slice().as_out()) {
            Ok(decoded) => decoded,
            Err(error) => fail(&format!("invalid Base64 input: {error}")),
        }
    } else {
        STANDARD.encode(&input, output.as_mut_slice().as_out())
    };

    io::stdout()
        .write_all(output_bytes)
        .unwrap_or_else(|error| fail(&format!("cannot write stdout: {error}")));
}
