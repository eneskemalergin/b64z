#include "simdutf.h"

#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <limits>
#include <memory>
#include <stdexcept>
#include <string>
#include <sys/stat.h>
#include <unistd.h>
#include <utility>

namespace {

struct FileData {
  std::unique_ptr<char[]> bytes;
  size_t size;
};

FileData read_file(const char *path) {
  const int fd = open(path, O_RDONLY);
  if (fd < 0) {
    throw std::runtime_error("cannot open " + std::string(path) + ": " +
                             strerror(errno));
  }

  struct stat status;
  if (fstat(fd, &status) != 0) {
    const std::string message = "cannot stat " + std::string(path) + ": " +
                                strerror(errno);
    close(fd);
    throw std::runtime_error(message);
  }
  if (status.st_size < 0 ||
      static_cast<uintmax_t>(status.st_size) > std::numeric_limits<size_t>::max()) {
    close(fd);
    throw std::runtime_error("input is too large: " + std::string(path));
  }

  const size_t size = static_cast<size_t>(status.st_size);
  std::unique_ptr<char[]> data;
  try {
    data.reset(new char[size == 0 ? 1 : size]);
  } catch (...) {
    close(fd);
    throw;
  }
  size_t offset = 0;
  while (offset < size) {
    const size_t count = std::min(
        size - offset, static_cast<size_t>(std::numeric_limits<ssize_t>::max()));
    const ssize_t read_count = read(fd, data.get() + offset, count);
    if (read_count < 0) {
      if (errno == EINTR) {
        continue;
      }
      const std::string message = "cannot read " + std::string(path) + ": " +
                                  strerror(errno);
      close(fd);
      throw std::runtime_error(message);
    }
    if (read_count == 0) {
      close(fd);
      throw std::runtime_error("input changed while reading: " +
                               std::string(path));
    }
    offset += static_cast<size_t>(read_count);
  }
  if (close(fd) != 0) {
    throw std::runtime_error("cannot close " + std::string(path) + ": " +
                             strerror(errno));
  }
  return FileData{std::move(data), size};
}

void write_stdout(const char *data, size_t length) {
  size_t offset = 0;
  while (offset < length) {
    const size_t count = std::min(
        length - offset, static_cast<size_t>(std::numeric_limits<ssize_t>::max()));
    const ssize_t write_count = write(STDOUT_FILENO, data + offset, count);
    if (write_count < 0) {
      if (errno == EINTR) {
        continue;
      }
      throw std::runtime_error("cannot write stdout: " +
                               std::string(strerror(errno)));
    }
    if (write_count == 0) {
      throw std::runtime_error("stdout made no progress");
    }
    offset += static_cast<size_t>(write_count);
  }
}

} // namespace

int main(int argc, char **argv) {
  try {
    bool decode = false;
    const char *input_path = nullptr;
    if (argc == 2) {
      input_path = argv[1];
    } else if (argc == 3 && std::string(argv[1]) == "--decode") {
      decode = true;
      input_path = argv[2];
    } else if (argc == 3 && std::string(argv[1]) == "--encode") {
      input_path = argv[2];
    } else {
      fprintf(stderr, "usage: %s [--decode] INPUT\n", argv[0]);
      return 2;
    }

    const FileData input = read_file(input_path);
    const size_t output_capacity = decode
                                       ? simdutf::maximal_binary_length_from_base64(
                                             input.bytes.get(), input.size)
                                       : simdutf::base64_length_from_binary(input.size);
    std::unique_ptr<char[]> output(
        new char[std::max<size_t>(output_capacity, 1)]);

    size_t output_length;
    if (decode) {
      const simdutf::result result = simdutf::base64_to_binary(
          input.bytes.get(), input.size, output.get(), simdutf::base64_default,
          simdutf::last_chunk_handling_options::loose);
      if (result.error != simdutf::error_code::SUCCESS) {
        throw std::runtime_error("invalid Base64 input");
      }
      output_length = result.count;
    } else {
      output_length = simdutf::binary_to_base64(
          input.bytes.get(), input.size, output.get(), simdutf::base64_default);
    }
    write_stdout(output.get(), output_length);
    return 0;
  } catch (const std::exception &error) {
    fprintf(stderr, "simdutf-fastbase64: %s\n", error.what());
    return 1;
  }
}
