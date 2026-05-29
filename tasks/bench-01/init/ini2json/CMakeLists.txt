cmake_minimum_required(VERSION 3.24)

find_program(INI2JSON_CLANG clang)
find_program(INI2JSON_CLANGXX clang++)

if(NOT CMAKE_C_COMPILER AND INI2JSON_CLANG)
  set(CMAKE_C_COMPILER "${INI2JSON_CLANG}" CACHE STRING "C compiler")
endif()

if(NOT CMAKE_CXX_COMPILER AND INI2JSON_CLANGXX)
  set(CMAKE_CXX_COMPILER "${INI2JSON_CLANGXX}" CACHE STRING "C++ compiler")
endif()

project(ini2json VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 23)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

include(FetchContent)

FetchContent_Declare(
  nlohmann_json
  GIT_REPOSITORY https://github.com/nlohmann/json.git
  GIT_TAG v3.12.0
)

FetchContent_MakeAvailable(nlohmann_json)

add_subdirectory(src)
