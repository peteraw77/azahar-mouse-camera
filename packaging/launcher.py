"""Entry point for the packaged exe. PyInstaller needs a script to start from."""

import sys

from mousecam.__main__ import console_main

sys.exit(console_main())
