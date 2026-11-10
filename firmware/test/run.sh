#!/bin/sh
# Build and run the PC-side firmware tests (needs g++).
cd "$(dirname "$0")" || exit 1
g++ -std=c++17 -Wall -Wextra -O1 -o /tmp/limpet16_test test_host.cpp ../limpet16/src/ads131m08.cpp && /tmp/limpet16_test
