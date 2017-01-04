# testUtil.py

#/***************************************************************************
# *   Copyright (C) 2016 Daniel Mueller (deso@posteo.net)                   *
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

"""Tests for the utility functionality."""

from deso.execute import (
  isExecutable,
)
from os import (
  fchmod,
  fstat,
  unlink,
  symlink,
)
from os.path import (
  basename,
  join,
)
from stat import (
  S_IXGRP,
  S_IXOTH,
  S_IXUSR,
)
from tempfile import (
  TemporaryDirectory,
  NamedTemporaryFile,
)
from unittest import (
  TestCase,
  main,
)


class TestExecute(TestCase):
  """A test case for utility functionality."""
  def testExecutableCheck(self):
    """Verify that the 'isExecutable' function works as expected."""
    with NamedTemporaryFile() as f:
      fd = f.file.fileno()
      mode = fstat(fd).st_mode

      # Make sure the the file has no execution rights. Depending on the
      # default file mode mask we could end up with an executable file
      # by default.
      fchmod(fd, mode & ~(S_IXUSR | S_IXGRP | S_IXOTH))
      self.assertFalse(isExecutable(f.name))

      fchmod(fd, S_IXUSR)
      self.assertTrue(isExecutable(f.name))

      # Also verify that a symbolic link pointing to an executable file
      # is reported correctly.
      with TemporaryDirectory() as d:
        link = join(d, basename(f.name))
        symlink(f.name, link)

        self.assertTrue(isExecutable(link))


if __name__ == "__main__":
  main()
