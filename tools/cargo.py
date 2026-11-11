#!/usr/bin/env python3
"""Invoke the project-local compiler and Cargo cache."""
import sys
from common import cargo

if __name__ == "__main__":
    cargo(*sys.argv[1:])
