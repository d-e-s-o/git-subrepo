# repository.py

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

"""Git repository functionality for Python."""

from deso.execute import (
  execute,
)
from os import (
  chdir,
  environ,
  getcwd,
)
from os.path import (
  commonprefix,
  join,
)
from re import (
  sub,
)
from tempfile import (
  TemporaryDirectory,
)


def write(repo, *components, data=None, truncate=True):
  """Write data into a file in the repository."""
  mode = "w+" if truncate else "a"
  with open(repo.path(*components), mode) as f:
    if truncate:
      f.truncate()
    f.write(data)


def read(repo, *components):
  """Read data from a file in the repository."""
  with open(repo.path(*components), "r") as f:
    return f.read()


class PathMixin:
  """A mixin inheriting the PATH environment variable to all executed git commands."""
  @staticmethod
  def inheritEnv(env):
    """Inherit the PATH environment variable into the given environment."""
    env["PATH"] = environ["PATH"]


  def git(self, *args, **kwargs):
    """Run a git command, taking care to inherit the PATH environment variable."""
    env = kwargs.setdefault("env", {})
    PathMixin.inheritEnv(env)

    return super().git(*args, **kwargs)


class PythonMixin:
  """A mixin inheriting PYTHON* environment variables to all executed git commands."""
  @staticmethod
  def inheritEnv(env):
    """Inherit all PYTHON* environment variables into the given environment."""
    env.update(filter(lambda x: x[0].startswith("PYTHON"), environ.items()))


  def git(self, *args, **kwargs):
    """Run a git command, taking care to inherit all PYTHON* environment variables."""
    env = kwargs.setdefault("env", {})
    PythonMixin.inheritEnv(env)

    return super().git(*args, **kwargs)


class Repository:
  """Objects of this class represent a git repository."""
  def __init__(self, git):
    """Create a new Repository object."""
    self._git = git
    self._directory = TemporaryDirectory()
    self._commit_nr = 1


  def autoChangeDir(function):
    """Decorator automatically changing the current working directory."""
    def changeDir(self, *args, **kwargs):
      """Change the current directory, invoke the decorated function, and revert the change."""
      cwd = getcwd()
      git_dir = self._directory.name

      # We only want to change the current working directory into the
      # git repository if we are not already *somewhere* in the git
      # repository. This behavior is useful for testing correct
      # treatment of relative paths.
      if commonprefix([cwd, git_dir]) != git_dir:
        chdir(git_dir)
        try:
          return function(self, *args, **kwargs)
        finally:
          chdir(cwd)
      else:
        return function(self, *args, **kwargs)

    return changeDir


  @autoChangeDir
  def git(self, *args, **kwargs):
    """Run a git command."""
    # If not requested otherwise we always start git with an empty
    # environment. We do not want any of the global/user-specific
    # configuration to have effect on the commands.
    kwargs.setdefault("env", {})

    return execute(self._git, *args, **kwargs)


  def __getattr__(self, name):
    """Invoke a git command."""
    def replace(match):
      """Replace an upper case char with a dash followed by a lower case version of it."""
      s, = match.groups()
      return "-%s" % s.lower()

    command = sub("([A-Z])", replace, name)
    return lambda *args, **kwargs: self.git(command, *args, **kwargs)


  def _init(self, *args, init_user=True, **kwargs):
    """Initialize a new repository."""
    self.init(*args, **kwargs)

    if init_user:
      self.config("user", "email", "you@example.com")
      self.config("user", "name", "Your Name")


  def commit(self, *args, **kwargs):
    """Create a commit of the staged files."""
    message = "commit #%d" % self._commit_nr
    out = self.git("commit", "--message", message, *args, **kwargs)
    self._commit_nr += 1
    return out


  def config(self, section, key, value, *args, **kwargs):
    """Set a configuration value in the local repository."""
    name = "%s.%s" % (section, key)
    value = "%s" % value
    return self.git("config", "--local", name, value, *args, **kwargs)


  def destroy(self):
    """Destroy the git repository."""
    # Cleanup the temporary directory, automatically deleting all the
    # content.
    self._directory.cleanup()


  def __enter__(self, *args, **kwargs):
    """The block enter handler returns an initialized Repository object."""
    self._init(*args, **kwargs)
    return self


  def __exit__(self, type_, value, traceback):
    """The block exit handler destroys the git repository."""
    self.destroy()


  def path(self, *components):
    """Form an absolute path by combining the given path components."""
    return join(self._directory.name, *components)
