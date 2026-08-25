#!/bin/sh
# Shipped in the workflow bundle's bin/. HealthOmics documents this directory as
# read-only + executable to tasks; whether it is reachable from `beforeScript`
# decides whether the real gate can be *delivered* to the point where it runs.
echo "bin_reachable=yes"
