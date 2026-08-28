cmake_minimum_required(VERSION 3.16)
project(audio_forensics LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 REQUIRED COMPONENTS Core Gui Widgets Network WebSockets Concurrent)
find_package(ZLIB REQUIRED)

add_executable(audio_forensics
    src/main.cpp
    src/analysis.cpp
    src/plots.cpp
    src/player.cpp
    src/service.cpp
    src/detectors.cpp
    src/docx.cpp
    src/report.cpp
    src/batch.cpp
    src/mainwindow.cpp
)

target_link_libraries(audio_forensics PRIVATE
    Qt6::Core Qt6::Gui Qt6::Widgets Qt6::Network Qt6::WebSockets Qt6::Concurrent
    ZLIB::ZLIB
)

