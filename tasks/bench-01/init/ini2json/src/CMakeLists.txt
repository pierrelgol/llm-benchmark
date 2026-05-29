add_library(ini2json_lib
  ini2json.cpp
)

target_include_directories(ini2json_lib
  PUBLIC
    ${PROJECT_SOURCE_DIR}/include
)

target_link_libraries(ini2json_lib
  PUBLIC
    nlohmann_json::nlohmann_json
)

target_compile_options(ini2json_lib
  PRIVATE
    -Wall
    -Wextra
    -Wpedantic
)

add_executable(ini2json
  main.cpp
)

target_link_libraries(ini2json
  PRIVATE
    ini2json_lib
)
