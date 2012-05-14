#
# importers.py
#
# Demonstration subclasses of imputil.Importer
#

# There should be consideration for the imports below if it is desirable
# to have "all" modules be imported through the imputil system.

# these are C extensions
import sys
import imp
import struct
import marshal

# these are .py modules
import imputil
import os

import pyjd

######################################################################

_TupleType = type(())
_StringType = type('')

######################################################################

# byte-compiled file suffic character
_suffix_char = __debug__ and 'c' or 'o'

# byte-compiled file suffix
_suffix = '.py' + _suffix_char

# the C_EXTENSION suffixes
_c_suffixes = filter(lambda x: x[2] == imp.C_EXTENSION, imp.get_suffixes())

from modcompile import PlatformParser, Module

pp = PlatformParser(verbose=False)
pp.platform =  pyjd.engine
parser = PlatformParser(verbose=False, chain_plat=pp)

def _timestamp(pathname):
    "Return the file modification time as a Long."
    try:
        s = os.stat(pathname)
    except OSError:
        return None
    return long(s[8])

def _fs_import(dir, modname, fqname):
    "Fetch a module from the filesystem."

    pathname = os.path.join(dir, modname)
    if os.path.isdir(pathname):
        values = { '__pkgdir__' : pathname, '__path__' : [ pathname ] }
        ispkg = 1
        pathname = os.path.join(pathname, '__init__')
    else:
        values = { }
        ispkg = 0

        # look for dynload modules
        for desc in _c_suffixes:
            fname = pathname + desc[0]
            try:
                fp = open(fname, desc[1])
            except IOError:
                pass
            else:
                module = imp.load_module(fqname, fp, fname, desc)
                values['__file__'] = fname
                return 0, module, values

    filename = pathname + '.py'
    filenamec = pathname + _suffix
    t_py = _timestamp(filename)
    t_pyc = _timestamp(filenamec)
    #print "timestamp", filename, t_py, t_pyc
    if t_py is None and t_pyc is None:
        return None
    code = None
    out_t_py = t_py
    out_filename = filename
    # XXX TODO - read .pyc from platform-specific locations...
    platform_file = parser.checkOverridePlatformFile(filename)
    #print "check platform file", filename, platform_file
    if platform_file:
        platform_filec = platform_file[:-3] + _suffix
        t_p_py = _timestamp(platform_file)
        t_p_pyc = _timestamp(platform_filec)
        #print "platform file", platform_file, platform_filec, t_p_py, t_p_pyc
        if t_p_py is not None or t_p_pyc is not None:
            # platform file exists: must check that instead.
            ok = True
            if t_py is not None and t_pyc is not None and t_py > t_pyc:
                # .py exists, .pyc exists, .py is newer than pyc: nope
                ok = False
            if t_py is not None and t_p_py is not None and t_py > t_p_py:
                # .py exists, platform.py exists, .py is newer than pyc: nope
                ok = False
            if t_py is not None and t_p_pyc is not None and t_py > t_p_pyc:
                # .py exists, platform.pyc exists, .py is newer than pyc: nope
                ok = False

            #print "platform file ok", platform_file, platform_filec
            if ok and \
                (t_p_py is None or (t_p_pyc is not None and t_p_pyc >= t_p_py)):
                f = open(platform_filec, 'rb')
                magic = f.read(4)
                #print "reading platform file", platform_filec, repr(magic), repr(imp.get_magic())
                if magic == imp.get_magic():
                    t = struct.unpack('<I', f.read(4))[0]
                    #print "time?", platform_filec, t, t_p_py
                    if t == t_p_py:
                        code = marshal.load(f)
                f.close()

    if code is None and \
       (t_py is None or (t_pyc is not None and t_pyc >= t_py)):
        f = open(filenamec, 'rb')
        magic = f.read(4)
        if magic == imp.get_magic():
            t = struct.unpack('<I', f.read(4))[0]
            if t == t_py:
                code = marshal.load(f)
        f.close()

    if code is None:
        filename = pathname + '.py'
        "compiling", filename
        mod, filename = parser.parseModule(modname, filename)
        code = Module(mod, filename)
        code.compile()
        code = code.getCode()

        if platform_file and t_p_py:
            out_t_py = t_p_py
            out_filename = platform_file

        # try to cache the compiled code
        try:
            f = open(out_filename + _suffix_char, 'wb')
        except IOError, e:
            #print "write cache error", out_filename + _suffix_char, e
            pass
        else:
            #print "writing cache to ", out_filename + _suffix_char
            f.write('\0\0\0\0')
            f.write(struct.pack('<I', out_t_py))
            marshal.dump(code, f)
            f.flush()
            f.seek(0, 0)
            f.write(imp.get_magic())
            f.close()

    values['__file__'] = filename
    return ispkg, code, values

