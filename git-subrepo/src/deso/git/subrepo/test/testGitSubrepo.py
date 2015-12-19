#!/usr/bin/env python

#/***************************************************************************
# *   Copyright (C) 2015 Daniel Mueller (deso@posteo.net)                   *
# *                                                                         *
# *   This program is free software: you can redistribute it and/or modify  *
# *   it under the terms of the GNU General Public License as published by  *
# *   the Free Software Foundation, either version 3 of the License, or     *
# *   (at your option) any later version.                                   *
# *                                                                         *
# *   This program is distributed in the hope that it will be useful,       *
# *   but WITHOUT ANY WARRANTY; without even the implied warranty of        *
# *   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the         *
# *   GNU General Public License for more details.                          *
# *                                                                         *
# *   You should have received a copy of the GNU General Public License     *
# *   along with this program.  If not, see <http://www.gnu.org/licenses/>. *
# ***************************************************************************/

"""Various tests for the git-subrepo functionality."""

from deso.execute import (
  execute,
  findCommand,
)
from deso.git.repo import (
  read,
  Repository,
  write,
)
from os import (
  chdir,
  getcwd,
  mkdir,
  pardir,
)
from os.path import (
  dirname,
  exists,
  join,
  realpath,
)
from random import (
  randint,
)
from sys import (
  executable,
)
from unittest import (
  main,
  TestCase,
)


GIT = findCommand("git")
GIT_SUBREPO = realpath(join(dirname(__file__), pardir, "git-subrepo.py"))


class GitRepository(Repository):
  """A git repository with subrepo support."""
  def __init__(self):
    """Initialize the git repository."""
    super().__init__(GIT)


  @Repository.unsetHome
  @Repository.autoChangeDir
  def revParse(self, *args):
    """Invoke git-rev-parse with a set of arguments."""
    # We need to remove the trailing new line symbol here.
    # Unfortunately, there is no --null option (as supported by
    # git-config) that causes a NULL terminated string to be emitted.
    out, _ = execute(GIT, "rev-parse", *args, stdout=b"")
    return out[:-1].decode("utf-8")


  @Repository.unsetHome
  @Repository.autoChangeDir
  def subrepo(self, *args):
    """Invoke a git-subrepo command."""
    execute(executable, GIT_SUBREPO, *args)


