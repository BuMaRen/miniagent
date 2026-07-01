#!/bin/bash
find . -path ./.venv -prune -o -type d -name __pycache__ -print -exec rm -rf {} +
