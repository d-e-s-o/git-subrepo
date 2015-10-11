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

from deso.git.repo import (
  read,
  Repository,
  write,
)
from os import (
  pardir,
)
from os.path import (
  dirname,
  join,
  realpath,
)
from shutil import (
  which,
)
from subprocess import (
  check_call,
  DEVNULL,
)
from sys import (
  executable,
)
from unittest import (
  main,
  SkipTest,
  TestCase,
)


GIT = "git"
GIT_SUBREPO = realpath(join(dirname(__file__), pardir, "git-subrepo.py"))


class GitRepository(Repository):
  """A git repository with subrepo support."""
  def __init__(self):
    """Initialize the git repository."""
    super().__init__(GIT)


  @Repository.unsetHome
  @Repository.autoChangeDir
  def subrepo(self, *args):
    """Invoke a git-subrepo command."""
    check_call([executable, GIT_SUBREPO] + list(args), stdout=DEVNULL)


def setUpModule():
  """Setup function invoked when loading the module."""
  if which(GIT) is None:
    raise SkipTest("%s command not found on system" % GIT)


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


if __name__ == "__main__":
  main()
