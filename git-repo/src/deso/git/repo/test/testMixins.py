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
  ProcessError,
)
from deso.git.repo import (
  PathMixin,
  PythonMixin,
  Repository,
  write,
)
from os import (
  chmod,
  environ,
)
from sys import (
  executable,
)
from textwrap import (
  dedent,
)
from unittest import (
  main,
  SkipTest,
  TestCase,
)


GIT = findCommand("git")


class HookRepository(Repository):
  """A repository that employs a custom pre-commit hook."""
  def _init(self):
    """Initialize the repository and install the copyright hook."""
    super()._init()

    hook = self.path(".git", "hooks", "pre-commit")
    with open(hook, "w+") as f:
      content = dedent("""\
        #!{python}
        from os import environ
        print(environ)
        exit(0 if \"{env}\" in environ else 1)\
      """).format(python=executable, env=self._ENVIRON_TO_CHECK)

      f.write(content)
      # The hook script is required to be executable.
      chmod(f.fileno(), 0o755)


class InvalidRepository(HookRepository):
  """A repository performing a check for a non-existent environment variable."""
  _ENVIRON_TO_CHECK = "UNDEFINED"


class PathRepository(PathMixin, HookRepository):
  """A repository that inherits the PATH environment variable to all executed git commands."""
  _ENVIRON_TO_CHECK = "PATH"


class PythonRepository(PythonMixin, HookRepository):
  """A repository that inherits the PYTHONPATH environment variable to all executed git commands."""
  # There could be more PYTHON variables defined but we only check one.
  _ENVIRON_TO_CHECK = "PYTHONPATH"


class TestMixins(TestCase):
  """Tests for the different mixins."""
  def _doMixinTest(self, repo_class):
    """Create a repository of the given class and create a commit."""
    # We simply instantiate the repository and create a commit. The
    # pre-commit hook will be run and it will fail in case the desired
    # environment variable is not inherited.
    with repo_class(GIT) as repo:
      write(repo, "foo", data="data")
      repo.add("foo")
      repo.commit()


  def testInvalidMixin(self):
    """Verify that our environment variable checking logic works properly."""
    with self.assertRaises(ProcessError):
      self._doMixinTest(InvalidRepository)


  def testPathMixin(self):
    """Verify that when using PathMixin we inherit the PATH environment variable."""
    if "PATH" not in environ:
      raise SkipTest("PATH not in current environment.")

    self._doMixinTest(PathRepository)


  def testPythonMixin(self):
    """Verify that when using PythonMixin we inherit the PYTHONPATH environment variable."""
    if "PYTHONPATH" not in environ:
      raise SkipTest("PYTHONPATH not in current environment.")

    self._doMixinTest(PythonRepository)


if __name__ == "__main__":
  main()
