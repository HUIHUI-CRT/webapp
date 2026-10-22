# CMake 构建脚本：把 fastcore.cpp 编译成 Python 可导入的扩展模块。
#
# 用法（在任意构建目录中执行）：
#     cmake -S backend/cpp -B backend/build -DCMAKE_BUILD_TYPE=Release
#     cmake --build backend/build --config Release
# 产物默认落在 backend/build/（模块名 fastcore），后端启动时会在该目录搜索。
#
# Windows + MinGW 生成器示例：
#     cmake -S backend/cpp -B backend/build -G "MinGW Makefiles" ^
#           -DCMAKE_MAKE_PROGRAM=... -DCMAKE_CXX_COMPILER=.../g++.exe

cmake_minimum_required(VERSION 3.15)
project(fastcore LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

# 优先使用已安装的 pybind11 包，其次回退到 pip 安装的 pybind11 包路径。
find_package(pybind11 CONFIG QUIET)

if(NOT pybind11_FOUND)
  find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
  execute_process(
    COMMAND "${Python_EXECUTABLE}" -m pybind11 --cmakedir
    OUTPUT_VARIABLE pybind11_ROOT
    OUTPUT_STRIP_TRAILING_WHITESPACE
    ERROR_QUIET
  )
  if(pybind11_ROOT)
    list(APPEND CMAKE_PREFIX_PATH "${pybind11_ROOT}")
    find_package(pybind11 CONFIG REQUIRED)
  else()
    message(FATAL_ERROR "未找到 pybind11，请先执行: pip install pybind11")
  endif()
endif()

pybind11_add_module(fastcore MODULE fastcore.cpp)

if(MSVC)
  target_compile_options(fastcore PRIVATE /O2 /utf-8)
else()
  target_compile_options(fastcore PRIVATE -O3 -Wall)
endif()

# MinGW：把 gcc / libstdc++ / winpthread 运行库静态链进模块，
# 否则 .pyd 会依赖 libgcc_s_seh-1.dll 等文件，在未安装 MSYS2 的机器上无法导入。
if(MINGW)
  target_link_options(fastcore PRIVATE -static-libgcc -static-libstdc++ -static)
endif()

# 让产物直接出现在构建目录根部，方便后端把它加入 sys.path。
set_target_properties(fastcore PROPERTIES
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}"
  LIBRARY_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}"
  RUNTIME_OUTPUT_DIRECTORY_RELEASE "${CMAKE_BINARY_DIR}"
)
