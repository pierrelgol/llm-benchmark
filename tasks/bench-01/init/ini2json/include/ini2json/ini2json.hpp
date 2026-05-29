#ifndef INI2JSON_HPP
#define INI2JSON_HPP

#include <nlohmann/json.hpp>
#include <expected>
#include <filesystem>
#include <fstream>
#include <map>
#include <string>


namespace ini {

enum class ParseError {
        fail_to_open,
        file_not_found,
        invalid_extension,
        invalid_syntax,
        duplicated_section,
        duplicated_variable,
};

class Parser {
      public:
        using Key            = std::string;
        using Value          = std::string;
        using Section        = std::map< Key, Value >;
        using Entries        = std::map< Key, Section >;

        using iterator       = Entries::iterator;
        using const_iterator = Entries::const_iterator;

      private:
        Section m_globals;
        Entries m_entries;


        auto    open_file(std::filesystem::path const& file) -> std::expected< std::ifstream, ParseError >;

      public:
        Parser()                          = default;
        Parser(const Parser&)             = default;
        Parser(Parser&&)                  = default;
        Parser&  operator=(const Parser&) = default;
        Parser&  operator=(Parser&&)      = default;

        iterator begin() noexcept {
                return m_entries.begin();
        }

        iterator end() noexcept {
                return m_entries.end();
        }

        const_iterator begin() const noexcept {
                return m_entries.begin();
        }

        const_iterator end() const noexcept {
                return m_entries.end();
        }

        const_iterator cbegin() const noexcept {
                return m_entries.cbegin();
        }

        const_iterator cend() const noexcept {
                return m_entries.cend();
        }

        auto parse(std::filesystem::path const& file) -> std::expected< void, ParseError >;
        auto to_json() const -> nlohmann::json;
};

} // namespace ini

#endif
