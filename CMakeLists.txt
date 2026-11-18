cmake_minimum_required(VERSION 3.22)
project(beamcore LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_compile_options(-Wall -Wextra -Wpedantic -Wconversion -Wshadow -Werror -Wno-error=sign-conversion -Wno-sign-conversion)

add_library(beamcore STATIC cpp/beamcore/src/beamcore.cpp)
target_include_directories(beamcore PUBLIC cpp/beamcore/include)

add_executable(beamcore_tests cpp/beamcore/tests/test_beamcore.cpp)
target_link_libraries(beamcore_tests PRIVATE beamcore)

option(BEAMCORE_PYTHON "Build the Python module" ON)
if(BEAMCORE_PYTHON)
  find_package(Python3 COMPONENTS Interpreter Development.Module REQUIRED)
  execute_process(COMMAND ${Python3_EXECUTABLE} -c "import pybind11; print(pybind11.get_cmake_dir())"
                  OUTPUT_VARIABLE pybind11_DIR OUTPUT_STRIP_TRAILING_WHITESPACE)
  find_package(pybind11 CONFIG REQUIRED)
  pybind11_add_module(_beamcore cpp/beamcore/src/bindings.cpp)
  target_link_libraries(_beamcore PRIVATE beamcore)
  set_target_properties(_beamcore PROPERTIES LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/lbp)
endif()
