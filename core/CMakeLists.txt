cmake_minimum_required(VERSION 3.16)
project(zerotrace_core VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# Find Python and pybind11
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)
find_package(pybind11 REQUIRED)

# Find OpenSSL for AES in Purge mode
find_package(OpenSSL REQUIRED)

# Find libblkid for block device detection
find_library(BLKID_LIB blkid REQUIRED)

# Source files for the core library
set(CORE_SOURCES
    src/device.cpp
    src/ata.cpp
    src/nvme.cpp
    src/wipe_clear.cpp
    src/wipe_purge.cpp
    src/wipe_firmware.cpp
    src/entropy.cpp
    src/timing.cpp
)

# Build as a static library first (for testing)
add_library(zerotrace_core_static STATIC ${CORE_SOURCES})
target_include_directories(zerotrace_core_static PUBLIC include)
target_link_libraries(zerotrace_core_static
    OpenSSL::SSL
    OpenSSL::Crypto
    ${BLKID_LIB}
)

# Build the pybind11 Python module
pybind11_add_module(zerotrace_core src/bindings.cpp ${CORE_SOURCES})
target_include_directories(zerotrace_core PUBLIC include)
target_link_libraries(zerotrace_core PRIVATE
    OpenSSL::SSL
    OpenSSL::Crypto
    ${BLKID_LIB}
)
