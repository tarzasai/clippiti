# PyInstaller entry point. Importing the package's main as a package attribute
# keeps relative imports inside clippiti working in the frozen build.
from clippiti.__main__ import main

if __name__ == "__main__":
  main()
