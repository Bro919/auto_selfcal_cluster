import sys
import subprocess

# install pandas using casa's python
cmd = ["/home/casa/packages/RHEL7/release/casa-6.6.4-34-py3.8.el8/lib/py/bin/python3.8", "-m", "pip", "install", "pandas"]
subprocess.run(cmd)

# append path
sys.path.append('/lustre/aoc/observers/nm-14416/.local/lib/python3.8/site-packages')

# import pandas
import pandas
