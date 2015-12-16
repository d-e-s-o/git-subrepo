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
  def addAndCheck(self, prefix):
    """Add a subrepo to another directory and check for correct file contents."""
    with GitRepository() as lib,\
         GitRepository() as app:
      write(lib, "test.hpp", data="int test() { return 42; }")
      lib.add("test.hpp")
      lib.commit()

      app.remote("add", "--fetch", "lib", lib.path())
      app.subrepo("add", "lib", prefix, "master")

      # Create an additional non-subrepo commit in the application.
      write(app, "main.c", data="#include \"test.hpp\"")
      app.add("main.c")
      app.commit()

      self.assertEqual(read(app, prefix, "test.hpp"), read(lib, "test.hpp"))


  def testAdd(self):
    """Verify that we can add a subrepo into another repository."""
    for prefix in ("lib", join("src", "lib")):
      self.addAndCheck(prefix)


  def testUpdate(self):
    """Verify that subrepos can be updated properly."""
    with GitRepository() as r1,\
         GitRepository() as r2:
      write(r1, "text.dat", data="test42")
      r1.add("text.dat")
      r1.commit()

      r2.remote("add", "--fetch", "text", r1.path())
      r2.subrepo("add", "text", "text", "master")

      self.assertEqual(read(r2, "text", "text.dat"), "test42")

      # Make some changes to r1 and then update it.
      write(r1, "text.dat", data="test41")
      r1.add("text.dat")
      write(r1, "text2.dat", data="empty")
      r1.add("text2.dat")
      r1.commit()

      r2.fetch("text")
      r2.subrepo("update", "text", "text", "master")

      self.assertEqual(read(r2, "text", "text.dat"), "test41")
      self.assertEqual(read(r2, "text", "text2.dat"), "empty")


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
      r2.subrepo("add", "py", join("src", "lib"), sha1)

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
        app.subrepo("add", "lib", "lib", "master")
      finally:
        chdir(cwd)

      self.assertTrue(exists(app.path("src", "lib", "lib.h")))


if __name__ == "__main__":
  main()
