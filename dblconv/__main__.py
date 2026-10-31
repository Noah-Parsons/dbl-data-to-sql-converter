"""`python -m dblconv` with no arguments opens the window; with arguments it runs the
folder conversion from the command line (see dblconv.batch)."""
import sys


def main():
    if len(sys.argv) > 1:
        from .batch import main as cli
        cli()
    else:
        from .gui import main as gui
        gui()


if __name__ == "__main__":
    main()
