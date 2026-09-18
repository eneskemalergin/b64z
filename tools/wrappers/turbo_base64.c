#include "turbob64.h"

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int usage(const char *program) {
  fprintf(stderr, "usage: %s [--decode] INPUT\n", program);
  return 2;
}

static int read_file(const char *path, unsigned char **data, size_t *length) {
  int fd = open(path, O_RDONLY);
  if (fd < 0) {
    fprintf(stderr, "turbo-base64: cannot open %s: %s\n", path,
            strerror(errno));
    return 1;
  }

  struct stat status;
  if (fstat(fd, &status) != 0) {
    fprintf(stderr, "turbo-base64: cannot stat %s: %s\n", path,
            strerror(errno));
    close(fd);
    return 1;
  }
  if (status.st_size < 0 || (uintmax_t)status.st_size > SIZE_MAX) {
    fprintf(stderr, "turbo-base64: input is too large: %s\n", path);
    close(fd);
    return 1;
  }

  size_t size = (size_t)status.st_size;
  unsigned char *buffer = malloc(size == 0 ? 1 : size);
  if (buffer == NULL) {
    fprintf(stderr, "turbo-base64: cannot allocate %zu bytes\n", size);
    close(fd);
    return 1;
  }

  size_t offset = 0;
  while (offset < size) {
    size_t count = size - offset;
    if (count > (size_t)SSIZE_MAX) {
      count = (size_t)SSIZE_MAX;
    }
    ssize_t read_count = read(fd, buffer + offset, count);
    if (read_count < 0) {
      if (errno == EINTR) {
        continue;
      }
      fprintf(stderr, "turbo-base64: cannot read %s: %s\n", path,
              strerror(errno));
      free(buffer);
      close(fd);
      return 1;
    }
    if (read_count == 0) {
      fprintf(stderr, "turbo-base64: input changed while reading: %s\n", path);
      free(buffer);
      close(fd);
      return 1;
    }
    offset += (size_t)read_count;
  }

  if (close(fd) != 0) {
    fprintf(stderr, "turbo-base64: cannot close %s: %s\n", path,
            strerror(errno));
    free(buffer);
    return 1;
  }

  *data = buffer;
  *length = size;
  return 0;
}

static int write_stdout(const unsigned char *data, size_t length) {
  size_t offset = 0;
  while (offset < length) {
    size_t count = length - offset;
    if (count > (size_t)SSIZE_MAX) {
      count = (size_t)SSIZE_MAX;
    }
    ssize_t write_count = write(STDOUT_FILENO, data + offset, count);
    if (write_count < 0) {
      if (errno == EINTR) {
        continue;
      }
      fprintf(stderr, "turbo-base64: cannot write stdout: %s\n",
              strerror(errno));
      return 1;
    }
    if (write_count == 0) {
      fprintf(stderr, "turbo-base64: stdout made no progress\n");
      return 1;
    }
    offset += (size_t)write_count;
  }
  return 0;
}

int main(int argc, char **argv) {
  int decode = 0;
  const char *input_path = NULL;
  if (argc == 2) {
    input_path = argv[1];
  } else if (argc == 3 && strcmp(argv[1], "--decode") == 0) {
    decode = 1;
    input_path = argv[2];
  } else if (argc == 3 && strcmp(argv[1], "--encode") == 0) {
    input_path = argv[2];
  } else {
    return usage(argv[0]);
  }

  unsigned char *input = NULL;
  size_t input_length = 0;
  if (read_file(input_path, &input, &input_length) != 0) {
    return 1;
  }

  tb64ini(0, 0);
  size_t output_capacity;
  if (decode) {
    output_capacity = tb64declen(input, input_length);
    if (input_length != 0 && output_capacity == 0) {
      fprintf(stderr, "turbo-base64: invalid Base64 input\n");
      free(input);
      return 1;
    }
  } else {
    output_capacity = tb64enclen(input_length);
  }

  unsigned char *output = malloc(output_capacity == 0 ? 1 : output_capacity);
  if (output == NULL) {
    fprintf(stderr, "turbo-base64: cannot allocate %zu bytes\n",
            output_capacity);
    free(input);
    return 1;
  }

  size_t output_length = decode
                             ? tb64dec(input, input_length, output)
                             : tb64enc(input, input_length, output);
  if (decode && input_length != 0 && output_length == 0) {
    fprintf(stderr, "turbo-base64: invalid Base64 input\n");
    free(output);
    free(input);
    return 1;
  }

  int result = write_stdout(output, output_length);
  free(output);
  free(input);
  return result;
}
