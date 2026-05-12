import os
import subprocess
import sys

print(f"Installing pandas into CASA Python: {sys.executable}")
subprocess.run([sys.executable, "-m", "pip", "install", "--user", "pandas"], check=True)

user_site = os.path.expanduser(
    f"~/.local/lib/python{sys.version_info.major}.{sys.version_info.minor}/site-packages"
)
if user_site not in sys.path:
    sys.path.insert(0, user_site)

import pandas
print(f"Imported pandas {pandas.__version__}")
