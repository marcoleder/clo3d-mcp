#--------------------------------------------------------------------------------
# clo_shim — C ABI over the CLO APIs that CLO's Python bindings cannot reach.
#
# Modelled on the CLO SDK's ExportPlugin sample, with two deliberate differences:
#   * no Qt          -> nothing here needs it, so retarget-qt.sh is never required
#   * not a plug-in  -> CLO does not load this; CLO's embedded Python dlopen()s it
#                       via ctypes, and it reaches the already-populated
#                       CLOAPI::APICommand singleton inside CLO's process.
#
# Build (Release only — debug binaries do not load in CLO):
#   macOS:    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCLO_SDK_DIR=...
#             cmake --build build --config Release -j 10
#   Windows:  cmake -S . -B build -A x64 -DCLO_SDK_DIR=C:/CLO_SDK
#             cmake --build build --config Release
#--------------------------------------------------------------------------------
cmake_minimum_required(VERSION 3.20)

project(clo_shim
    DESCRIPTION "C ABI shim for CLO APIs unreachable from Python"
    VERSION 2026.1.224
    LANGUAGES CXX
)

# Point this at your CLO SDK. Overridable: -DCLO_SDK_DIR=/path/to/CLO_SDK_...
if (WIN32)
    set(_clo_sdk_default "C:/CLO_SDK")
else()
    set(_clo_sdk_default "$ENV{HOME}/CLO_SDK")
endif()
set(CLO_SDK_DIR "${_clo_sdk_default}" CACHE PATH "Root of the CLO SDK")

if (NOT EXISTS "${CLO_SDK_DIR}/CLOAPIInterface/CLOAPIInterface.h")
    message(FATAL_ERROR "CLO SDK not found at ${CLO_SDK_DIR} — pass -DCLO_SDK_DIR=...")
endif()

add_library(${PROJECT_NAME} SHARED clo_shim.cpp)

# C++17: the SDK headers use structured bindings in places, and the samples
# only compile because they never touch those paths.
set_target_properties(${PROJECT_NAME} PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    CXX_EXTENSIONS OFF
    # no "lib" prefix games: keep the name stable for ctypes
    PREFIX "lib"
)

if(APPLE)
    target_compile_definitions(${PROJECT_NAME} PRIVATE CLO_API_INTERFACE_STATIC_BUILD)
elseif(MSVC)
    target_compile_definitions(${PROJECT_NAME} PRIVATE UNICODE _WINDOWS _USRDLL)
    set_target_properties(${PROJECT_NAME} PROPERTIES
        MSVC_RUNTIME_LIBRARY "MultiThreadedDLL"   # must match CLO
        PREFIX ""                                  # -> clo_shim.dll
    )

    # must match CLO (LSMinimumSystemVersion 12.0)
    set(CMAKE_OSX_DEPLOYMENT_TARGET 12.0)
    if ("${CMAKE_OSX_ARCHITECTURES}" STREQUAL "")
        execute_process(COMMAND uname -m COMMAND tr -d '\n'
                        OUTPUT_VARIABLE osx_architecture)
        set(CMAKE_OSX_ARCHITECTURES ${osx_architecture})
    endif()
    message("-- Target architecture: ${CMAKE_OSX_ARCHITECTURES}")
endif()

target_include_directories(${PROJECT_NAME} PRIVATE "${CLO_SDK_DIR}/CLOAPIInterface")

find_library(CLO_API_INTERFACE NAMES CLOAPIInterface
             HINTS "${CLO_SDK_DIR}/CLOAPIInterface/Lib" REQUIRED)
target_link_libraries(${PROJECT_NAME} PRIVATE ${CLO_API_INTERFACE})

# On Windows CLO.exe and CLOAPIInterface.dll sit next to each other, and the
# loader finds the DLL already in the process — no install-name surgery needed.
# macOS resolves by install name, hence the POST_BUILD step below.

#--------------------------------------------------------------------------------
# THE critical step: resolve CLOAPIInterface to the copy CLO already has loaded.
# Without this the shim would load a SECOND copy whose APICommand singleton is
# empty, and every call would return -2 (not ready).
if (APPLE)
    add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
        COMMAND ${CMAKE_INSTALL_NAME_TOOL} -change
            "@rpath/libCLOAPIInterface.dylib"
            "@executable_path/../Frameworks/libCLOAPIInterface.dylib"
            "$<TARGET_FILE:${PROJECT_NAME}>"
        COMMAND ${CMAKE_COMMAND} -E echo "-- linked against the CLOAPIInterface that CLO already has loaded"
    )
endif()