class TestGitSubrepo(TestCase):
  """Tests for the git-subrepo script."""
  def addUpdateAndCheck(self, prefix, multi_commit=False):
    """Add a subrepo to another directory and check for correct file contents."""
    with GitRepository() as lib1,\
         GitRepository() as lib2,\
         GitRepository() as app:
      write(lib1, "test.hpp", data="int test() { return 42; }")
      lib1.add("test.hpp")

      # We want to see if we can add single and multi commit remote
      # repositories as the initial commit equally well. So create an
      # intermediate commit here if desired.
      if multi_commit:
        lib1.commit()

      # Also verify that we can properly import binary data.
      write(lib1, "test.bin", data="".join(chr(randint(0, 255)) for _ in range(512)))
      lib1.add("test.bin")
      lib1.commit()

      app.remote("add", "--fetch", "lib1", lib1.path())
      app.subrepo("import", "lib1", prefix, "master")

      # Create an additional non-subrepo commit in the application.
      write(app, "main.c", data="#include \"test.hpp\"")
      app.add("main.c")
      app.commit()

      # Add a second subrepo. This time unconditionally in the root
      # directory.
      write(lib2, "foo42.py", data="def main(): pass")
      lib2.add("foo42.py")

      mkdir(lib2.path("lib2"))
      write(lib2, "lib2", "lib2.py", data="import sys")
      lib2.add(lib2.path("lib2", "lib2.py"))
      lib2.commit()

      app.remote("add", "--fetch", "lib2", lib2.path())
      app.subrepo("import", "lib2", ".", "master")

      self.assertEqual(read(app, prefix, "test.hpp"), read(lib1, "test.hpp"))
      self.assertEqual(read(app, prefix, "test.bin"), read(lib1, "test.bin"))
      self.assertEqual(read(app, "foo42.py"), read(lib2, "foo42.py"))
      self.assertEqual(read(app, "lib2", "lib2.py"), read(lib2, "lib2", "lib2.py"))

      # Now update 'lib1' and then update the subrepo referencing it in
      # 'app'.
      write(lib1, "test.hpp", data="int test() { return 1; }")
      lib1.add("test.hpp")
      write(lib1, "test.cpp", data="#error Not Compilable")
      lib1.add("test.cpp")
      lib1.commit()

      app.fetch("lib1")
      app.subrepo("import", "lib1", prefix, "master")

      self.assertEqual(read(app, prefix, "test.hpp"), read(lib1, "test.hpp"))
      self.assertEqual(read(app, prefix, "test.cpp"), read(lib1, "test.cpp"))
      self.assertEqual(read(app, "foo42.py"), read(lib2, "foo42.py"))
      self.assertEqual(read(app, "lib2", "lib2.py"), read(lib2, "lib2", "lib2.py"))


  def testImport(self):
    """Verify that we can import subrepos into another repository."""
    for prefix in (".", "lib", join("src", "lib")):
      for multi_commit in (False, True):
        self.addUpdateAndCheck(prefix, multi_commit=multi_commit)


  def testUpdate(self):
    """Verify that subrepos can be updated properly."""
    with GitRepository() as r1,\
         GitRepository() as r2:
      write(r1, "text.dat", data="test42")
      r1.add("text.dat")
      r1.commit()

      r2.remote("add", "--fetch", "text", r1.path())
      r2.subrepo("import", "text", "text", "master")

      self.assertEqual(read(r2, "text", "text.dat"), "test42")

      # Make some changes to r1 and then update it.
      write(r1, "text.dat", data="test41")
      r1.add("text.dat")
      write(r1, "text2.dat", data="empty")
      r1.add("text2.dat")
      r1.commit()

      r2.fetch("text")
      r2.subrepo("import", "text", "text", "master")

      self.assertEqual(read(r2, "text", "text.dat"), "test41")
      self.assertEqual(read(r2, "text", "text2.dat"), "empty")

      # Now also "downdate".
      r2.subrepo("import", "text", "text", "master^")

      self.assertEqual(read(r2, "text", "text.dat"), "test42")

      with self.assertRaises(FileNotFoundError):
        read(r2, "text", "text2.dat")


  def testSha1HashResolution(self):
    """Verify that git-subrepo is able to handle supplied SHA1 hashes correctly."""
    with GitRepository() as r1,\
         GitRepository() as r2:
      content = "def run(): print('hello!')"

      write(r1, "main.py", data=content)
      r1.add("main.py")
      r1.commit()
      sha1 = r1.revParse("HEAD")

      r2.remote("add", "--fetch", "py", r1.path())
      r2.subrepo("import", "py", join("src", "lib"), sha1)

      self.assertEqual(read(r2, "src", "lib", "main.py"), content)


  def testRelativePrefixHandling(self):
    """Verify that subrepo prefixes are treated relative to the current directory."""
    with GitRepository() as lib,\
         GitRepository() as app:
      cwd = getcwd()

      write(lib, "lib.h", data="/* Lib */")
      lib.add("lib.h")
      lib.commit()
      app.remote("add", "--fetch", "lib", lib.path())

      # In order to test handling of relative paths we change into a sub
      # directory. All operations should then work relative to this sub
      # directory.
      mkdir(app.path("src"))
      chdir(app.path("src"))
      try:
        app.subrepo("import", "lib", "lib", "master")
      finally:
        chdir(cwd)

      self.assertTrue(exists(app.path("src", "lib", "lib.h")))


  def testAddEqualRepos(self):
    """Verify that we can merge two similar subrepos pulled in as dependencies."""
    with GitRepository() as lib1,\
         GitRepository() as lib2,\
         GitRepository() as lib3,\
         GitRepository() as app:
      mkdir(lib1.path("lib1"))
      write(lib1, "lib1", "lib1.py", data="pass")
      lib1.add(lib1.path("lib1", "lib1.py"))
      lib1.commit()

      lib2.remote("add", "--fetch", "lib1", lib1.path())
      lib2.subrepo("import", "lib1", ".", "master")

      mkdir(lib2.path("lib2"))
      write(lib2, "lib2", "lib2.py", data="def foo(): pass")
      lib2.add(lib2.path("lib2", "lib2.py"))
      lib2.commit()

      mkdir(lib3.path("lib3"))
      write(lib3, "lib3", "lib3.py", data="def bar(): pass")
      lib3.add(lib3.path("lib3", "lib3.py"))
      lib3.commit()

      lib3.remote("add", "--fetch", "lib1", lib1.path())
      lib3.subrepo("import", "lib1", ".", "master")

      self.assertEqual(read(lib2, "lib1", "lib1.py"), read(lib1, "lib1", "lib1.py"))
      self.assertEqual(read(lib3, "lib1", "lib1.py"), read(lib1, "lib1", "lib1.py"))

      app.remote("add", "--fetch", "lib2", lib2.path())
      app.remote("add", "--fetch", "lib3", lib3.path())
      app.subrepo("import", "lib2", ".", "master")
      app.subrepo("import", "lib3", ".", "master")

      self.assertEqual(read(app, "lib1", "lib1.py"), read(lib1, "lib1", "lib1.py"))
      self.assertEqual(read(app, "lib2", "lib2.py"), read(lib2, "lib2", "lib2.py"))
      self.assertEqual(read(app, "lib3", "lib3.py"), read(lib3, "lib3", "lib3.py"))

      # Now create some more commits in each of the repositories and
      # update the imports.
      write(lib1, "lib1", "lib1.py", data="def baz(): pass")
      lib1.add(lib1.path("lib1", "lib1.py"))
      lib1.commit()

      lib2.fetch("lib1")
      lib2.subrepo("import", "lib1", ".", "master")

      self.assertEqual(read(lib2, "lib1", "lib1.py"), read(lib1, "lib1", "lib1.py"))

      write(lib2, "lib2", "lib2.py", data="pass")
      lib2.add(lib2.path("lib2", "lib2.py"))
      lib2.commit()

      write(lib3, "lib3", "lib3.py", data="def foobar(): pass")
      lib3.add(lib3.path("lib3", "lib3.py"))
      lib3.commit()

      lib3.fetch("lib1")
      lib3.subrepo("import", "lib1", ".", "master")

      app.fetch("lib2")
      app.fetch("lib3")
      app.subrepo("import", "lib2", ".", "master")
      app.subrepo("import", "lib3", ".", "master")

      self.assertEqual(read(app, "lib1", "lib1.py"), read(lib1, "lib1", "lib1.py"))
      self.assertEqual(read(app, "lib2", "lib2.py"), read(lib2, "lib2", "lib2.py"))
      self.assertEqual(read(app, "lib3", "lib3.py"), read(lib3, "lib3", "lib3.py"))


if __name__ == "__main__":
  main()
