"""PyInstaller entry point (the package's __main__ uses relative imports, so the bundle needs a plain script)."""
import sys

from stemforge.app.window import main

sys.exit(main())
