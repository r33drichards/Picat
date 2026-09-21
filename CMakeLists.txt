cmake_minimum_required(VERSION 3.27)
project(picat
        LANGUAGES C CXX
        VERSION 7.3
)

include(GNUInstallDirs)

if(DEFINED OPENBSD_LOCALBASE)
    include_directories(${OPENBSD_LOCALBASE}/include)
    link_directories(${OPENBSD_LOCALBASE}/lib)
endif()

set(CMAKE_MODULE_PATH
        ${CMAKE_CURRENT_LIST_DIR}/cmake
        ${CMAKE_MODULE_PATH}
)

if(${CMAKE_SYSTEM_NAME} STREQUAL "OpenBSD")
        set(SYSTEM_NAME "OPENBSD")
elseif(${CMAKE_SYSTEM_NAME} STREQUAL "Linux")
        set(SYSTEM_NAME "LINUX")
else()
        message(FATAL_ERROR "Unsupported system: ${CMAKE_SYSTEM_NAME}")
endif()

if (CMAKE_SIZEOF_VOID_P EQUAL 8)
    set(64BITS M64BITS)
    message(STATUS "Set 64bit")
endif ()

# Optional in-process Laya inference (lib2/laya.pi, emu/laya_interface.cpp).
# The laya.cpp runtime is a git submodule at emu/laya.cpp; it is added here,
# before Picat's global compile flags, so those flags do not leak into ggml.
option(PICAT_LAYA "Build the laya decision-model module (needs the emu/laya.cpp submodule, ICU and nlohmann-json)" OFF)
option(PICAT_LAYA_CUDA "Build the laya module with the CUDA backend" OFF)
if(PICAT_LAYA)
    if(NOT EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/emu/laya.cpp/CMakeLists.txt")
        message(FATAL_ERROR "PICAT_LAYA=ON but emu/laya.cpp is empty; run: git submodule update --init --recursive")
    endif()
    set(LAYA_CUDA ${PICAT_LAYA_CUDA} CACHE BOOL "" FORCE)
    set(BUILD_SHARED_LIBS OFF)
    set(BUILD_TESTING OFF)
    add_subdirectory(emu/laya.cpp EXCLUDE_FROM_ALL)
endif()

add_compile_definitions(unix POSIX ${SYSTEM_NAME} GC PICAT SAT ${64BITS})
add_compile_options(-O3 -fno-strict-aliasing -finline-functions -fomit-frame-pointer -Wno-error=unused-label)

add_subdirectory(emu)
