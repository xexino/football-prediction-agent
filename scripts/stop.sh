#!/usr/bin/env bash
pkill -f "^python3 -m fil serve" && echo stopped || echo "not running"
