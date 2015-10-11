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

from deso.git.repo import (
  read,
  Repository,
  write,
)
from unittest import (
  main,
  TestCase,
)


GIT = "git"


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


if __name__ == "__main__":
  main()
