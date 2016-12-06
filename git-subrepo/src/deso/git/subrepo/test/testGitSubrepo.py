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
from deso.git.subrepo import (
  GitImporter,
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
  argv as sysargv,
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


TRUE = findCommand("true")
GIT = findCommand("git")
GIT_SUBREPO = realpath(join(dirname(__file__), pardir, "git-subrepo.py"))


def _subrepo(*args, **kwargs):
  """Invoke git-subrepo with the given arguments."""
  env = {}
  PathMixin.inheritEnv(env)
  PythonMixin.inheritEnv(env)

  return execute(executable, GIT_SUBREPO, *args, env=env, **kwargs)


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


  def message(self, commit):
    """Retrieve the commit message of a commit."""
    out, _ = self.show("--no-patch", "--format=format:%B", commit, stdout=b"")
    return out.decode("utf-8")


  def amend(self, message=None):
    """Amend the current HEAD commit to include all the staged changes."""
    if message is None:
      message = "--reuse-message=HEAD"
    else:
      message = "--message=%s" % message

    self.git("commit", "--amend", message)


  @Repository.autoChangeDir
  def reimport(self, commit, branch=None):
    """Reimport all subrepos found."""
    # In order for an interactive rebase operation to work in our
    # non-interactive test we simply skip the editor part by setting it
    # to /bin/true. A cleaner way might be some git-filter-branch
    # invocation but since we rarely use that in real-world workflows
    # and because it is more complex to employ we stay with rebase.
    env = {"GIT_EDITOR": TRUE}
    args = [executable, GIT_SUBREPO, "reimport"]
    if branch is not None:
      args += ["--branch=%s" % branch]

    cmd = " ".join(args)
    try:
      self.rebase("--interactive", "--keep-empty", "--exec=%s" % cmd, commit, env=env)
    except ProcessError as e:
      # The rebase stopped in the middle because of some error (expected
      # or not). Transparently abort the rebase here.
      self.rebase("--abort")
      raise


  @Repository.autoChangeDir
  def subrepo(self, *args):
    """Invoke a git-subrepo command."""
    _subrepo(*args)


class TestGitSubrepo(TestCase):
  """Tests for the git-subrepo script."""
  def testSubsumedFileRemoval(self):
    """Test that the removeSubsumedFiles method works as expected."""
    def doTest(files, expected):
      """Remove subsumed files from a list and check for the expected result."""
      new_files = GitImporter.removeSubsumedFiles(files)
      # We operate on sets (i.e., ignore order) to make testing more
      # intuitive.
      self.assertSetEqual(set(new_files), set(expected))

    input_output = [
      # A single file/directory should be left untouched.
      (["/usr/"],
       ["/usr/"]),
      # Duplicated entries should be removed (and trailing separators
      # ignored).
      (["/etc", "/etc/"],
       ["/etc"]),
      # Non-subsumed files need to stay.
      (["/etc/hosts.conf", "/etc/conf.d/"],
       ["/etc/hosts.conf", "/etc/conf.d/"]),
      (["/usr/lib/libz.so", "/usr/lib64"],
       ["/usr/lib/libz.so", "/usr/lib64"]),
      (["/usr/lib64/libz.so", "/usr/lib"],
       ["/usr/lib64/libz.so", "/usr/lib"]),
      (["/usr/lib64/", "/usr/lib"],
       ["/usr/lib64/", "/usr/lib"]),
      (["/usr/lib64", "/usr/lib/"],
       ["/usr/lib64", "/usr/lib/"]),
      (["/usr/lib64", "/usr/lib"],
       ["/usr/lib64", "/usr/lib"]),
      (["python/lib", "python/lib3"],
       ["python/lib", "python/lib3"]),
      # Subsumed files should be removed.
      (["/etc/hosts.conf", "/etc/conf.d/hostname", "/etc/conf.d/"],
       ["/etc/hosts.conf", "/etc/conf.d/"]),
      (["/etc/init.d", "/etc/init.d/x", "/etc/init.d/y"],
       ["/etc/init.d"]),
      (["/etc/env.d/", "/etc/env.d/00basic", "/etc/env.d/0", "/etc/env.d/10"],
       ["/etc/env.d/"]),
      (["/etc/env.d/", "/etc/conf.d/host", "/etc/conf.d", "/etc/env.d/00basic"],
       ["/etc/env.d/", "/etc/conf.d"]),
      (["/usr", "python", "python/lib", "python/lib3"],
       ["/usr", "python"]),
    ]

    for files, expected in input_output:
      doTest(files, expected)


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


  def testImportOnSameBranchAsImportDirectory(self):
    """Verify we can import when residing on a branch named equal to the import directory."""
    def doTest(r1_prefix, import_prefix):
      """Perform the import test with the given prefixes."""
      with GitRepository() as r1,\
           GitRepository() as r2:
        if r1_prefix != ".":
          mkdir(r1.path(r1_prefix))

        r1_file = r1.path(r1_prefix, "r1.py")
        r2_file = r2.path(import_prefix, r1_prefix, "r1.py")

        # Create two commits.
        write(r1, r1_file, data="# r1.py")
        r1.add(r1_file)
        r1.commit()

        write(r1, r1_file, data="# r1.py\n# 2")
        r1.add(r1_file)
        r1.commit()

        # Change to a branch of the same name as the remote repository and
        # the local directory where we import this remote repository.
        r2.checkout("-b", "r1")
        # Import at the first commit.
        r2.remote("add", "--fetch", "r1", r1.path())
        r2.subrepo("import", "r1", import_prefix, "master^")

        self.assertEqual(read(r2, r2_file), "# r1.py")

        # And import at the second commit.
        r2.subrepo("import", "r1", import_prefix, "master")
        self.assertEqual(read(r2, r2_file), read(r1, r1_file))

        # Also perform a deletion.
        self.assertTrue(exists(r2.path(import_prefix, r1_prefix)))
        r2.subrepo("delete", "r1", import_prefix)
        self.assertFalse(exists(r2.path(import_prefix, r1_prefix)))

    doTest(".", "r1")
    doTest("r1", ".")


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
    """Verify that in case the --debug-exceptions option is specified we get a backtrace."""
    with GitRepository() as repo:
      regex = r"Traceback \(most recent call last\)"
      with self.assertRaisesRegex(ProcessError, regex):
        repo.subrepo("import", "--debug-exceptions", "foo", "bar/", "HEAD")


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
    def doTest(prefix, directory=""):
      """Perform the import test."""
      with GitRepository() as lib,\
           GitRepository() as app:
        if directory:
          mkdir(lib.path(directory))

        # Note that joining with an empty directory ("") effectively is
        # a no-op.
        file1 = join(directory, "test1.h")
        file2 = join(directory, "test.h")

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

    for directory in ("", "lib"):
      doTest(".", directory=directory)
      doTest("prefix", directory=directory)
      doTest(join("dir1", "dir2"), directory=directory)


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


  def testIntermixedSubrepoUpdatesWithRenames(self):
    """Verify that intermixed subrepo updates with file renames are handled properly."""
    def doTest(prefix):
      """Perform the import test."""
      with GitRepository() as r1,\
           GitRepository() as r2,\
           GitRepository() as r3:
        write(r1, "test.py", data="foo")
        r1.add("test.py")
        r1.commit()

        # 'r3' contains 'r1'.
        r3.remote("add", "--fetch", "r1", r1.path())
        r3.subrepo("import", "r1", prefix, "master")

        r1.mv("test.py", "foo.py")
        r1.commit()

        # So does 'r2', but in a newer state with a renamed file.
        r2.remote("add", "--fetch", "r1", r1.path())
        r2.subrepo("import", "r1", prefix, "master")

        # 'r3' also contains 'r2'. This import implicitly updates 'r1'.
        r3.remote("add", "--fetch", "r2", r2.path())
        r3.subrepo("import", "r2", ".", "master")

        self.assertFalse(exists(r3.path(prefix, "test.py")))
        self.assertTrue(exists(r3.path(prefix, "foo.py")))

        # Advance 'r1' to state 3.
        r1.mv("foo.py", "bar.py")
        r1.commit()

        r3.fetch("r1")
        r3.subrepo("import", "r1", prefix, "master")

        self.assertFalse(exists(r3.path(prefix, "test.py")))
        self.assertFalse(exists(r3.path(prefix, "foo.py")))
        self.assertTrue(exists(r3.path(prefix, "bar.py")))

    doTest(".")
    doTest("test")


  def testNestedImportPrefixes(self):
    """Check that the prefixes for nested imports are correct."""
    with GitRepository() as r1,\
         GitRepository() as r2,\
         GitRepository() as r3:
      mkdir(r3.path("r3"))
      write(r3, "r3", "r3.py", data="r3")
      r3.add(r3.path("r3", "r3.py"))
      r3.commit()

      mkdir(r2.path("r2"))
      write(r2, "r2", "r2.py", data="r2")
      r2.add(r2.path("r2", "r2.py"))
      r2.commit()

      r2.remote("add", "--fetch", "r3", r3.path())
      r2.subrepo("import", "r3", "src-r3", "master")

      r1.remote("add", "--fetch", "r2", r2.path())
      r1.subrepo("import", "r2", "src-r2", "master")

      self.assertIn("import subrepo src-r2/:r2 at ", r1.message("HEAD"))
      self.assertIn("import subrepo src-r2/src-r3/:r3 at ", r1.message("HEAD"))


  def testImportWithSubsumingPrefix(self):
    """Import a state containing two directories with one's name being a prefix of the other's."""
    with GitRepository() as foo,\
         GitRepository() as bar:
      mkdir(bar.path("lib"))
      write(bar, "lib", "foo.py", data="test")
      mkdir(bar.path("lib64"))
      write(bar, "lib64", "bar.py", data="test2")

      bar.add(bar.path("lib", "foo.py"))
      bar.add(bar.path("lib64", "bar.py"))
      bar.commit()

      foo.remote("add", "--fetch", "bar", bar.path())
      foo.subrepo("import", "bar", ".", "master")

      self.assertEqual(read(foo, "lib/foo.py"), "test")
      self.assertEqual(read(foo, "lib64/bar.py"), "test2")

      # Make some changes to bar's files and then perform another import.
      write(bar, "lib", "foo.py", data="test3")
      write(bar, "lib64", "bar.py", data="test4")
      bar.add(bar.path("lib", "foo.py"))
      bar.add(bar.path("lib64", "bar.py"))
      bar.commit()

      foo.fetch("bar")
      foo.subrepo("import", "bar", ".", "master")

      self.assertEqual(read(foo, "lib/foo.py"), "test3")
      self.assertEqual(read(foo, "lib64/bar.py"), "test4")


  def performReimportTest(self, test_func):
    """Run a test function on a small subrepo scaffolding."""
    with GitRepository() as lib,\
         GitRepository() as app:
      # Let's create an initial (empty) commit and tag it so that later
      # on we can rebase easier.
      lib.commit("--allow-empty")
      lib.tag("init", "master")

      # Now create some actual content.
      write(lib, "test.txt", data="test")
      lib.add("test.txt")
      lib.commit()
      sha1 = lib.revParse("HEAD")

      # Import 'lib' as a subrepo.
      app.remote("add", "--fetch", "lib", lib.path())
      app.subrepo("import", "lib", ".", "master")

      self.assertEqual(read(app, "test.txt"), "test")
      self.assertIn(sha1, app.message("HEAD"))

      test_func(lib, app)


  def testReimportAmendedRemote(self):
    """Verify that we can properly reimport a subrepo with an amended HEAD commit."""
    def amendRemote(lib, app):
      """Amend the HEAD commit in the 'lib' repository and try reimporting it."""
      # Now change the latest commit in 'lib'.
      write(lib, "test.txt", data="data")
      lib.add("test.txt")
      lib.amend()
      sha1 = lib.revParse("HEAD")

      # Last but not least reimport the subrepo. It should contain the
      # latest changes afterwards.
      app.fetch("lib")
      app.reimport("init")

      self.assertEqual(read(app, "test.txt"), "data")
      self.assertIn(sha1, app.message("HEAD"))

    self.performReimportTest(amendRemote)


  def testReimportWithAdditionalChange(self):
    """Verify that reimports respect additional, local changes."""
    def extendedImport(lib, app):
      """Amend a subrepo import to add an additional file and test reimport."""
      # The most recent commit in the 'app' repository is an import. We
      # want to include some additional changes in it and make the
      # import message be contained in the body, not the subject line.
      write(app, "file.txt", data="file")
      app.add("file.txt")

      message = "add file.txt\n\n%s" % app.message("HEAD")
      app.amend(message)

      # Change the latest commit in 'lib' to force a reimport to happen.
      write(lib, "test.txt", data="newdata")
      lib.add("test.txt")
      lib.amend()

      # Reimport the subrepo.
      app.fetch("lib")
      app.reimport("init")

      self.assertEqual(read(app, "file.txt"), "file")
      self.assertEqual(read(app, "test.txt"), "newdata")

      expected = "add file.txt\n\nimport subrepo"
      self.assertIn(expected, app.message("HEAD"))

    self.performReimportTest(extendedImport)


  def testReimportIsIgnoredOnDifferentBranch(self):
    """Verify that the --branch parameter is handled correctly."""
    def amendOnDifferentBranch(lib, app):
      """Amend a subrepo import to modify additional files and test reimport."""
      sha1_old = lib.revParse("HEAD")
      lib.checkout("-b", "non-master")
      write(lib, "test.txt", data="data")
      lib.add("test.txt")
      lib.amend()
      sha1_new = lib.revParse("HEAD")

      # Last but not least reimport the subrepo. It should contain the
      # latest changes afterwards.
      app.fetch("lib")
      app.reimport("init", branch="master")

      self.assertEqual(read(app, "test.txt"), "test")
      self.assertIn(sha1_old, app.message("HEAD"))

      app.reimport("init", branch="non-master")

      self.assertEqual(read(app, "test.txt"), "data")
      self.assertIn(sha1_new, app.message("HEAD"))

    self.performReimportTest(amendOnDifferentBranch)


  def testReimportCwdInPrefix(self):
    """Verify that we can reimport a subrepo while residing in the respective prefix directory."""
    def reimport():
      """Reimport the subrepo imported at HEAD."""
      env = {}
      PathMixin.inheritEnv(env)
      PythonMixin.inheritEnv(env)

      execute(executable, GIT_SUBREPO, "reimport", env=env)

    def doTest(prefix):
      """Perform a reimport with the current working directory inside the subrepo path."""
      with GitRepository() as repo1,\
           GitRepository() as repo2:
        data = "".join(chr(randint(0, 255)) for _ in range(512))
        mkdir(repo1.path("dat"))
        write(repo1, join("dat", "file.bin"), data=data)
        repo1.add(join("dat", "file.bin"))
        repo1.commit()

        # Import 'repo1' as a subrepo.
        repo2.remote("add", "--fetch", "repo1", repo1.path())
        repo2.subrepo("import", "repo1", prefix, "master")

        file_ = join(prefix, "dat", "file.bin")
        self.assertEqual(read(repo2, file_), read(repo1, "dat", "file.bin"))

        data = "".join(chr(randint(0, 255)) for _ in range(512))
        write(repo1, join("dat", "file.bin"), data=data)
        repo1.add(join("dat", "file.bin"))
        repo1.amend()

        self.assertNotEqual(read(repo2, file_), read(repo1, "dat", "file.bin"))
        repo2.fetch("repo1")

        cwd = getcwd()
        chdir(repo2.path(prefix, "dat"))
        try:
          # Reimport the subrepo imported at HEAD.
          reimport()
        finally:
          chdir(cwd)

        self.assertEqual(read(repo2, file_), read(repo1, "dat", "file.bin"))

    doTest(".")
    doTest("dir")


  def testReimportCommitMessageFixup(self):
    """Verify that a reimport fixes up the import commit message correctly."""
    with GitRepository() as lib1,\
         GitRepository() as lib2,\
         GitRepository() as app:
      # Create commit #1.
      lib2.commit("--allow-empty")

      # Create commit #2.
      write(lib2, "lib2.c", data="dat")
      lib2.add("lib2.c")
      lib2.commit()
      sha1 = lib2.revParse("HEAD")

      # Import 'lib2' as a subrepo.
      app.remote("add", "--fetch", "lib2", lib2.path())
      app.subrepo("import", "lib2", "lib2", "master")

      self.assertEqual(read(app, "lib2", "lib2.c"), "dat")
      self.assertIn(sha1, app.message("HEAD"))

      # Create some content for 'lib1'.
      write(lib1, "lib1.c", data="dit")
      lib1.add("lib1.c")
      lib1.commit()

      # Now change 'lib2's history by adding a subrepo import BEFORE
      # commit #2. We do so by removing the top commit, performing a
      # subrepo import of 'lib1', and then cherry-picking the original
      # commit #2 (we still have its SHA1).
      lib2.reset("--hard", "HEAD^")
      lib2.remote("add", "--fetch", "lib1", lib1.path())
      lib2.subrepo("import", "lib1", "lib1", "master")
      lib2.cherryPick(sha1)

      # Lastly, reimport 'lib2' in 'app'. It should now pull in 'lib1'
      # and also mark this import in the resulting commit message.
      app.fetch("lib2")
      app.subrepo("reimport")

      self.assertEqual(read(app, "lib2", "lib1", "lib1.c"), "dit")
      self.assertIn(lib1.revParse("HEAD"), app.message("HEAD"))
      self.assertIn(lib2.revParse("HEAD"), app.message("HEAD"))


  def testReimportSameCommitInImportingRepository(self):
    """Reimport when the importing repo has a commit with the same message as the remote one."""
    with GitRepository() as r1,\
         GitRepository() as r2:
      r1.commit("--allow-empty")
      write(r1, "r1.c", data="1st")
      r1.add("r1.c")
      r1.commit()

      r2.commit("--allow-empty")
      write(r2, "r2.c", data="2nd")
      r2.add("r2.c")
      r2.commit()

      r2.remote("add", "--fetch", "r1", r1.path())
      r2.subrepo("import", "r1", ".", "master")

      write(r1, "r1.c", data="1st-amended")
      r1.add("r1.c")
      r1.amend()

      # Reimport 'r1' at changed state. This reimport would fail if we
      # could not properly handle the case that the importing repository
      # ("r2") contains a commit with the same subject line as the
      # commit we try to reimport the given remote repository ("r1") at.
      r2.fetch("r1")
      self.assertNotIn(r1.revParse("HEAD"), r2.message("HEAD"))
      r2.subrepo("reimport")
      self.assertIn(r1.revParse("HEAD"), r2.message("HEAD"))


  def testReimportRecursiveSubrepoImport(self):
    """Verify that we can reimport a recursive subrepo import."""
    with GitRepository() as r1,\
         GitRepository() as r2,\
         GitRepository() as r3:
      r1.commit("--allow-empty")
      write(r1, "r1.c", data="1st")
      r1.add("r1.c")
      r1.commit()

      r2.commit("--allow-empty")
      write(r2, "r2.c", data="2nd")
      r2.add("r2.c")
      r2.commit()

      r2.remote("add", "--fetch", "r1", r1.path())
      r2.subrepo("import", "r1", ".", "master")
      r2.commit("--allow-empty")

      r3.commit("--allow-empty")
      r3.remote("add", "--fetch", "r2", r2.path())
      r3.subrepo("import", "r2", ".", "master")

      write(r1, "r1.c", data="1st-amended")
      r1.add("r1.c")
      r1.amend()
      r1_sha1 = r1.revParse("HEAD")

      r2.fetch("r1")
      r2.reimport("HEAD^^")

      r3.fetch("r2")
      self.assertNotIn(r1_sha1, r3.message("HEAD"))
      r3.reimport("HEAD^")
      self.assertIn(r1_sha1, r3.message("HEAD"))


  def testReimportDelete(self):
    """Verify that deletion commits are reimported properly."""
    with GitRepository() as repo1,\
         GitRepository() as repo2:
      repo1.commit("--allow-empty")

      # Add some content to 'repo1'.
      mkdir(repo1.path("repo1"))
      write(repo1, "repo1", "test.asm", data="mov $42, %rax")
      repo1.add(repo1.path("repo1", "test.asm"))
      repo1.commit()

      # Create an initial empty commit so that we can properly rebase
      # over all others.
      repo2.commit("--allow-empty")
      repo2.tag("init", "master")

      # Import 'repo1' as a subrepo.
      repo2.remote("add", "--fetch", "repo1", repo1.path())
      repo2.subrepo("import", "repo1", ".", "master")

      self.assertTrue(exists(repo2.path("repo1", "test.asm")))

      repo2.subrepo("delete", "repo1", ".")
      self.assertFalse(exists(repo2.path("repo1", "test.asm")))

      # Next we add an additional file to 'repo1' and we do so by
      # amending the HEAD commit.
      write(repo1, "repo1", "file.asm", data="mov $1337, %rbx")
      repo1.add(repo1.path("repo1", "file.asm"))
      repo1.amend()

      # Now we reimport 'repo1' in 'repo2'. The import will pull in the
      # new file, file.asm, and the deletion should remove it.
      repo2.fetch("repo1")
      repo2.reimport("init")

      self.assertFalse(exists(repo2.path("repo1", "test.asm")))
      self.assertFalse(exists(repo2.path("repo1", "file.asm")))


  def testSubrepoDelete(self):
    """Verify that a subrepo can be deleted."""
    def doTest(prefix):
      """Perform the import test."""
      with GitRepository() as r1,\
           GitRepository() as r2:
        write(r1, "subrepoFile.py", data="r1")
        r1.add("subrepoFile.py")
        r1.commit()

        r2.remote("add", "--fetch", "r1", r1.path())
        r2.subrepo("import", "r1", prefix, "master")
        self.assertTrue(exists(r2.path(prefix, "subrepoFile.py")))

        r2.subrepo("delete", "r1", prefix)
        self.assertFalse(exists(r2.path(prefix, "subrepoFile.py")))

    doTest(".")
    doTest("prefix")


  def testSubrepoDelete(self):
    """Check that subrepo deletion commit messages have the expected format."""
    with GitRepository() as repo1,\
         GitRepository() as repo2,\
         GitRepository() as repo3,\
         GitRepository() as repo4:
      write(repo1, "first.py", data="first repo file")
      repo1.add("first.py")
      repo1.commit()

      write(repo2, "second.py", data="second repo file")
      repo2.add("second.py")
      repo2.commit()
      repo2.remote("add", "--fetch", "repo1", repo1.path())
      repo2.subrepo("import", "repo1", "prefix1", "master")

      write(repo3, "third.py", data="third repo file")
      repo3.add("third.py")
      repo3.commit()
      repo3.remote("add", "--fetch", "repo2", repo2.path())
      repo3.subrepo("import", "repo2", "prefix2", "master")

      write(repo4, "fourth.py", data="fourth repo file")
      repo4.add("fourth.py")
      repo4.commit()
      repo4.remote("add", "--fetch", "repo3", repo3.path())
      repo4.subrepo("import", "repo3", "prefix3", "master")

      repo4.subrepo("delete", "repo3", "prefix3")

      message = repo4.message("HEAD").splitlines()
      self.assertEqual(len(message), 4)
      self.assertEqual(message[0], "delete subrepo prefix3/:repo3")
      self.assertEqual(message[1], "")
      self.assertEqual(message[2], "delete subrepo prefix3/prefix2/:repo2")
      self.assertEqual(message[3], "delete subrepo prefix3/prefix2/prefix1/:repo1")


  def testIntermixedSubrepoDelete(self):
    """Verify that deletion of subrepos imported directly and indirectly works as expected."""
    def doTest(prefix):
      """Perform the import test."""
      with GitRepository() as r1,\
           GitRepository() as r2,\
           GitRepository() as r3:
        write(r1, "r1.py", data="data")
        r1.add("r1.py")
        r1.commit()

        r3.remote("add", "--fetch", "r1", r1.path())
        r3.subrepo("import", "r1", prefix, "master")

        r2.remote("add", "--fetch", "r1", r1.path())
        r2.subrepo("import", "r1", ".", "master")

        write(r2, "r2.cc", data="data")
        r2.add("r2.cc")
        r2.commit()

        r3.remote("add", "--fetch", "r2", r2.path())
        r3.subrepo("import", "r2", prefix, "master")

        self.assertTrue(exists(r3.path(prefix, "r1.py")))
        self.assertTrue(exists(r3.path(prefix, "r2.cc")))

        # Make some changes in 'r1' and create a new commit.
        write(r1, "blubb.py", data="foo")
        r1.add("blubb.py")
        r1.commit()

        # Import 'r1' directly into 'r3'.
        r3.fetch("r1")
        r3.subrepo("import", "r1", prefix, "master")

        # Also create a file in 'r3' directly.
        write(r3, "r3.py", data="data")
        r3.add("r3.py")
        r3.commit()

        self.assertTrue(exists(r3.path(prefix, "r1.py")))
        self.assertTrue(exists(r3.path(prefix, "blubb.py")))
        self.assertTrue(exists(r3.path(prefix, "r2.cc")))
        self.assertTrue(exists(r3.path("r3.py")))

        # Now delete 'r2' from 'r3'.
        r3.subrepo("delete", "r2", prefix)

        # The contents of 'r1' must persist because it got imported
        # directly into 'r3' as well, not just as a dependency of 'r2'.
        self.assertTrue(exists(r3.path(prefix, "r1.py")))
        self.assertTrue(exists(r3.path(prefix, "blubb.py")))
        self.assertFalse(exists(r3.path(prefix, "r2.cc")))
        self.assertTrue(exists(r3.path("r3.py")))

    doTest(".")
    doTest("foo")


  def testCannotDeleteUnknownSubrepo(self):
    """Check that we fail properly when attempting to delete an unknown subrepo."""
    def doTest(prefix):
      """Perform the deletion test."""
      with GitRepository() as r1,\
           GitRepository() as r2:
        write(r1, "r1.c", data="r1")
        r1.add("r1.c")
        r1.commit()

        r2.remote("add", "--fetch", "r1", r1.path())
        r2.subrepo("import", "r1", prefix, "master")

        regex = r"Subrepo .* not found"
        with self.assertRaisesRegex(ProcessError, regex):
          r2.subrepo("delete", "r3", prefix)

    doTest(".")
    doTest("foo")


  def testCannotDeleteSubrepoAtOtherPrefix(self):
    """Verify that subrepo deletion only works with the correct prefix."""
    def doTest(import_prefix, delete_prefix):
      """Perform the deletion test."""
      with GitRepository() as r1,\
           GitRepository() as r2:
        write(r1, "r1.c", data="r1")
        r1.add("r1.c")
        r1.commit()

        r2.remote("add", "--fetch", "r1", r1.path())
        r2.subrepo("import", "r1", import_prefix, "master")

        regex = r"Subrepo .* not found"
        with self.assertRaisesRegex(ProcessError, regex):
          r2.subrepo("delete", "r1", delete_prefix)

    doTest(".", "foo")
    doTest("foo", ".")


  def testCannotDeleteDependentSubrepo(self):
    """Verify that we cannot delete a subrepo that still is a dependency of another."""
    def doTest(prefix, lib2_prefixed=False):
      """Perform a test run."""
      with GitRepository() as lib1,\
           GitRepository() as lib2,\
           GitRepository() as app:
        if lib2_prefixed:
           lib2_prefix = "."
           app_prefix = prefix
        else:
           lib2_prefix = prefix
           app_prefix = "."

        write(lib1, "somefilewithaweirdname.y", data="ya?")
        lib1.add("somefilewithaweirdname.y")
        lib1.commit()

        write(lib2, "lib2.file", data="data!")
        lib2.add("lib2.file")
        lib2.commit()

        lib2.remote("add", "--fetch", "lib1", lib1.path())
        lib2.subrepo("import", "lib1", lib2_prefix, "master")

        app.remote("add", "--fetch", "lib1", lib1.path())
        app.subrepo("import", "lib1", prefix, "master")

        app.remote("add", "--fetch", "lib2", lib2.path())
        app.subrepo("import", "lib2", app_prefix, "master")

        regex = r"Cannot delete subrepo .* Still a dependency of"
        with self.assertRaisesRegex(ProcessError, regex):
          app.subrepo("delete", "lib1", prefix)

    doTest(".")
    doTest("dir", True)
    doTest("foobar", False)


  def testIndirectlyPulledInSubrepoCannotBeDeleted(self):
    """Verify that a subrepo that got pulled in only as dependency of another cannot be deleted."""
    def doTest(prefix):
      """Perform a test run."""
      with GitRepository() as lib1,\
           GitRepository() as lib2,\
           GitRepository() as app:
        write(lib1, "hello.cc", data="/* C++ */")
        lib1.add("hello.cc")
        lib1.commit()

        lib2.remote("add", "--fetch", "lib1", lib1.path())
        lib2.subrepo("import", "lib1", ".", "master")

        app.remote("add", "--fetch", "lib2", lib2.path())
        app.subrepo("import", "lib2", prefix, "master")

        regex = r"Cannot delete subrepo .* as it did not get imported directly."
        with self.assertRaisesRegex(ProcessError, regex):
          app.subrepo("delete", "lib1", prefix)

    doTest(".")
    doTest("dir")


  def performCompletion(self, to_complete, expected):
    """Perform a completion and verify the expected result is produced."""
    argv = [
      "--_complete",
      "%d" % len(to_complete),
      sysargv[0],
    ] + to_complete

    out, _ = _subrepo(*argv, stdout=b"")
    completions = out.decode().splitlines()
    self.assertSetEqual(set(completions), expected)


  def testCompletion(self):
    """Verify that commands and arguments can be completed properly."""
    self.performCompletion(["--h"], {"--help"})
    self.performCompletion(["imp"], {"import"})
    self.performCompletion(["import", "--debug"], {"--debug-commands", "--debug-exceptions"})
    self.performCompletion(["import", "--f"], {"--force"})
    self.performCompletion(["re"], {"reimport"})
    self.performCompletion(["reimport", "--e"], {"--edit"})


if __name__ == "__main__":
  main()
