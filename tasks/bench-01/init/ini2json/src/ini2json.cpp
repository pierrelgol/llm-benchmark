#include "ini2json/ini2json.hpp"
#include <filesystem>
#include <fstream>
#include <optional>
#include <string>
#include <string_view>

using namespace ini;

auto Parser::open_file(std::filesystem::path const& path) -> std::expected< std::ifstream, ParseError > {
        if (path.has_extension() == false or path.extension() != ".ini") {
                return std::unexpected(ParseError::invalid_extension);
        }

        std::error_code ec;
        if (std::filesystem::exists(path, ec) == false or not std::filesystem::is_regular_file(path)) {
                return std::unexpected(ParseError::file_not_found);
        }

        std::ifstream file(path);

        if (file.is_open() == false or file.fail() or file.bad()) {
                return std::unexpected(ParseError::fail_to_open);
        }

        return file;
}

static auto trim(std::string_view s, std::string_view elements) -> std::string_view {
        const auto begin = s.find_first_not_of(elements);

        if (begin == std::string_view::npos) {
                return {};
        }

        const auto end = s.find_last_not_of(elements);
        return s.substr(begin, end - begin + 1);
}

static auto is_comment(std::string_view line) -> bool {
        return line.starts_with(';') or line.starts_with('#');
}

auto Parser::parse(std::filesystem::path const& path) -> std::expected< void, ParseError > {
        auto       maybe_file = open_file(path);
        const auto whitespace = std::string_view(" \r\n\v\f\t");

        if (not maybe_file) {
                return std::unexpected(maybe_file.error());
        }

        auto file            = std::move(maybe_file).value();
        auto current_section = std::optional< Key >{};

        for (std::string line; std::getline(file, line);) {
                if (line.ends_with('\r')) {
                        line.pop_back();
                }

                const auto trimmed = trim(line, whitespace);

                if (trimmed.empty() or is_comment(trimmed)) {
                        continue;
                }

                if (trimmed.starts_with('[')) {
                        if (not trimmed.ends_with(']')) {
                                return std::unexpected(ParseError::invalid_syntax);
                        }

                        const auto section_name = std::string(trim(trimmed.substr(1, trimmed.size() - 2), whitespace));
                        if (section_name.empty() or m_entries.contains(section_name)) {
                                return std::unexpected(section_name.empty() ? ParseError::invalid_syntax : ParseError::duplicated_section);
                        }

                        m_entries.emplace(section_name, Section{});
                        current_section = section_name;
                        continue;
                }

                const auto separator = trimmed.find('=');
                if (separator == std::string_view::npos) {
                        return std::unexpected(ParseError::invalid_syntax);
                }

                const auto key   = std::string(trim(trimmed.substr(0, separator), whitespace));
                const auto value = std::string(trim(trimmed.substr(separator + 1), whitespace));
                if (key.empty()) {
                        return std::unexpected(ParseError::invalid_syntax);
                }

                auto& target = current_section ? m_entries.at(*current_section) : m_globals;
                if (target.contains(key)) {
                        return std::unexpected(ParseError::duplicated_variable);
                }

                target.emplace(key, value);
        }

        return {};
}

auto Parser::to_json() const -> nlohmann::json {
        auto output = nlohmann::json::object();

        for (const auto& [key, value] : m_globals) {
                output[key] = value;
        }

        for (const auto& [section_name, section] : m_entries) {
                output[section_name] = section;
        }

        return output;
}
