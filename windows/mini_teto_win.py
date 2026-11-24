"""PyInstaller entry point: the same command line as on Linux (mini-teto.exe feed, say hi, quit ...)."""
import sys

from mini_teto.app import main

if __name__ == "__main__":
    sys.exit(main())
