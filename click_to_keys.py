"""Entry-point shim. The bridge lives in the src/ package; run this or
`python -m src.main`."""

from src.main import main_cli

if __name__ == "__main__":
    main_cli()
