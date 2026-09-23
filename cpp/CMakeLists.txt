#--------------------------------------------------------------------------------
# CLO native plugin, reusable bridge/test targets, and Python fallback shim.
#
# The default shim target has no Qt dependency and is loaded via Python ctypes.
# The opt-in plugin uses the SDK's general entry points and CLO's Qt event loop.
# Both resolve the already-populated CLOAPI::APICommand singleton in the host.
#
# Build (Release only — debug binaries do not load in CLO):
#   macOS:    cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DCLO_SDK_DIR=...
#             cmake --build build --config Release -j 10
#   Windows:  cmake -S . -B build -A x64 -DCLO_SDK_DIR=C:/CLO_SDK
#             cmake --build build --config Release
#--------------------------------------------------------------------------------
cmake_minimum_required(VERSION 3.20)

# Match the bundled 2026.1 SDK library's minimum OS; respect explicit overrides.
if(CMAKE_HOST_APPLE AND NOT DEFINED CMAKE_OSX_DEPLOYMENT_TARGET)
    set(CMAKE_OSX_DEPLOYMENT_TARGET "15.0" CACHE STRING "Minimum macOS version")
endif()

project(clo_shim
    DESCRIPTION "Native CLO MCP bridge and Python fallback shim"
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

option(CLO_BUILD_SHIM "Build the Python fallback's ctypes shim" ON)
option(CLO_BUILD_NATIVE_PLUGIN "Build the opt-in native CLO plugin" OFF)
option(CLO_BUILD_NATIVE_TESTS "Build offline native bridge tests" OFF)

if(CLO_BUILD_SHIM OR CLO_BUILD_NATIVE_PLUGIN)
    if (NOT EXISTS "${CLO_SDK_DIR}/CLOAPIInterface/CLOAPIInterface.h")
        message(FATAL_ERROR "CLO SDK not found at ${CLO_SDK_DIR} — pass -DCLO_SDK_DIR=...")
    endif()
    find_library(CLO_API_INTERFACE NAMES CLOAPIInterface
                 HINTS "${CLO_SDK_DIR}/CLOAPIInterface/Lib" REQUIRED)
endif()

if(CLO_BUILD_SHIM)
add_library(${PROJECT_NAME} SHARED clo_shim.cpp)

# C++17: the SDK headers use structured bindings in places, and the samples
# only compile because they never touch those paths.
set_target_properties(${PROJECT_NAME} PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
    CXX_EXTENSIONS OFF
    # no "lib" prefix games: keep the name stable for ctypes
    PREFIX "lib"
    # Versioned filename avoids reusing a loaded ABI-1 image after an upgrade.
    OUTPUT_NAME "clo_shim_v2"
)

if(APPLE)
    target_compile_definitions(${PROJECT_NAME} PRIVATE CLO_API_INTERFACE_STATIC_BUILD)
elseif(MSVC)
    target_compile_definitions(${PROJECT_NAME} PRIVATE UNICODE _WINDOWS _USRDLL)
    set_target_properties(${PROJECT_NAME} PROPERTIES
        WINDOWS_EXPORT_ALL_SYMBOLS ON
        MSVC_RUNTIME_LIBRARY "MultiThreadedDLL"   # must match CLO
        PREFIX ""                                  # -> clo_shim_v2.dll
    )
endif()
target_include_directories(${PROJECT_NAME} PRIVATE "${CLO_SDK_DIR}/CLOAPIInterface")
target_link_libraries(${PROJECT_NAME} PRIVATE ${CLO_API_INTERFACE})
if(APPLE)
    # Resolve the singleton CLO already populated, not a second SDK library.
    add_custom_command(TARGET ${PROJECT_NAME} POST_BUILD
        COMMAND ${CMAKE_INSTALL_NAME_TOOL} -change
            "@rpath/libCLOAPIInterface.dylib"
            "@executable_path/../Frameworks/libCLOAPIInterface.dylib"
            "$<TARGET_FILE:${PROJECT_NAME}>")
endif()
endif() # CLO_BUILD_SHIM

if(CLO_BUILD_NATIVE_PLUGIN OR CLO_BUILD_NATIVE_TESTS)
    find_package(Qt6 6.10.3 EXACT REQUIRED COMPONENTS Core Gui)
    add_library(clo_bridge_core STATIC
        bridge/PlatformLock.cpp bridge/JsonFiles.cpp bridge/SceneReviewState.cpp
        bridge/ProtocolQueue.cpp bridge/BridgeController.cpp)
    target_compile_features(clo_bridge_core PUBLIC cxx_std_17)
    target_include_directories(clo_bridge_core PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/bridge")
    target_link_libraries(clo_bridge_core PUBLIC Qt6::Core)
    set_target_properties(clo_bridge_core PROPERTIES POSITION_INDEPENDENT_CODE ON)
    if(CLO_BUILD_NATIVE_PLUGIN)
        set(_clo_headers "${CLO_SDK_DIR}/CLOAPIInterface")
    else()
        set(_clo_headers "${CMAKE_CURRENT_SOURCE_DIR}/../sdk/CLOAPIInterface")
    endif()
    add_library(clo_bridge_commands STATIC
        bridge/CommandDispatcher.cpp bridge/ResultContracts.cpp bridge/ExportOptions.cpp bridge/Artifacts.cpp
        bridge/handlers/Scene.cpp bridge/handlers/Patterns.cpp bridge/handlers/Fabrics.cpp
        bridge/handlers/Colorways.cpp bridge/handlers/Avatars.cpp bridge/handlers/Simulation.cpp bridge/handlers/Exports.cpp)
    target_include_directories(clo_bridge_commands PUBLIC "${_clo_headers}")
    target_link_libraries(clo_bridge_commands PUBLIC clo_bridge_core Qt6::Gui)
    set_target_properties(clo_bridge_commands PROPERTIES POSITION_INDEPENDENT_CODE ON)
endif()

if(CLO_BUILD_NATIVE_PLUGIN)
    if(CMAKE_CONFIGURATION_TYPES)
        set(CMAKE_CONFIGURATION_TYPES Release CACHE STRING "CLO supports Release plugins only" FORCE)
    endif()
    if(NOT CMAKE_CONFIGURATION_TYPES AND NOT CMAKE_BUILD_TYPE STREQUAL "Release")
        message(FATAL_ERROR "CLO requires a Release plugin build")
    endif()
    if(NOT APPLE AND NOT MSVC)
        message(FATAL_ERROR "The CLO host plugin targets macOS or MSVC Windows")
    endif()
    find_package(Qt6 6.10.3 EXACT REQUIRED COMPONENTS Widgets)
    add_library(clo_mcp_plugin SHARED bridge/PluginEntry.cpp bridge/SdkHost.cpp)
    target_include_directories(clo_mcp_plugin PRIVATE "${CLO_SDK_DIR}/CLOAPIInterface")
    target_link_libraries(clo_mcp_plugin PRIVATE clo_bridge_commands Qt6::Widgets ${CLO_API_INTERFACE})
    set_target_properties(clo_mcp_plugin PROPERTIES OUTPUT_NAME "clo_mcp_plugin_v1"
        CXX_VISIBILITY_PRESET hidden VISIBILITY_INLINES_HIDDEN ON
        MSVC_RUNTIME_LIBRARY "MultiThreadedDLL")
    if(APPLE)
        target_compile_definitions(clo_mcp_plugin PRIVATE CLO_API_INTERFACE_STATIC_BUILD)
        add_custom_command(TARGET clo_mcp_plugin POST_BUILD
            COMMAND ${CMAKE_COMMAND} -DPLUGIN=$<TARGET_FILE:clo_mcp_plugin>
                -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/RetargetHost.cmake")
    endif()
    add_custom_command(TARGET clo_mcp_plugin POST_BUILD
        COMMAND ${CMAKE_COMMAND} -DPLUGIN=$<TARGET_FILE:clo_mcp_plugin>
            -DSDK=${CLO_SDK_DIR} -DQT=${Qt6Core_VERSION} -DCONFIG=$<CONFIG>
            "-DCOMPILER=${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}"
            -P "${CMAKE_CURRENT_SOURCE_DIR}/cmake/Manifest.cmake"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${CMAKE_CURRENT_SOURCE_DIR}/../NOTICE" "$<TARGET_FILE_DIR:clo_mcp_plugin>/NOTICE"
        COMMAND ${CMAKE_COMMAND} -E copy_if_different "${CMAKE_CURRENT_SOURCE_DIR}/../LICENSE" "$<TARGET_FILE_DIR:clo_mcp_plugin>/LICENSE")
endif()

if(CLO_BUILD_NATIVE_TESTS)
    enable_testing()
    add_executable(clo_queue_harness tests/QueueHarness.cpp)
    target_link_libraries(clo_queue_harness PRIVATE clo_bridge_core)
    add_executable(clo_protocol_tests tests/ProtocolTests.cpp)
    target_link_libraries(clo_protocol_tests PRIVATE clo_bridge_core)
    add_test(NAME native_protocol COMMAND clo_protocol_tests)
    add_executable(clo_command_tests tests/CommandTests.cpp)
    target_link_libraries(clo_command_tests PRIVATE clo_bridge_commands)
    add_test(NAME native_commands COMMAND clo_command_tests "${CMAKE_CURRENT_SOURCE_DIR}/../tests/fixtures/result_contracts.json")
    add_executable(clo_export_tests tests/ExportTests.cpp)
    target_link_libraries(clo_export_tests PRIVATE clo_bridge_commands)
    add_test(NAME native_exports COMMAND clo_export_tests)
endif()
