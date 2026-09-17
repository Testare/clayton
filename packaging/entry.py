"""PyInstaller entry point.

A tiny top-level launcher so PyInstaller analyzes the ``app`` package by import
(``from app.main import main``) rather than running ``app/main.py`` as ``__main__``,
which would break its absolute ``from app...`` imports.
"""
from app.main import main

if __name__ == "__main__":
    main()
