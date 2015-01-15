# -*- mode: python -*-
from path_helpers import path
import pygtkhelpers
import flatland
import matplotlib
import opencv_helpers
import pygst_utils
import pygst_utils_windows_server
import pygst
pygst.require('0.10')
import gst

try:
    import pymunk
    chipmunk_path = path(pymunk.__file__).parent.joinpath('chipmunk.dll')
    if not chipmunk_path.isfile():
        chipmunk_path = None
except ImportError:
    chipmunk_path = None
    print 'Could not import pymunk'

import zmq

extra_py = []
a = Analysis([os.path.join(HOMEPATH,'support\\_mountzlib.py'),
            os.path.join(HOMEPATH,'support\\useUnicode.py'),
            'microdrop\\microdrop.py'] + extra_py,
            excludes=['opencv_helpers', 'flatland', 'pygtkhelpers', 'pygst_utils',
                    'pygst_utils_windows_server', 'gst', ])

for mod in [gst, flatland, pygtkhelpers, pygst_utils, pygst_utils_windows_server, opencv_helpers]:
    mod_path = path(mod.__file__).parent
    a.datas += [(str(mod_path.parent.relpathto(p)), str(p.abspath()), 'DATA')\
            for p in mod_path.walkfiles(ignore=[r'\.git', r'site_scons',
                    r'.*\.pyc'])]

# Copy matplotlib mpl-data files to dist directory.
matplotlib_path = path(matplotlib.__file__).parent
a.datas += [(str(matplotlib_path.relpathto(p)), str(p.abspath()), 'DATA')\
        for p in matplotlib_path.joinpath('mpl-data').walkfiles(ignore=[r'\.git', r'site_scons', r'.*\.pyc'])]


zmq_dll_path = path(zmq.__file__).parent.joinpath('libzmq.dll')
if not zmq_dll_path.isfile():
    raise IOError, 'Cannot find zmq DLL: %s' % zmq_dll_path

a.datas += [(zmq_dll_path.name, str(zmq_dll_path), 'DATA')]

if chipmunk_path:
    print 'adding %s to data' % chipmunk_path
    a.datas += [(chipmunk_path.name, str(chipmunk_path), 'DATA')]
open_cv_glade_path = path(opencv_helpers.__file__).parent.joinpath('glade')
a.datas += [(str(open_cv_glade_path.parent.relpathto(p)), str(p.abspath()),
        'DATA') for p in open_cv_glade_path.walkfiles(ignore=[r'site_scons',
                                                               r'.*\.pyc'])]
a.datas += [(str(path('microdrop').relpathto(p)), str(p.abspath()), 'DATA')\
            for p in path('microdrop\\gui').walkfiles('*.glade')]
a.datas += [(str(path('microdrop').relpathto(p)), str(p.abspath()), 'DATA')\
            for p in path('microdrop').joinpath('utility', 'gui').walkfiles('*.glade')]
a.datas += [(str(path('microdrop').relpathto(p)), str(p.abspath()), 'DATA')\
            for p in path('microdrop\\plugins')\
                    .walkfiles(ignore=[r'site_scons', r'.*\.pyc'])]
a.datas += [(str(path('microdrop').relpathto(p)), str(p.abspath()), 'DATA')\
            for p in path('microdrop\\devices').walkfiles()]
a.datas += [(str(path('microdrop').relpathto(p)), str(p.abspath()), 'DATA')\
            for p in path('microdrop\\etc').walkfiles()]
a.datas += [(str(path('microdrop').relpathto(p)), str(p.abspath()), 'DATA')\
            for p in path('microdrop\\share').walkfiles()]
a.datas += [(str(path('microdrop').relpathto(p)), str(p.abspath()), 'DATA')\
            for p in path('microdrop\\support').walkfiles()]
a.datas += [(path('version.txt'),
            path('microdrop\\version.txt').abspath(),
            'DATA')]

pyz = PYZ(a.pure)
exe = EXE(pyz,
            a.scripts,
            exclude_binaries=True,
            name=os.path.join('build\\pyi.win32\\microdrop', 'microdrop.exe'),
            debug=True,
            strip=False,
            upx=True,
            console=True,
            icon='microdrop.ico')
coll = COLLECT(exe,
                a.datas,
                a.binaries,
                a.zipfiles,
                upx=True,
                name=os.path.join('dist', 'microdrop'))
