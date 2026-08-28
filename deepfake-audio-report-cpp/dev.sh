#!/bin/bash
# Сборка и запуск прототипа в контейнере. Хостовая система не трогается.
#
#   ./dev.sh build    — собрать проект
#   ./dev.sh run      — собрать и запустить окно
#   ./dev.sh test     — самопроверка без окна
#   ./dev.sh shell    — оболочка внутри контейнера
set -euo pipefail
cd "$(dirname "$0")"

if ! command -v docker >/dev/null 2>&1; then
    echo "Не найден docker." >&2
    exit 1
fi

COMPOSE="docker compose -f docker-compose.dev.yml"
# UID в bash доступен только для чтения, поэтому имена свои
export HOST_UID="$(id -u)"
export HOST_GID="$(id -g)"

BUILD_DIR=build-docker
CONFIGURE="cmake -S . -B $BUILD_DIR -G Ninja -DCMAKE_BUILD_TYPE=Release"
COMPILE="cmake --build $BUILD_DIR -j\$(nproc)"

case "${1:-run}" in
    build)
        $COMPOSE run --rm dev bash -lc "$CONFIGURE && $COMPILE"
        ;;
    run)
        # Разрешаем контейнеру рисовать на нашем экране
        if command -v xhost >/dev/null 2>&1; then
            xhost +local:docker >/dev/null
        fi
        $COMPOSE run --rm dev bash -lc \
            "$CONFIGURE && $COMPILE && ./$BUILD_DIR/audio_forensics"
        ;;
    test)
        file="${2:-}"
        if [ -z "$file" ]; then
            echo "Использование: ./dev.sh test запись.wav" >&2
            exit 1
        fi
        $COMPOSE run --rm -e QT_QPA_PLATFORM=offscreen dev bash -lc \
            "$CONFIGURE && $COMPILE && ./$BUILD_DIR/audio_forensics --selftest '$file'"
        ;;
    shell)
        if command -v xhost >/dev/null 2>&1; then
            xhost +local:docker >/dev/null
        fi
        $COMPOSE run --rm dev bash
        ;;
    *)
        echo "Команды: build | run | test <файл> | shell" >&2
        exit 1
        ;;
esac