######################################################################
#
# Simple function-based importer
#
class FuncImporter(imputil.Importer):
    "Importer subclass to delegate to a function rather than method overrides."
    def __init__(self, func):
        self.func = func
    def get_code(self, parent, modname, fqname):
        return self.func(parent, modname, fqname)

def install_with(func):
    FuncImporter(func).install()


######################################################################
#
# Base class for archive-based importing
#
class PackageArchiveImporter(imputil.Importer):
    """Importer subclass to import from (file) archives.

    This Importer handles imports of the style <archive>.<subfile>, where
    <archive> can be located using a subclass-specific mechanism and the
    <subfile> is found in the archive using a subclass-specific mechanism.

    This class defines two hooks for subclasses: one to locate an archive
    (and possibly return some context for future subfile lookups), and one
    to locate subfiles.
    """

    def get_code(self, parent, modname, fqname):
        if parent:
            # the Importer._finish_import logic ensures that we handle imports
            # under the top level module (package / archive).
            assert parent.__importer__ == self

            # if a parent "package" is provided, then we are importing a
            # sub-file from the archive.
            result = self.get_subfile(parent.__archive__, modname)
            if result is None:
                return None
            if isinstance(result, _TupleType):
                assert len(result) == 2
                return (0,) + result
            return 0, result, {}

        # no parent was provided, so the archive should exist somewhere on the
        # default "path".
        archive = self.get_archive(modname)
        if archive is None:
            return None
        return 1, "", {'__archive__':archive}

    def get_archive(self, modname):
        """Get an archive of modules.

        This method should locate an archive and return a value which can be
        used by get_subfile to load modules from it. The value may be a simple
        pathname, an open file, or a complex object that caches information
        for future imports.

        Return None if the archive was not found.
        """
        raise RuntimeError, "get_archive not implemented"

    def get_subfile(self, archive, modname):
        """Get code from a subfile in the specified archive.

        Given the specified archive (as returned by get_archive()), locate
        and return a code object for the specified module name.

        A 2-tuple may be returned, consisting of a code object and a dict
        of name/values to place into the target module.

        Return None if the subfile was not found.
        """
        raise RuntimeError, "get_subfile not implemented"


class PackageArchive(PackageArchiveImporter):
    "PackageArchiveImporter subclass that refers to a specific archive."

    def __init__(self, modname, archive_pathname):
        self.__modname = modname
        self.__path = archive_pathname

    def get_archive(self, modname):
        if modname == self.__modname:
            return self.__path
        return None

    # get_subfile is passed the full pathname of the archive


######################################################################
#
# Emulate the standard directory-based import mechanism
#
class DirectoryImporter(imputil.Importer):
    "Importer subclass to emulate the standard importer."

    def __init__(self, dir):
        self.dir = dir

    def get_code(self, parent, modname, fqname):
        if parent:
            dir = parent.__pkgdir__
        else:
            dir = self.dir

        # Return the module (and other info) if found in the specified
        # directory. Otherwise, return None.
        return _fs_import(dir, modname, fqname)

    def __repr__(self):
        return '<%s.%s for "%s" at 0x%x>' % (self.__class__.__module__,
                                             self.__class__.__name__,
                                             self.dir,
                                             id(self))


######################################################################
#
# Emulate the standard path-style import mechanism
#
class PathImporter(imputil.Importer):
    def __init__(self, path=sys.path):
        self.path = path

    def get_code(self, parent, modname, fqname):
        #print "PathImporter.get_code", parent, modname, fqname
        if parent:
            # we are looking for a module inside of a specific package
            return _fs_import(parent.__pkgdir__, modname, fqname)

        # scan sys.path, looking for the requested module
        for dir in self.path:
            if isinstance(dir, _StringType):
                result = _fs_import(dir, modname, fqname)
                if result:
                    return result

        # not found
        return None

######################################################################

def _test_dir():
    "Debug/test function to create DirectoryImporters from sys.path."
    imputil.ImportManager().install()
    path = sys.path[:]
    path.reverse()
    for d in path:
        sys.path.insert(0, DirectoryImporter(d))
    sys.path.insert(0, imputil.BuiltinImporter())

def _test_revamp():
    "Debug/test function for the revamped import system."
    imputil.ImportManager().install()
    sys.path.insert(0, PathImporter())
    sys.path.insert(0, imputil.BuiltinImporter())
