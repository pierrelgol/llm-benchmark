# ini2json

C++23 INI parser that outputs JSON.

## Build

This project uses CMake, Clang, and `nlohmann/json` fetched at configure time.

```bash
just build
```

## Run

```bash
just run path/to/file.ini
```

```bash
./build/src/ini2json --compact path/to/file.ini
./build/src/ini2json --indent 4 path/to/file.ini
./build/src/ini2json --tab path/to/file.ini
```

Formatting options:

- `--compact`, `-c`: output single-line JSON.
- `--indent N`, `-i N`: set pretty-print indentation width from `0` to `32` spaces. Default is `2`.
- `--tab`, `-t`: use tabs for pretty-print indentation.

## Generate INI

```bash
./build/src/ini2json --generate valid --seed 123 --sections 2 --keys 4
./build/src/ini2json --generate invalid --seed 123
```

Generation options:

- `--generate valid|invalid`, `-g valid|invalid`: write a random INI file to stdout instead of parsing a file.
- `--seed N`, `-s N`: use an unsigned 64-bit seed for reproducible output. If omitted, a random seed is used.
- `--sections N`: set generated section count from `0` to `32`. Default is `3`.
- `--keys N`: set generated key count per global scope and section from `0` to `64`. Default is `4`.

Generated files include the seed as an INI comment on the first line.
