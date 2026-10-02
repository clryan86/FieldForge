"""PyInstaller GUI entry point, intentionally distinct from the console helper."""

from fieldforge.launcher import main

if __name__ == "__main__":
    raise SystemExit(main())
