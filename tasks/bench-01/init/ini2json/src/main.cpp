#include "ini2json/ini2json.hpp"
#include <array>
#include <cstdint>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <optional>
#include <random>
#include <sstream>
#include <string>
#include <string_view>

namespace {

enum class GenerateKind {
        none,
        valid,
        invalid,
};

struct Options {
        std::string   input_file;
        int           indent        = 2;
        int           section_count = 3;
        int           key_count     = 4;
        char          indent_char   = ' ';
        bool          compact       = false;
        bool          indent_set    = false;
        GenerateKind  generate      = GenerateKind::none;
        std::uint64_t seed          = 0;
        bool          seed_set      = false;
};

auto usage(std::ostream& out) -> void {
        out << "Usage: ini2json [OPTIONS] FILE\n"
            << "       ini2json --generate valid|invalid [OPTIONS]\n"
            << "\n"
            << "Convert an INI file to JSON or generate random INI files.\n"
            << "\n"
            << "Options:\n"
            << "  -c, --compact       Output single-line JSON\n"
            << "  -i, --indent N      Number of spaces per indentation level (default: 2)\n"
            << "  -t, --tab           Indent pretty JSON with tabs instead of spaces\n"
            << "  -g, --generate K    Generate random INI instead of parsing a file (valid or invalid)\n"
            << "  -s, --seed N        Use an explicit generator seed\n"
            << "      --sections N    Number of generated sections from 0 to 32 (default: 3)\n"
            << "      --keys N        Number of generated keys per scope from 0 to 64 (default: 4)\n"
            << "  -h, --help          Show this help message\n";
}

auto parse_int(std::string_view value, int max) -> std::optional< int > {
        if (value.empty()) {
                return std::nullopt;
        }

        auto result = 0;
        for (const auto ch : value) {
                if (ch < '0' or ch > '9') {
                        return std::nullopt;
                }

                result = (result * 10) + (ch - '0');
                if (result > max) {
                        return std::nullopt;
                }
        }

        return result;
}

auto parse_seed(std::string_view value) -> std::optional< std::uint64_t > {
        if (value.empty()) {
                return std::nullopt;
        }

        auto result = std::uint64_t{0};
        for (const auto ch : value) {
                if (ch < '0' or ch > '9') {
                        return std::nullopt;
                }

                const auto digit = static_cast< std::uint64_t >(ch - '0');
                if (result > (std::numeric_limits< std::uint64_t >::max() - digit) / 10) {
                        return std::nullopt;
                }

                result = (result * 10) + digit;
        }

        return result;
}

auto parse_generate_kind(std::string_view value) -> std::optional< GenerateKind > {
        if (value == "valid") {
                return GenerateKind::valid;
        }

        if (value == "invalid") {
                return GenerateKind::invalid;
        }

        return std::nullopt;
}

auto parse_options(int argc, char** argv) -> std::optional< Options > {
        auto options = Options{};

        for (auto i = 1; i < argc; ++i) {
                const auto arg = std::string_view(argv[i]);

                if (arg == "-h" or arg == "--help") {
                        usage(std::cout);
                        std::exit(0);
                }

                if (arg == "-c" or arg == "--compact") {
                        options.compact = true;
                        continue;
                }

                if (arg == "-t" or arg == "--tab") {
                        options.indent_char = '\t';
                        if (not options.indent_set) {
                                options.indent = 1;
                        }
                        continue;
                }

                if (arg == "-i" or arg == "--indent") {
                        if (i + 1 >= argc) {
                                std::cerr << "ini2json: missing value for " << arg << "\n";
                                return std::nullopt;
                        }

                        const auto indent = parse_int(argv[++i], 32);
                        if (not indent) {
                                std::cerr << "ini2json: indent must be an integer from 0 to 32\n";
                                return std::nullopt;
                        }

                        options.indent     = *indent;
                        options.indent_set = true;
                        continue;
                }

                if (arg.starts_with("--indent=")) {
                        const auto indent = parse_int(arg.substr(std::string_view("--indent=").size()), 32);
                        if (not indent) {
                                std::cerr << "ini2json: indent must be an integer from 0 to 32\n";
                                return std::nullopt;
                        }

                        options.indent     = *indent;
                        options.indent_set = true;
                        continue;
                }

                if (arg == "-g" or arg == "--generate") {
                        if (i + 1 >= argc) {
                                std::cerr << "ini2json: missing value for " << arg << "\n";
                                return std::nullopt;
                        }

                        const auto kind = parse_generate_kind(argv[++i]);
                        if (not kind) {
                                std::cerr << "ini2json: generate kind must be valid or invalid\n";
                                return std::nullopt;
                        }

                        options.generate = *kind;
                        continue;
                }

                if (arg.starts_with("--generate=")) {
                        const auto kind = parse_generate_kind(arg.substr(std::string_view("--generate=").size()));
                        if (not kind) {
                                std::cerr << "ini2json: generate kind must be valid or invalid\n";
                                return std::nullopt;
                        }

                        options.generate = *kind;
                        continue;
                }

                if (arg == "-s" or arg == "--seed") {
                        if (i + 1 >= argc) {
                                std::cerr << "ini2json: missing value for " << arg << "\n";
                                return std::nullopt;
                        }

                        const auto seed = parse_seed(argv[++i]);
                        if (not seed) {
                                std::cerr << "ini2json: seed must be an unsigned 64-bit integer\n";
                                return std::nullopt;
                        }

                        options.seed     = *seed;
                        options.seed_set = true;
                        continue;
                }

                if (arg.starts_with("--seed=")) {
                        const auto seed = parse_seed(arg.substr(std::string_view("--seed=").size()));
                        if (not seed) {
                                std::cerr << "ini2json: seed must be an unsigned 64-bit integer\n";
                                return std::nullopt;
                        }

                        options.seed     = *seed;
                        options.seed_set = true;
                        continue;
                }

                if (arg == "--sections") {
                        if (i + 1 >= argc) {
                                std::cerr << "ini2json: missing value for " << arg << "\n";
                                return std::nullopt;
                        }

                        const auto count = parse_int(argv[++i], 32);
                        if (not count) {
                                std::cerr << "ini2json: sections must be an integer from 0 to 32\n";
                                return std::nullopt;
                        }

                        options.section_count = *count;
                        continue;
                }

                if (arg.starts_with("--sections=")) {
                        const auto count = parse_int(arg.substr(std::string_view("--sections=").size()), 32);
                        if (not count) {
                                std::cerr << "ini2json: sections must be an integer from 0 to 32\n";
                                return std::nullopt;
                        }

                        options.section_count = *count;
                        continue;
                }

                if (arg == "--keys") {
                        if (i + 1 >= argc) {
                                std::cerr << "ini2json: missing value for " << arg << "\n";
                                return std::nullopt;
                        }

                        const auto count = parse_int(argv[++i], 64);
                        if (not count) {
                                std::cerr << "ini2json: keys must be an integer from 0 to 64\n";
                                return std::nullopt;
                        }

                        options.key_count = *count;
                        continue;
                }

                if (arg.starts_with("--keys=")) {
                        const auto count = parse_int(arg.substr(std::string_view("--keys=").size()), 64);
                        if (not count) {
                                std::cerr << "ini2json: keys must be an integer from 0 to 64\n";
                                return std::nullopt;
                        }

                        options.key_count = *count;
                        continue;
                }

                if (arg.starts_with("-")) {
                        std::cerr << "ini2json: unknown option: " << arg << "\n";
                        return std::nullopt;
                }

                if (not options.input_file.empty()) {
                        std::cerr << "ini2json: expected exactly one input file\n";
                        return std::nullopt;
                }

                options.input_file = std::string(arg);
        }

        if (options.generate != GenerateKind::none and not options.input_file.empty()) {
                std::cerr << "ini2json: generate mode does not accept an input file\n";
                return std::nullopt;
        }

        if (options.generate == GenerateKind::none and options.input_file.empty()) {
                std::cerr << "ini2json: missing input file\n";
                return std::nullopt;
        }

        return options;
}

auto random_index(std::mt19937_64& rng, std::size_t size) -> std::size_t {
        auto dist = std::uniform_int_distribution< std::size_t >(0, size - 1);
        return dist(rng);
}

auto random_token(std::mt19937_64& rng, std::string_view prefix, int index) -> std::string {
        constexpr auto alphabet    = std::string_view("abcdefghijklmnopqrstuvwxyz0123456789_-");
        auto           length_dist = std::uniform_int_distribution< int >(3, 10);
        auto           out         = std::ostringstream{};

        out << prefix << index << '_';
        for (auto i = 0; i < length_dist(rng); ++i) {
                out << alphabet[random_index(rng, alphabet.size())];
        }

        return out.str();
}

auto random_value(std::mt19937_64& rng, int index) -> std::string {
        constexpr auto words = std::array{
            std::string_view("alpha"),
            std::string_view("bravo"),
            std::string_view("charlie"),
            std::string_view("delta"),
            std::string_view("echo"),
            std::string_view("42"),
            std::string_view("true"),
            std::string_view("false"),
            std::string_view("/home/foo/bar/baz"),
            std::string_view("42.69420"),
        };

        auto out = std::ostringstream{};
        out << words[random_index(rng, words.size())] << '_' << index;
        return out.str();
}

auto write_key_values(std::ostream& out, std::mt19937_64& rng, std::string_view prefix, int count) -> void {
        for (auto i = 0; i < count; ++i) {
                out << random_token(rng, prefix, i) << " = " << random_value(rng, i) << '\n';
        }
}

auto generated_seed(const Options& options) -> std::uint64_t {
        if (options.seed_set) {
                return options.seed;
        }

        auto device = std::random_device{};
        return (static_cast< std::uint64_t >(device()) << 32) ^ static_cast< std::uint64_t >(device());
}

auto generate_valid_ini(const Options& options, std::uint64_t seed) -> std::string {
        auto rng = std::mt19937_64(seed);
        auto out = std::ostringstream{};

        out << "; seed: " << seed << '\n';
        write_key_values(out, rng, "global", options.key_count);

        for (auto section = 0; section < options.section_count; ++section) {
                if (options.key_count > 0 or section == 0) {
                        out << '\n';
                }
                out << '[' << random_token(rng, "section", section) << "]\n";
                write_key_values(out, rng, "key", options.key_count);
        }

        return out.str();
}

auto generate_invalid_ini(const Options& options, std::uint64_t seed) -> std::string {
        auto           rng           = std::mt19937_64(seed);
        auto           base          = generate_valid_ini(options, seed);
        auto           out           = std::ostringstream{};

        constexpr auto invalid_forms = std::array{
            std::string_view("unterminated_section"),
            std::string_view("empty_section"),
            std::string_view("missing_separator"),
            std::string_view("empty_key"),
            std::string_view("duplicate_section"),
            std::string_view("duplicate_key"),
        };

        const auto form = invalid_forms[random_index(rng, invalid_forms.size())];
        out << base;
        if (not base.ends_with('\n')) {
                out << '\n';
        }

        if (form == "unterminated_section") {
                out << "[broken_section\n";
        } else if (form == "empty_section") {
                out << "[]\n";
        } else if (form == "missing_separator") {
                out << "broken_key_without_separator\n";
        } else if (form == "empty_key") {
                out << " = value\n";
        } else if (form == "duplicate_section") {
                out << "[duplicate]\n"
                    << "value = first\n"
                    << "[duplicate]\n"
                    << "value = second\n";
        } else {
                out << "[duplicate_key]\n"
                    << "value = first\n"
                    << "value = second\n";
        }

        return out.str();
}

auto error_message(ini::ParseError error) -> std::string_view {
        switch (error) {
                case ini::ParseError::fail_to_open : return "failed to open file";
                case ini::ParseError::file_not_found : return "file not found";
                case ini::ParseError::invalid_extension : return "input file must have a .ini extension";
                case ini::ParseError::invalid_syntax : return "invalid INI syntax";
                case ini::ParseError::duplicated_section : return "duplicated section";
                case ini::ParseError::duplicated_variable : return "duplicated variable";
        }

        return "unknown parse error";
}

} // namespace

int main(int argc, char** argv) {
        const auto options = parse_options(argc, argv);
        if (not options) {
                usage(std::cerr);
                return 1;
        }

        if (options->generate != GenerateKind::none) {
                const auto seed = generated_seed(*options);
                if (options->generate == GenerateKind::valid) {
                        std::cout << generate_valid_ini(*options, seed);
                } else {
                        std::cout << generate_invalid_ini(*options, seed);
                }

                return 0;
        }

        auto       parser = ini::Parser{};
        const auto parsed = parser.parse(options->input_file);
        if (not parsed) {
                std::cerr << "ini2json: " << error_message(parsed.error()) << ": " << options->input_file << "\n";
                return 1;
        }

        const auto json = parser.to_json();
        if (options->compact) {
                std::cout << json.dump() << '\n';
        } else {
                std::cout << json.dump(options->indent, options->indent_char) << '\n';
        }

        return 0;
}
