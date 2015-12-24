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

"""Test for the git repository Python wrapper."""

from deso.execute import (
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
)
from os.path import (
  join,
)
from unittest import (
  main,
  TestCase,
)


GIT = findCommand("git")


class TestRepository(TestCase):
  """Tests for the Repository class."""
  def testAddCommitReset(self):
    """Test the add, commit, and reset functionality."""
    with Repository(GIT) as repo:
      write(repo, "file.dat", data="content")
      repo.add("file.dat")
      repo.commit()

      self.assertEqual(read(repo, "file.dat"), "content")

      write(repo, "file.dat", data="empty")
      self.assertEqual(read(repo, "file.dat"), "empty")

      repo.reset("HEAD", "--hard")
      self.assertEqual(read(repo, "file.dat"), "content")


  def testRemote(self):
    """Test remote repository add and fetch."""
    with Repository(GIT) as lib,\
         Repository(GIT) as app:
      write(lib, "lib.py", data="# lib.py")
      lib.add("lib.py")
      lib.commit()

      app.remote("add", "--fetch", "lib", lib.path())
      app.checkout("lib/master")

      self.assertEqual(read(app, "lib.py"), read(lib, "lib.py"))

      # Create another commit in the library.
      write(lib, "other.dat", data="something else")
      lib.add("other.dat")
      lib.commit()

      app.fetch("lib")
      app.checkout("lib/master")

      self.assertEqual(read(app, "lib.py"), read(lib, "lib.py"))
      self.assertEqual(read(app, "other.dat"), read(lib, "other.dat"))


  def testOutput(self):
    """Verify that we can retrieve a command's standard output contents."""
    with Repository(GIT) as foo:
      write(foo, "foo.c", data="// foo.c")
      foo.add("foo.c")
      foo.commit()

      # We also verify here that we can invoke a git command containing
      # a dash (rev-parse in this case).
      sha1, _ = foo.revParse("HEAD", stdout=b"")
      self.assertRegex(sha1[:-1].decode("utf-8"), "[0-9a-f]{40}")


  def testChdir(self):
    """Verify that we do not change the working directory if already in the git repo."""
    with Repository(GIT) as foo:
      cwd = getcwd()
      dir_ = foo.path("test")

      mkdir(dir_)
      write(foo, join(dir_, "test_file"), data="data")

      chdir(dir_)
      try:
        # Add a path relative to the current working directory.
        foo.add("test_file")
        foo.commit()
        self.assertEqual(getcwd(), dir_)
      finally:
        chdir(cwd)


if __name__ == "__main__":
  main()
