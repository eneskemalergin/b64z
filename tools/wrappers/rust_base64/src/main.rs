use std::{env, ffi::OsStr, fs, io, io::Write, process};

use base64::{
    encoded_len,
    engine::{general_purpose::STANDARD, simd::Simd},
    Engine,
};

fn fail(message: &str) -> ! {
    eprintln!("rust-base64-simd: {message}");
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
    let engine = Simd::standard(*STANDARD.config());
    let output_capacity = if decode {
        input.len()
    } else {
        encoded_len(input.len(), true).unwrap_or_else(|| fail("input is too large"))
    };
    let mut output = vec![0u8; output_capacity];

    let output_length = if decode {
        match engine.decode_slice(&input, &mut output) {
            Ok(length) => length,
            Err(error) => fail(&format!("invalid Base64 input: {error}")),
        }
    } else {
        match engine.encode_slice(&input, &mut output) {
            Ok(length) => length,
            Err(error) => fail(&format!("cannot encode input: {error}")),
        }
    };

    io::stdout()
        .write_all(&output[..output_length])
        .unwrap_or_else(|error| fail(&format!("cannot write stdout: {error}")));
}
