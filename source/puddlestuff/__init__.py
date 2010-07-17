# -*- coding: utf-8 -*-
import subprocess, re
from os.path import dirname
version_string = '0.9.3'
version = (0,9,3)

try:
    filedir = dirname(dirname(__file__))
    info = subprocess.Popen(['svn', 'info', filedir], 
        stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    revision = int(re.search(u'Revision: (\d+)', 
        info.stdout.read()).groups()[0])
    print u'puddletag Version: %s, Revision: %s' % (version_string, revision)
except (EnvironmentError, AttributeError):
    revision = None