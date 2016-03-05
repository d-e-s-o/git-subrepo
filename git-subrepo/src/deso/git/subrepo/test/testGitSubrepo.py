#!/usr/bin/env python

#/***************************************************************************
# *   Copyright (C) 2015-2016 Daniel Mueller (deso@posteo.net)              *
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

from deso.cleanup import (
  defer,
)
from deso.execute import (
  execute,
  findCommand,
  ProcessError,
)
from deso.git.repo import (
  PathMixin,
  PythonMixin,
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
from tempfile import (
  TemporaryDirectory,
)
from unittest import (
  main,
  SkipTest,
  TestCase,
)


GIT = findCommand("git")
GIT_SUBREPO = realpath(join(dirname(__file__), pardir, "git-subrepo.py"))


def _subrepo(*args):
  """Invoke git-subrepo with the given arguments."""
  env = {}
  PathMixin.inheritEnv(env)
  PythonMixin.inheritEnv(env)

  execute(executable, GIT_SUBREPO, *args, env=env)


class GitRepository(PathMixin, PythonMixin, Repository):
  """A git repository with subrepo support."""
  def __init__(self):
    """Initialize the git repository."""
    super().__init__(GIT)


  def revParse(self, *args):
    """Invoke git-rev-parse with a set of arguments."""
    # We need to remove the trailing new line symbol here.
    # Unfortunately, there is no --null option (as supported by
    # git-config) that causes a NULL terminated string to be emitted.
    out, _ = self.git("rev-parse", *args, stdout=b"")
    return out[:-1].decode("utf-8")


  @Repository.autoChangeDir
  def subrepo(self, *args):
    """Invoke a git-subrepo command."""
    _subrepo(*args)


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

      self.assertEqual(read(app, "src", "lib", "lib.h"), read(lib, "lib.h"))

      # Now perform an "update" import, i.e., one where some data
      # already exists and we effectively just create an incremental
      # patch on top of that.
      write(lib, "lib.h", data="test")
      lib.add("lib.h")
      lib.commit()
      app.fetch("lib")

      chdir(app.path("src"))
      try:
        app.subrepo("import", "lib", "lib", "master")
      finally:
        chdir(cwd)

      self.assertEqual(read(app, "src", "lib", "lib.h"), read(lib, "lib.h"))


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


  def testImportSubrepoAtCurrentState(self):
    """Try importing a subrepo that is already at the desired state."""
    def doTest(prefix):
      """Perform the test by importing at the given prefix."""
      with GitRepository() as r1,\
           GitRepository() as r2:
        write(r1, "test.py", data="# test.py")
        r1.add("test.py")
        r1.commit()

        r2.remote("add", "--fetch", "test", r1.path())
        r2.subrepo("import", "test", prefix, "master")

        # Try importing the subrepo a second time, to the same state. This
        # invocation must fail.
        with self.assertRaisesRegex(ProcessError, r"No changes"):
          r2.subrepo("import", "test", prefix, "master")

    doTest(".")
    doTest("prefix")


  def testImportEmptySubrepo(self):
    """Try importing an empty subrepo."""
    def doTest(prefix):
      """Perform the test by importing at the given prefix."""
      with GitRepository() as r1,\
           GitRepository() as r2:
        r1.commit("--allow-empty")
        r2.remote("add", "--fetch", "r1", r1.path())

        with self.assertRaisesRegex(ProcessError, r"No changes"):
          r2.subrepo("import", "r1", prefix, "master")

    doTest("./")
    doTest("r1")


  def testInvocationOutsideOfRepository(self):
    """Verify that the program behaves as intended if invoked outside of a git repository."""
    def skipTestIfInGitRepo():
      """Skip the current test if we are in a git repository."""
      try:
        execute(GIT, "rev-parse", "--git-dir")
        raise SkipTest("Found a git repository above '%s'" % getcwd())
      except ProcessError:
        pass

    cwd = getcwd()
    # Check for the proper return message. We assume git-rev-parse
    # failed as that is the first command that is executed. Note that
    # the most important thing in the regular expression is the first
    # single quote sign. The problem is that the reported message in our
    # scenario does not begin with the git-rev-parse failure but with
    # the Python one. However, the actual git failure is reported in
    # single quotes.
    regex = r"'\[Status [0-9]+\] [^ ]*git rev-parse"

    with TemporaryDirectory() as dir_:
      with defer() as d:
        chdir(dir_)
        d.defer(chdir, cwd)

        # Although we are in a temporary directory depending on the
        # overall file system structure we might still have a git
        # repository somewhere above us that could be found. In such a
        # case we want to skip the test.
        skipTestIfInGitRepo()

        with self.assertRaisesRegex(ProcessError, regex):
          _subrepo("import", "repo", ".", "master")


  def testBacktraceOnError(self):
    """Verify that in case the --debug option is specified we get a backtrace."""
    with GitRepository() as repo:
      regex = r"Traceback \(most recent call last\)"
      with self.assertRaisesRegex(ProcessError, regex):
        repo.subrepo("import", "--debug", "foo", "bar/", "HEAD")


  def testErrorOnUncommittedConflictingChanges(self):
    """Check that we error out in case there are uncomitted conflicting changes in the tree."""
    def doTest(prefix, stage):
      """Perform the import test and verify that conflicting files are not overwritten."""
      with GitRepository() as other,\
           GitRepository() as this:
        if prefix != ".":
          mkdir(other.path(prefix))
          mkdir(this.path(prefix))

        write(other, "other.py", data="data")
        other.add(other.path("other.py"))
        other.commit()

        data = "other conflicting data"
        this.remote("add", "--fetch", "other", other.path())
        # Add a file into "this" repository that causes a conflict with
        # a file in "other".
        write(this, prefix, "other.py", data=data)
        if stage:
          this.add(this.path(prefix, "other.py"))
          regex = r"Your index contains uncommitted changes."
        else:
          regex = r"other.py: already exists in working directory"

        with self.assertRaisesRegex(ProcessError, regex):
          this.subrepo("import", "other", prefix, "master")

        # The conflicting file's contents should not have been touched.
        self.assertEqual(read(this, prefix, "other.py"), data)

    for stage in (False, True):
      doTest(".", stage)
      doTest("some-prefix", stage)


  def testCommitOwnershipVerification(self):
    """Check that commits not belonging to a given remote repository are flagged."""
    def addCommits(repo):
      """Create two commits in the given repository."""
      # Note that we need some variability in the content committed
      # otherwise the created SHA1 sums will be the same even between
      # different repositories (!).
      write(repo, "file1.txt", data="%s" % repr(repo))
      repo.add("file1.txt")
      repo.commit()
      sha1 = repo.revParse("HEAD")

      write(repo, "file2.txt", data="%s" % repr(repo))
      repo.add("file2.txt")
      repo.commit()
      sha2 = repo.revParse("HEAD")
      return [sha1, sha2]

    with GitRepository() as lib1,\
         GitRepository() as lib2,\
         GitRepository() as app:
      lib1_commits = addCommits(lib1)
      lib2_commits = addCommits(lib2)
      app_commits = addCommits(app)

      lib2.remote("add", "--fetch", "lib1", lib1.path())

      app.remote("add", "--fetch", "lib1", lib1.path())
      app.remote("add", "--fetch", "lib2", lib2.path())

      regex = r"not a reachable commit"

      # Check that various variations of commit <-> remote repository
      # mismatches cause an error.
      with self.assertRaisesRegex(ProcessError, regex):
        lib2.subrepo("import", "lib1", ".", lib2_commits[1])

      with self.assertRaisesRegex(ProcessError, regex):
        app.subrepo("import", "lib1", ".", lib2_commits[0])

      with self.assertRaisesRegex(ProcessError, regex):
        app.subrepo("import", "lib2", ".", lib1_commits[1])

      with self.assertRaisesRegex(ProcessError, regex):
        app.subrepo("import", "lib2", ".", app_commits[1])

      # Now override the check. The imports must succeed.
      app.subrepo("import", "--force", "lib2", "test1", lib1_commits[0])
      self.assertTrue(exists(app.path("test1", "file1.txt")))
      self.assertFalse(exists(app.path("test1", "file2.txt")))

      app.subrepo("import", "--force", "lib2", "test1", lib1_commits[1])
      self.assertTrue(exists(app.path("test1", "file1.txt")))
      self.assertTrue(exists(app.path("test1", "file2.txt")))

      app.subrepo("import", "--force", "lib1", "test2", lib2_commits[0])
      self.assertTrue(exists(app.path("test1", "file1.txt")))
      self.assertTrue(exists(app.path("test1", "file2.txt")))
      self.assertTrue(exists(app.path("test2", "file1.txt")))
      self.assertFalse(exists(app.path("test2", "file2.txt")))


  def testImportRenamedFiles(self):
    """Verify that importing works properly in the face of file renames."""
    def doTest(prefix):
      """Perform the import test."""
      with GitRepository() as lib,\
           GitRepository() as app:
        mkdir(lib.path("lib"))
        file1 = join("lib", "test1.h")
        file2 = join("lib", "test.h")

        write(lib, file1, data="inline int test() { return 1337; }")
        lib.add(file1)
        lib.commit()

        app.remote("add", "--fetch", "lib", lib.path())
        app.subrepo("import", "lib", prefix, "master")
        self.assertTrue(exists(app.path(prefix, file1)))

        # Rename the header file.
        lib.mv(file1, file2)
        lib.commit()

        # Fetch new repository state and update.
        app.fetch("lib")
        app.subrepo("import", "lib", prefix, "master")

        self.assertTrue(exists(app.path(prefix, file2)))
        self.assertFalse(exists(app.path(prefix, file1)))

    doTest(".")
    doTest("prefix")
    doTest(join("dir1", "dir2"))


  def testIntermixedSubrepoUpdates(self):
    """Verify that intermixed subrepo updates are handled correctly."""
    def doTest(prefix):
      """Perform the import test."""
      with GitRepository() as lib1,\
           GitRepository() as lib2,\
           GitRepository() as app:
        write(lib1, "test.py", data="# state1")
        lib1.add("test.py")
        lib1.commit()

        app.remote("add", "--fetch", "lib1", lib1.path())
        app.subrepo("import", "lib1", prefix, "master")

        # Advance 'lib1' to state 2.
        write(lib1, "test.py", data="# state2")
        lib1.add("test.py")
        lib1.commit()

        # 'lib2' contains 'lib1' as a subrepo in state 2.
        lib2.remote("add", "--fetch", "lib1", lib1.path())
        lib2.subrepo("import", "lib1", prefix, "master")

        # 'app' contains 'lib2' as well. This import will implicitly
        # update 'lib1' to state 2.
        app.remote("add", "--fetch", "lib2", lib2.path())
        app.subrepo("import", "lib2", ".", "master")

        self.assertEqual(read(app, prefix, "test.py"), read(lib1, "test.py"))

        # Advance 'lib1' to state 3.
        write(lib1, "test.py", data="# state3")
        lib1.add("test.py")
        lib1.commit()

        app.fetch("lib1")
        app.subrepo("import", "lib1", prefix, "master")

        self.assertEqual(read(app, prefix, "test.py"), read(lib1, "test.py"))

    doTest(".")
    doTest("test")


  def testIndirectImport(self):
    """Verify that indirect imports (subrepos of subrepos) work properly."""
    with GitRepository() as lib1,\
         GitRepository() as lib2,\
         GitRepository() as appx:
      mkdir(lib1.path("lib1"))
      mkdir(lib1.path("lib1", "include"))
      write(lib1, "lib1", "include", "lib1.hpp", data="int test1() { return 42; }")
      lib1.add(lib1.path("lib1", "include", "lib1.hpp"))
      lib1.commit()

      mkdir(lib2.path("lib2"))
      mkdir(lib2.path("lib2", "include"))
      write(lib2, "lib2", "include", "lib2.hpp", data="int test2() { return 1337; }")
      lib2.add(lib2.path("lib2", "include", "lib2.hpp"))
      lib2.commit()

      # Add 'lib1' as a subrepo to 'lib2'. 'lib1' is never added to
      # 'appx' directly but it should get pulled in once 'lib2' is
      # imported.
      lib2.remote("add", "--fetch", "lib1", lib1.path())
      lib2.subrepo("import", "lib1", ".", "master")

      appx.remote("add", "--fetch", "lib2", lib2.path())
      appx.subrepo("import", "lib2", ".", "master")

      mkdir(appx.path("appx"))
      mkdir(appx.path("appx", "src"))
      write(appx, "appx", "src", "appx.cpp", data="int main() { return 0; }")
      appx.add(appx.path("appx", "src", "appx.cpp"))
      appx.commit()

      self.assertEqual(read(appx, "lib1", "include", "lib1.hpp"),
                       read(lib1, "lib1", "include", "lib1.hpp"))
      self.assertEqual(read(appx, "lib2", "include", "lib2.hpp"),
                       read(lib2, "lib2", "include", "lib2.hpp"))
      self.assertTrue(exists(appx.path("appx", "src", "appx.cpp")))

      write(lib1, "lib1", "include", "lib1_2.hpp", data="// test")
      lib1.add(lib1.path("lib1", "include", "lib1_2.hpp"))
      lib1.commit()

      lib2.fetch("lib1")
      lib2.subrepo("import", "lib1", ".", "master")

      appx.fetch("lib2")
      appx.subrepo("import", "lib2", ".", "master")

      self.assertEqual(read(appx, "lib1", "include", "lib1.hpp"),
                       read(lib1, "lib1", "include", "lib1.hpp"))
      self.assertEqual(read(appx, "lib2", "include", "lib2.hpp"),
                       read(lib2, "lib2", "include", "lib2.hpp"))
      self.assertTrue(exists(appx.path("appx", "src", "appx.cpp")))


if __name__ == "__main__":
  main()
