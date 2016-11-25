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

"""This script provides sub-repository functionality for git(1)."""

from argparse import (
  ArgumentParser,
  HelpFormatter,
)
from bisect import (
  insort,
)
from collections import (
  namedtuple,
)
from deso.execute import (
  execute as execute_,
  findCommand,
  formatCommands,
  ProcessError,
  spring as spring_,
)
from functools import (
  lru_cache,
)
from os import (
  curdir,
  devnull,
  sep,
)
from os.path import (
  abspath,
  basename,
  commonprefix,
  join,
  lexists,
  normpath,
  relpath,
)
from re import (
  compile as compileRe,
)
from sys import (
  argv as sysargv,
  stderr,
)
from tempfile import (
  mktemp,
)


GIT = findCommand("git")
ECHO = findCommand("echo")
REPO_STR = "{prefix}:{repo}"
PREFIX_R = r"([^:\n]+)"
REPO_R = r"([^ \n]+)"
IMPORT_MSG = "import subrepo %s at {sha1}" % REPO_STR
DELETE_MSG = "delete subrepo %s" % REPO_STR
# A meant-to-be regular expression matching no whitespaces.
NO_WS_R = "[^ \t]+"
# We want to filter out all tree objects (i.e., git's version of a
# directory) and blobs (files) from a given state.
TREE_R = "(?:tree|blob)"
# Our string matching a file imposes no restrictions on characters in
# its name/path.
FILE_R = ".+"
# A regular expression matching a SHA1 hash. A SHA1 checksum is
# comprised of 40 hexadecimal characters.
SHA1_R = "[a-z0-9]{40}"
IMPORT_MSG_R = IMPORT_MSG.format(prefix=PREFIX_R, repo=REPO_R, sha1="(%s)" % SHA1_R)
IMPORT_MSG_RE = compileRe(r"%s" % IMPORT_MSG_R)
DELETE_MSG_R = DELETE_MSG.format(prefix=PREFIX_R, repo=REPO_R)
DELETE_MSG_RE = compileRe(r"%s" % DELETE_MSG_R)
# As per git-ls-tree(1) each line has the following format:
# <mode> SP <type> SP <object> TAB <file>
LS_TREE = "{nows} {type} {nows}\t({file})$"
LS_TREE_R = LS_TREE.format(nows=NO_WS_R, type=TREE_R, file=FILE_R)
LS_TREE_RE = compileRe(LS_TREE_R)
# If the prefix resolved to this expression then the subrepo addition
# is to happen in the root of the repository. This case needs some
# special treatment later on.
ROOT_PREFIX = "%s%s" % (curdir, sep)


class SubrepoError(RuntimeError):
  """The base class for git-subrepo exceptions."""
  pass


class DependencyError(SubrepoError):
  """A class used for signaling dependency problems."""
  pass


class DeletionError(SubrepoError):
  """A class used for signaling problems in deleting a repository."""
  pass


class ReimportError(SubrepoError):
  """A class used for signaling problems in reimporting a repository."""
  pass


class Subrepo(namedtuple("Subrepo", ["repo", "prefix"])):
  """A class representing (repo, prefix) tuples uniquely identifying a subrepo."""
  def __str__(self):
    """Retrieve a textual representation of the subrepo tuple."""
    return REPO_STR.format(repo=self.repo, prefix=self.prefix)


def trail(path):
  """Ensure the path has a trailing separator."""
  return join(path, "")


def _git(root, *args):
  """Create a git command working in the given repository root."""
  return [GIT, "-C", root] + list(args)


def _execute(*args, verbose):
  """Run a program, optionally print the full command."""
  if verbose:
    print(formatCommands(list(args)))

  # We unconditionally read the stdout output. The overhead in our
  # context here is not much and we read stderr for error reporting
  # cases anyway.
  out, _ = execute_(*args, stdout=b"")
  return out


def _spring(commands, verbose):
  """Run a spring, optionally print the full command."""
  if verbose:
    print(formatCommands(commands))

  return spring_(commands)


class GitExecutor:
  """A class for executing git commands."""
  def __init__(self, root, verbose):
    """Initialize an executor object in the given git repository root."""
    assert abspath(root) == root, root

    self._root = root
    self._verbose = verbose


  def _command(self, *args):
    """Create a git command."""
    return _git(self._root, *args)


  def _diffArgs(self, prefix):
    """Retrieve suitable arguments for a git diff invocation."""
    args = ["--full-index", "--binary", "--no-color"]
    if prefix != ROOT_PREFIX:
      # We want changes to appear relative to the given prefix. Hence, we
      # need to tell git to generate a patch that contains the appropriate
      # prefixes.
      args += ["--src-prefix=%s" % prefix, "--dst-prefix=%s" % prefix]
    else:
      # Do not add a/ or b/ prefixes. This option is required because we
      # supply -p0 to the apply command.
      args += ["--no-prefix"]

    return args


  def diffIndexCommand(self):
    """Retrieve a git-diff-index command."""
    # Since we diff against an on-disk path, that will already act as
    # a prefix. So we pass in --no-prefix here.
    return self._command("diff-index") + self._diffArgs(ROOT_PREFIX)


  def diffTreeCommand(self, prefix):
    """Retrieve a git-diff-tree command."""
    return self._command("diff-tree") + self._diffArgs(prefix)


  def applyCommand(self):
    """Retrieve a git-apply command."""
    return self._command("apply", "-p0", "--binary", "--index", "--apply")


  def execute(self, *args):
    """Execute a git command."""
    return _execute(*self._command(*args), verbose=self._verbose)


  def spring(self, commands):
    """Execute a git command spring."""
    # Note that currently there are no clients reading output from a
    # spring so this use-case is not supported.
    return _spring(commands, verbose=self._verbose)


  def springWithSafeApply(self, pipe_cmds):
    """Create a spring comprising a pipeline of commands and running git-apply on the result."""
    # The idea here is: it is possible that a patch created by the given
    # pipeline of commands is empty. In such a case git-apply will fail,
    # which is undesired. We cannot work around this issue by catching
    # the resulting ProcessError because that could mask other errors.
    # So the work around is to emit a patch into the pipeline that
    # simply has no effect. To that end, we generate a temporary file
    # name (without generating the actual file; and yes, we use a
    # deprecated function because that *is* the correct way and
    # deprecating it instead of educating people is simply wrong). We
    # then tell git-apply to exclude this very file.
    file_ = basename(mktemp(prefix="null", dir=self._root))
    commands = [
      [
        [ECHO, retrieveDummyPatch(file_)],
      ] + pipe_cmds,
      self.applyCommand() + ["--exclude=%s" % file_],
    ]
    self.spring(commands)


  @property
  def root(self):
    """Retrieve the repository root associated with this executor object."""
    return self._root


def retrieveDummyPatch(file_):
  """Retrieve a dummy patch to stop git-apply from returning an error code on an empty diff."""
  return """\
diff --git {file} {file}
new file mode 100644
index 000000..000000
""".format(file=file_)


class TopLevelHelpFormatter(HelpFormatter):
  """A help formatter class for a top level parser."""
  def add_usage(self, usage, actions, groups, prefix=None):
    """Add usage information, overwrite the default prefix."""
    # Control flow is tricky here. Our invocation *might* come from the
    # sub-level parser or we might have been invoked directly. In the
    # latter case use our own prefix, otherwise just pass through the
    # given one.
    if prefix is None:
      prefix = "Usage: "

    super().add_usage(usage, actions, groups, prefix)


class SubLevelHelpFormatter(HelpFormatter):
  """A help formatter class for a sub level parser."""
  def add_usage(self, usage, actions, groups, prefix=None):
    """Add usage information, overwrite the default prefix."""
    super().add_usage(usage, actions, groups, "Usage: ")


def addStandardArgs(parser):
  """Add the standard arguments to an argument parser."""
  parser.add_argument(
    "-h", "--help", action="help",
    help="Show this help message and exit.",
  )


def addOptionalArgs(parser, reimport=False, delete=False, tree=False):
  """Add optional arguments to the argument parser."""
  parser.add_argument(
    "--debug-commands", action="store_true", default=False,
    dest="debug_commands",
    help="Display the commands being executed. This option is useful for "
         "understanding, debugging, and replaying what is being performed.",
  )
  parser.add_argument(
    "--debug-exceptions", action="store_true", default=False,
    dest="debug_exceptions",
    help="In addition to the already provided error messages also print "
         "backtraces for encountered errors.",
  )
  if not tree:
    parser.add_argument(
      "-e", "--edit", action="store_true", default=False, dest="edit",
      help="Open up an editor to allow for editing the commit message.",
    )
  if not reimport and not delete and not tree:
    parser.add_argument(
      "-f", "--force", action="store_true", default=False, dest="force",
      help="Force import of a subrepo at a given state even if the commit "
           "representing the state was not found to belong to the remote "
           "repository from which to import.",
    )


def addImportParser(parser):
  """Add a parser for the 'import' command to another parser."""
  import_ = parser.add_parser(
    "import", add_help=False, formatter_class=SubLevelHelpFormatter,
    help="Import a subrepo.",
  )
  import_.set_defaults(perform_command=performImport)

  required = import_.add_argument_group("Required arguments")
  required.add_argument(
    "remote-repository", action="store",
    help="A name of a remote repository. The remote repository must already be "
         "know and should be in an up-to-date state. If that is not the case "
         "you can add one using \"git remote add -f <remote-repository-name> "
         "<path-to-remote-repository>\"",
  )
  required.add_argument(
    "prefix", action="store",
    help="The prefix where to import the subrepo.",
  )
  required.add_argument(
    "commit", action="store",
    help="A commit of the remote repository to check out.",
  )

  optional = import_.add_argument_group("Optional arguments")
  addOptionalArgs(optional)
  addStandardArgs(optional)


def addReimportParser(parser):
  """Add a parser for the 'reimport' command to another parser."""
  reimport = parser.add_parser(
    "reimport", add_help=False, formatter_class=SubLevelHelpFormatter,
    help="Reimport a subrepo.",
  )
  reimport.set_defaults(perform_command=performReimport)

  optional = reimport.add_argument_group("Optional arguments")
  optional.add_argument(
    "-b", "--branch", action="store", default=None,
    help="Specify a branch in which to look for \"newer\" commits.",
  )
  optional.add_argument(
    "-v", "--verbose", action="store_true", default=None,
    help="Be more verbose and print the old and the new commit SHA1 on "
         "reimport.",
  )

  addOptionalArgs(optional, reimport=True)
  addStandardArgs(optional)


def addDeleteParser(parser):
  """Add a parser for the 'delete' command to another parser."""
  delete_ = parser.add_parser(
    "delete", add_help=False, formatter_class=SubLevelHelpFormatter,
    help="Delete a previously imported subrepo.",
  )
  delete_.set_defaults(perform_command=performDelete)

  required = delete_.add_argument_group("Required arguments")
  required.add_argument(
    "remote-repository", action="store",
    help="The name of the previously imported remote repository.",
  )
  required.add_argument(
    "prefix", action="store",
    help="The prefix of the imported subrepo.",
  )

  optional = delete_.add_argument_group("Optional arguments")
  addOptionalArgs(optional, delete=True)
  addStandardArgs(optional)


def addTreeParser(parser):
  """Add a parser for the 'tree' command to another parser."""
  tree = parser.add_parser(
    "tree", add_help=False, formatter_class=SubLevelHelpFormatter,
    help="Dump the dependency tree of all subrepos.",
  )
  tree.set_defaults(perform_command=performTree)

  optional = tree.add_argument_group("Optional arguments")
  addOptionalArgs(optional, tree=True)
  addStandardArgs(optional)


def setupArgumentParser():
  """Create and initialize an argument parser, ready for use."""
  parser = ArgumentParser(prog="git-subrepo", add_help=False,
                          formatter_class=TopLevelHelpFormatter)

  subparsers = parser.add_subparsers(
    title="Subcommands", metavar="command", dest="command",
    help="A command to perform.",
  )
  subparsers.required = True

  optional = parser.add_argument_group("Optional arguments")
  addStandardArgs(optional)

  addImportParser(subparsers)
  addReimportParser(subparsers)
  addDeleteParser(subparsers)
  addTreeParser(subparsers)
  return parser


def importMessage(subrepo, sha1):
  """Retrieve an import message for a subrepo import."""
  return IMPORT_MSG.format(prefix=subrepo.prefix, repo=subrepo.repo, sha1=sha1)


def importMessageForImports(imports, outer_prefix):
  """Retrieve a sorted list of import messages for the given imports."""
  messages = []
  # The imports can occur in basically arbitrary order. We want the
  # final import commit message to be somewhat consistent accross
  # multiple imports so we sort the entries by their final string
  # representation.
  for subrepo, sha1 in imports.items():
    # The prefix to embed in a commit message is comprised of the prefix
    # we performed the import in and the prefix the original import
    # happened in.
    import_prefix = trail(normpath(join(outer_prefix, subrepo.prefix)))
    message = importMessage(Subrepo(subrepo.repo, import_prefix), sha1)
    insort(messages, message)

  return messages


def importMessageForCommit(subrepo, sha1, imports, space=True):
  """Craft a commit message for a subrepo import."""
  subject = importMessage(subrepo, sha1)
  body = importMessageForImports(imports, subrepo.prefix)
  if not body:
    return subject

  return subject + ("\n\n" if space else "\n") + "\n".join(body)


def deleteMessage(subrepo):
  """Retrieve a commit message for a subrepo deletion."""
  return DELETE_MSG.format(prefix=subrepo.prefix, repo=subrepo.repo)


def deleteMessageForDeletion(dependencies):
  """Retrieve a sorted list of delete messages for the given deletion."""
  messages = []
  # The dependencies can occur in basically arbitrary order. We want the
  # final import commit message to be somewhat consistent accross
  # multiple commits so we sort the entries by their final string
  # representation.
  for subrepo, _ in dependencies:
    # Note that compared to the import we do not have to make any
    # adjustments to the prefix to use in the deletion message -- we can
    # simply reuse the same prefix as for the import.
    assert subrepo.prefix == trail(subrepo.prefix), subrepo.prefix
    message = deleteMessage(subrepo)
    insort(messages, message)

  return messages


def deleteMessageForCommit(subrepo, dependencies, space=True):
  """Craft a commit message for a subrepo deletion."""
  subject = deleteMessage(subrepo)
  body = deleteMessageForDeletion(dependencies)
  if not body:
    return subject

  return subject + ("\n\n" if space else "\n") + "\n".join(body)


class GitImporter:
  """A class handling subrepo imports."""
  def __init__(self, debug_commands):
    """Initialize the git subrepo importer object."""
    root = self._retrieveRepositoryRoot(debug_commands)
    self._git = GitExecutor(root, debug_commands)


  def resolveCommit(self, commit):
    """Resolve a commit into a SHA1 hash."""
    out = self._git.execute("rev-parse", "--verify", "%s^{commit}" % commit)
    return out.decode("utf-8")[:-1]


  def resolveRemoteCommit(self, repo, commit):
    """Resolve a potentially symbolic commit name in a remote repository to a SHA1 hash."""
    try:
      to_import = "refs/remotes/%s/%s" % (repo, commit)
      return self.resolveCommit(to_import)
    except ProcessError:
      # If we already got supplied a SHA1 hash the above command will fail
      # because we prefixed the hash with the repository, which git will
      # not understand. In such a case we want to make sure we are really
      # dealing with the SHA1 hash (and not something else we do not know
      # how to handle correctly) and ask git to parse it again, which
      # should just return the very same hash.
      sha1 = self.resolveCommit(commit)
      if sha1 != commit:
        # Very likely we will not hit this path because git-rev-parse
        # returns an error and so we raise an exception beforehand. But
        # to be safe we keep it.
        raise RuntimeError("Commit name '%s' was not understood." % commit)

      return commit


  def belongsToRepository(self, repo, sha1):
    """Check whether a given commit belongs to a remote repository."""
    def countRemoteCommits(*args):
      """Count the number of reachable commits in a remote repository."""
      out = self._git.execute("rev-list", "--count", "--remotes=%s" % repo, *args)
      return int(out[:-1].decode("utf-8"))

    # It is tougher than anticipated to simply find out whether a given
    # commit belongs to a given remote repository or not. The approach
    # chosen here is to count the number of reachable commits in a remote
    # repository with and without the given commit. If there is a
    # difference in commit count then we deduce that the commit is indeed
    # part of this repository. A potentially simpler approach is to do a
    # git-rev-list showing all commits and then "grep" for the commit of
    # interest. The problem with this approach is that either we need to
    # read a potentially huge list of commits into a Python string or we
    # have a dependency to the 'grep' program -- neither of which is
    # deemed acceptable.
    including = countRemoteCommits()
    excluding = countRemoteCommits("^%s" % sha1)
    # We excluded a single commit but it might be the parent of others
    # that now are also not listed. So every difference greater zero
    # indicates that the commit is indeed part of the repository.
    return including - excluding > 0


  def hasCachedChanges(self):
    """Check if the repository has changes."""
    try:
      # When using the --exit-code option the command will return 1 (i.e.,
      # cause an exception to be raised) in case there are changes and 0
      # otherwise.
      # Note that we cannot safely use git-diff-index or git-diff-tree
      # here because we cannot guarantee that a HEAD exists (and those
      # commands require some form of tree-ish or commit to be provided).
      self._git.execute("diff", "--cached", "--no-patch", "--exit-code", "--quiet")
      return False
    except ProcessError:
      return True


  @staticmethod
  def removeSubsumedFiles(files):
    """Remove files that are subsumed by directories."""
    if len(files) <= 1:
      return files

    # We work on a sorted list of files. This way we are sure that
    # directories potentially subsuming files appear before said files.
    files = sorted(files)
    subsumer, *files = files

    new_files = [subsumer]
    subsumer = trail(subsumer)

    for file_ in files:
      # Find the longest string both paths have in common. Note that
      # commonprefix really operates on a string/character level. It has
      # no knowledge of paths and path components. For that reason we need
      # some more checks below to not detect a subsumes relationship where
      # there is none. Consider for example the paths
      #   foo/bar
      #   foo/barbaz
      # where foo/bar is a common prefix of foo/barbaz on a string-level
      # but not on a path-level.
      prefix = commonprefix([file_, subsumer])
      if prefix == subsumer:
        # We determined that the given file could indeed be subsumed by
        # 'subsumer'. However, we need to rule out false positives caused
        # by working on a string level as opposed on a path level by
        # checking the determined prefix does not lie in the middle of
        # file_'s path. Note that usage of commonpath (available starting
        # from Python 3.5) instead of commonprefix above would relieve us
        # from these additional checks.
        length = len(prefix)
        is_file = length < len(file_) and file_[length - 1] == sep
        is_same = length == len(file_)

        if is_file or is_same:
          continue

      new_files += [file_]
      subsumer = trail(file_)

    return new_files


  def _diffAwayFiles(self, files):
    """Create a git command pipeline for removing a set of files/directories."""
    def diffAwayFile(file_):
      """If a file object exists, create a git command for creating a patch to remove it."""
      # Note that we deliberately choose to perform the weakest check
      # possible here to detect presence of the given file/directory (that
      # is, we just check if it exists at all, not if we have write access
      # etc.). We let git handle the rest.
      if lexists(join(self.root, file_)):
        return [git_diff_index + ["-R", empty_tree, "--", file_]]
      else:
        return []

    commands = []
    empty_tree = self._retrieveEmptyTree()
    git_diff_index = self._git.diffIndexCommand()

    for file_ in files:
      commands += diffAwayFile(file_)

    return commands


  def import_(self, subrepo, sha1):
    """Import a remote repository at a given commit at a given prefix."""
    assert trail(subrepo.prefix) == subrepo.prefix, subrepo.prefix
    assert self.resolveRemoteCommit(subrepo.repo, sha1) == sha1, sha1

    pipe_cmds = []
    empty_tree = self._retrieveEmptyTree()
    remote_tree = "%s^{tree}" % sha1

    git_diff_tree = self._git.diffTreeCommand(subrepo.prefix)
    files = self._readCommitFiles(sha1, subrepo.prefix)

    # If we can find a subrepo import commit for the same repository at
    # the same prefix then we can not only revert the files/directories
    # created by the new import commit but also by this previous one.
    # This logic properly handles file/directory file deletions and
    # renames between imports in the general case.
    # It is possible for a subrepo import to happen indirectly as part
    # of another import. Although those cases can be detected, it is
    # impossible to handle them correctly in a general manner as we
    # simply may not be able to access the commit data (in order to see
    # which files/directories are contained in the state it represents).
    if self._hasHead():
      # We lookup *all* imports that happened in our history as well as
      # in the past of the given commit.
      head_sha1 = self.resolveCommit("HEAD")
      current_imports = self._searchImportedSubrepos(head_sha1, flat=True)
      remote_imports = self._searchImportedSubrepos(sha1, flat=True)

      # Next we take all repository imports that happened in both
      # repositories (but potentially for different states) plus the
      # latest import of the remote repository to import itself (if any)
      # and revert the files associated with them as well.
      for remote_key in remote_imports.keys() | {subrepo}:
        if remote_key in current_imports:
          imported_sha1 = current_imports[remote_key]
          if self._isValidCommit(imported_sha1):
            files |= self._readCommitFiles(imported_sha1, remote_key.prefix)

    files = self.removeSubsumedFiles(files)
    pipe_cmds += self._diffAwayFiles(files)

    # Last but not least we need a patch that adds the desired bits of the
    # remote repository to this one.
    pipe_cmds += [git_diff_tree + [empty_tree, remote_tree]]
    self._git.springWithSafeApply(pipe_cmds)


  def _reimportImport(self, match, branch=None, verbose=False):
    """Attempt to reimport the import at the current HEAD, if any."""
    prefix, repo, old_commit = match.groups()
    subrepo = Subrepo(repo, prefix)

    subject = self._retrieveSubject(old_commit)
    new_commits = self._findCommitsBySubject(repo, subject, branch=branch)
    count = len(new_commits)
    if count != 1:
      if count < 1:
        msg = "Found no commits matching subject \"{sub}\"."
      else:
        msg = "Found {cnt} commits matching subject \"{sub}\":\n{commits}"

      # Note that it is safe to supply arguments that are not contained
      # in the string -- they will simply be ignored.
      msg = msg.format(cnt=count, sub=subject, commits="\n".join(new_commits))
      raise ReimportError(msg)

    new_commit, = new_commits
    if new_commit != old_commit:
      if verbose:
        print("Performing reimport.")
        print("Old commit: %s" % old_commit)
        print("New commit: %s" % new_commit)

      old_message = match.string
      new_message = self._replaceImportMessage(subrepo, old_message, new_commit, match.start())
      # Reimport the subrepo at a new commit. The incremental changes
      # (if any) will be staged, not committed yet.
      self.import_(Subrepo(repo, prefix), new_commit)
      # We amend the HEAD commit with the newly staged changes. We also
      # adjust the message to reference the correct new commit that we
      # updated to.
      self.amendCommit(new_message)
    else:
      if verbose:
        print("No changes found.")


  def _reimportDelete(self, match):
    """Attempt to reimport the deletion at the current HEAD, if any."""
    prefix, repo = match.groups()
    subrepo = Subrepo(repo, prefix)

    old_message = match.string
    new_message = self._replaceDeleteMessage(subrepo, old_message, match.start())
    # We simply perform another deletion on top of the existing one. If
    # any additional files had been added by means of a reimport these
    # will now get deleted, which is exactly what we want.
    # Note that HEAD^ always must exist at this point because in order
    # for a deletion commit to exist (legitimately) there must have been
    # an import beforehand.
    self.delete(subrepo, commit="HEAD^")
    self.amendCommit(new_message)


  def reimport(self, branch=None, verbose=False):
    """Attempt to reimport the current HEAD, if any."""
    if not self._hasHead():
      return

    old_message = self._retrieveMessage("HEAD")
    match = IMPORT_MSG_RE.search(old_message)
    if match is not None:
      self._reimportImport(match, branch=branch, verbose=verbose)
      return

    match = DELETE_MSG_RE.search(old_message)
    if match is not None:
      self._reimportDelete(match)
      return


  def commitImport(self, subrepo, sha1, edit=False):
    """Create a commit for an import."""
    options = ["--edit"] if edit else []
    imports = self._searchImportedSubrepos(sha1, flat=True)
    message = importMessageForCommit(subrepo, sha1, imports)
    self._git.execute("commit", "--no-verify", "--message=%s" % message, *options)


  def amendCommit(self, message):
    """Amend the HEAD commit with the currently staged changes."""
    self._git.execute("commit", "--amend", "--no-verify", "--message=%s" % message)


  def _findCommitsBySubject(self, repo, subject, branch=None):
    """Given a subject line, find all matching commits."""
    if branch is not None:
      # Note that unless the --remotes parameter's pattern contains some
      # sort of wildcard it will implicitly be converted into one by
      # appending "/*" at the end. We want an exact match of the branch
      # and so we explicitly make a wild card of it by placing the last
      # letter of the branch into square brackets.
      pattern = "%s/%s[%s]" % (repo, branch[:-1], branch[-1])
    else:
      pattern = repo

    args = [
      "--remotes=%s" % pattern,
      "--grep=^%s$" % subject,
    ]

    out = self._git.execute("rev-list", *args)
    commits = out.decode("utf-8").splitlines()
    return list(filter(lambda x: x.strip() != "", commits))


  def _findSubreposForDeletion(self, subrepo, commit=None):
    """Find the dependent subrepos for a deletion."""
    def flattenImports(tree):
      """Flatten a subrepo import tree by forcing all imports into a set."""
      flat = {subrepo_ for _, dependencies in tree.values()
                         for subrepo_, _ in dependencies}
      return tree.keys() | flat

    assert trail(subrepo.prefix) == subrepo.prefix, subrepo.prefix

    # Retrieve the full dependency tree for this repository. That is,
    # all the imported subrepos along with the subrepos they pulled in.
    head_sha1 = self.resolveCommit(commit if commit is not None else "HEAD")
    imports = self._searchImportedSubrepos(head_sha1)

    # Remove the top-level import of the repository we want to remove
    # from the set of imports (we know the repository is in there and it
    # hinders proper checking of dependencies while in there).
    without = {s: (v, d) for s, (v, d) in imports.items() if s != subrepo}
    # In order to perform checks on all imported subrepos, we need to
    # flatten the hierarchy. That is, we want all subrepos imported as
    # dependencies to be directly indexable as well.
    flattened = flattenImports(without)
    if subrepo not in imports:
      # We only support deletion of subrepos that were imported directly
      # and not just pulled in as a dependency of another subrepo.
      if subrepo in flattened:
        raise DeletionError("Cannot delete subrepo %s as it did not get "\
                            "imported directly." % str(subrepo))
      else:
        raise DeletionError("Subrepo %s not found." % str(subrepo))

    # Retrieve the SHA1 of the imported commit of the most recent import
    # of the subrepo to delete as well as the list of dependencies
    # imported along. We need the dependency list because we want to
    # remove those dependencies as well.
    commit, dependencies = imports[subrepo]

    delete_dependencies = set()
    ignore_dependencies = set()

    for imported_subrepo, imported_sha1 in [(subrepo, commit)] + dependencies:
      # Check if the given (prefix, repo) combination got pulled in
      # as part of another import as well, and not just as part of the
      # subrepo import which we are about to delete.
      if imported_subrepo in flattened:
        # If we are dealing with the repository we want to delete then
        # abort straight away. If, on the other hand, we are just
        # handling a dependency that got pulled in by another import, we
        # just silently continue because this dependency is still
        # needed.
        if imported_subrepo is subrepo:
          message = "Cannot delete subrepo %s. Still a dependency of %s."
          raise DependencyError(message % (subrepo, imported_subrepo))
        else:
          ignore_dependencies |= {(imported_subrepo, imported_sha1)}
      else:
        delete_dependencies |= {(imported_subrepo, imported_sha1)}

    return delete_dependencies, ignore_dependencies


  def _isValidCommitMessage(self, expression, message):
    """Check whether a given commit message is valid by matching each line with a pattern."""
    lines = filter(lambda x: len(x) > 0, message.splitlines())
    return all(map(expression.match, lines))


  def _replaceImportMessage(self, subrepo, old_message, new_commit, start):
    """Replace a commit message for an import for a specific commit with that of another commit."""
    imports = self._searchImportedSubrepos(new_commit, flat=True)
    # Sanity check that starting with the import line we found all
    # remaining lines of the commit message contain imports as well.
    if not self._isValidCommitMessage(IMPORT_MSG_RE, old_message[start:]):
      raise ReimportError("Invalid commit message. All import lines must reside at the end.")

    # We need to differentiate between the case where a commit is
    # *solely* an import and that when it contains other changes and,
    # thus, additional text in the commit message. In the latter case we
    # need to preserve the other text and must not craft an import
    # message with an empty line between the first import and the
    # others.
    space = start == 0
    new_message = importMessageForCommit(subrepo, new_commit, imports, space=space)
    if not space:
      new_message = old_message[:start] + new_message

    return new_message


  def _replaceDeleteMessage(self, subrepo, old_message, start):
    """Replace a commit message for an import for a specific commit with that of another commit."""
    # Sanity check that starting with the deletion line we found all
    # remaining lines of the commit message contain deletions as well.
    if not self._isValidCommitMessage(DELETE_MSG_RE, old_message[start:]):
      raise ReimportError("Invalid commit message. All deletion lines must reside at the end.")

    delete_deps, _ = self._findSubreposForDeletion(subrepo, commit="HEAD^")
    delete_deps = {(subrepo_, sha1) for subrepo_, sha1 in delete_deps
                     if subrepo_ != subrepo}

    space = start == 0
    new_message = deleteMessageForCommit(subrepo, delete_deps, space=space)
    if not space:
      new_message = old_message[:start] + new_message

    return new_message


  def delete(self, subrepo, commit=None):
    """Delete a previously imported subrepo."""
    assert trail(subrepo.prefix) == subrepo.prefix, subrepo.prefix

    if not self._hasHead():
      return

    delete_deps, ignore_deps = self._findSubreposForDeletion(subrepo, commit=commit)

    # We omit a subrepo from deletion. We need to remember the
    # files it comprises as those might be removed by deletion of a
    # "parent" subrepo, which is not what we want.
    # TODO: It is questionable whether the logic to exclude commits that
    #       are "invalid" (i.e., simply unknown in this repository) is
    #       sane. Couldn't it be that we delete too many/too few files
    #       because of that?
    ignore_files = {file_ for subrepo_, sha1 in ignore_deps
                     if self._isValidCommit(sha1)
                       for file_ in self._readCommitFiles(sha1, subrepo_.prefix)}
    # The set of files/directories which we want to remove. It basically
    # comprises the top-level files/directories of the commits that got
    # imported (directly or indirectly) into this repository as part of
    # a subrepo import.
    delete_files = {file_ for subrepo_, sha1 in delete_deps
                     if self._isValidCommit(sha1)
                       for file_ in self._readCommitFiles(sha1, subrepo_.prefix)}
    # A commit's files can comprise those of multiple subrepos. That
    # is not necessarily what we want because one of those subrepos
    # could be imported directly in which case we do not want to
    # delete it. So check the list of ignored files here.
    delete_files -= ignore_files

    delete_files = self.removeSubsumedFiles(delete_files)
    pipe_cmds = self._diffAwayFiles(delete_files)
    self._git.springWithSafeApply(pipe_cmds)


  def commitDelete(self, subrepo, edit=False):
    """Create a commit for a subrepo deletion."""
    options = ["--edit"] if edit else []
    delete_deps, _ = self._findSubreposForDeletion(subrepo)
    # The set of dependencies includes the one we want to delete. Remove
    # it from there as it is passed in separately to make sure it is
    # contained at the top of the commit message.
    delete_deps = {(subrepo_, sha1) for subrepo_, sha1 in delete_deps
                     if subrepo_ != subrepo}

    message = deleteMessageForCommit(subrepo, delete_deps)
    self._git.execute("commit", "--no-verify", "--message=%s" % message, *options)


  @property
  def root(self):
    """Retrieve the root directory of the git repository this importer is bound to."""
    return self._git.root


  @staticmethod
  def _retrieveRepositoryRoot(print_commands=False):
    """Retrieve the root directory of the current git repository."""
    # This function does not invoke git with the "-C" parameter because it
    # is the one that retrieves the argument to use with it.
    out = _execute(GIT, "rev-parse", "--show-toplevel", verbose=print_commands)
    return out[:-1].decode("utf-8")


  @lru_cache(maxsize=1)
  def _retrieveEmptyTree(self):
    """Retrieve the SHA1 sum of the empty tree."""
    # Note that the SHA1 sum of the empty tree is constant and *should*
    # not change. It is '4b825dc642cb6eb9a060e54bf8d69288fbee4904'.
    # However, to be safe here (and to document how to derive it), we
    # query it on the fly.
    out = self._git.execute("hash-object", "-t", "tree", devnull)
    return out[:-1].decode("utf-8")


  def _isValidCommit(self, commit):
    """Check whether a given SHA1 hash references a valid commit."""
    try:
      self._git.execute("rev-parse", "--quiet", "--verify", "%s^{commit}" % commit)
      return True
    except ProcessError:
      return False


  def _hasHead(self):
    """Check if the repository has a HEAD."""
    return self._isValidCommit("HEAD")


  def _readCommitFiles(self, sha1, prefix):
    """Given a commit, retrieve the top-level file objects contained in the state it represents."""
    out = self._git.execute("ls-tree", "%s^{tree}" % sha1)
    out = out.decode("utf-8")
    files = set()

    for line in out.splitlines():
      match = LS_TREE_RE.match(line)
      if match is not None:
        file_, = match.groups()
        files.add(file_)

    return {normpath(join(prefix, x)) for x in files}


  def _retrieveProperty(self, commit, format_):
    """Retrieve a property (represented by 'format_') of the given commit."""
    out = self._git.execute("show", "--no-patch", "--format=format:%%%s" % format_, commit)
    return out.decode("utf-8")


  def _retrieveSubject(self, commit):
    """Retrieve the subject line of the given commit."""
    # %s in a git format string represents the subject line.
    return self._retrieveProperty(commit, "s")


  def _retrieveMessage(self, commit):
    """Retrieve the message (description) of the given commit."""
    # %B in a git format string represents the raw description, containing
    # the subject line and the description body.
    return self._retrieveProperty(commit, "B")


  # This method can be rather expensive on large repositories. We cache
  # the return value in order to speed up repeated invocations.
  @lru_cache(maxsize=32)
  def _searchImportedSubrepos(self, head_commit, flat=False):
    """Find all subrepos that are imported in the history described by the given commit."""
    def importsAndDeletions(message, regex):
      """Extract all subrepo imports and deletions from a commit message."""
      # Note that a message can contain multiple imports/deletions in
      # case of nested subrepos. We want them all.
      for line in message.splitlines():
        match = regex.match(line)
        if match:
          import_prefix, import_repo, imported_commit,\
          delete_prefix, delete_repo = match.groups()

          if imported_commit is not None:
            prefix = import_prefix
            repo = import_repo
          else:
            prefix = delete_prefix
            repo = delete_repo

          # Theoretically, a remote repository can be imported multiple
          # times (although that really should be avoided). We support
          # this use case here by indexing with a pair of <repo, prefix>
          # instead of just the repository name, although other parts of
          # the program are free to prohibit such imports.
          yield Subrepo(repo, prefix), imported_commit

    def extractImports(commits, regex):
      """Extract all subrepo imports from the given list of commits."""
      imports = {}
      for commit in commits:
        message = self._retrieveMessage(commit)
        it = importsAndDeletions(message, regex)
        subrepo, sha1 = next(it)
        # Ignore all subsequent import messages of subrepos that we
        # already accounted for (with more recent commits).
        if subrepo in imports:
          continue

        # We are interested in top-level deletions but those on a lower
        # level have no value for us in this report.
        # TODO: We potentially do not want to include the SHA1 of
        #       imports at a lower level because unless we imported the
        #       repository directly as well, there is no way to access
        #       the commit (it simply is not known if the repository was
        #       not added as remote repository). Problem is that for the
        #       "flat" case we have to include the SHA1 sums at the
        #       moment (fix this?).
        imports[subrepo] = (sha1, [(k, v) for k, v in it if v is not None])

      # We want to filter out all the deletions as they should not be
      # visible to clients.
      return {k: (v, d) for k, (v, d) in imports.items() if v is not None}

    def extractImportsFlat(commits, regex):
      """Extract all subrepo imports into a flat dict."""
      imports = {}
      for commit in commits:
        message = self._retrieveMessage(commit)
        for subrepo, sha1 in importsAndDeletions(message, regex):
          if subrepo not in imports:
            imports[subrepo] = sha1

      return {k: v for k, v in imports.items() if v is not None}

    # For the caching to work reliably the provided commit must be a
    # SHA1 hash and not just a symbolic name.
    assert head_commit == self.resolveCommit(head_commit)

    # We create a pattern that is able to match subrepo imports as well
    # as deletions.
    component = "([^ :]+)"
    subrepo = Subrepo(component, component)
    import_pattern = importMessage(subrepo, "(%s)" % SHA1_R)
    delete_pattern = deleteMessage(subrepo)
    pattern = "%s|%s" % (import_pattern, delete_pattern)

    # The git pattern match is line based, meaning we can assume the
    # message to match starts at the beginning of the line and ends at
    # the end.
    out = self._git.execute("rev-list", "--extended-regexp", "--grep=^(%s)$" % pattern, head_commit)
    if out == b"":
      return {}

    extract = extractImports if not flat else extractImportsFlat
    commits = out.decode("utf-8").splitlines()
    # We match the message body line-based as well. We must not create a
    # new matching group for the entire pattern, however, so use the
    # '(?:XX) trickery here which is not available in git's regular
    # expression syntax.
    regex = compileRe("^(?:%s)$" % pattern)
    return extract(commits, regex)


def _retrieveSubrepoFromNamespace(namespace, git):
  """Given a namespace retrieve a Subrepo object for the prefix:repo attributes."""
  repo = getattr(namespace, "remote-repository")
  # The user-given prefix is to be treated relative to the current
  # working directory. This directory is not necessarily equal to the
  # current repository's root. So we have to perform some path magic in
  # order to convert the prefix into one relative to the git
  # repository's root. If we did nothing here git would always treat the
  # prefix relative to the root directory which would result in
  # unexpected behavior.
  prefix = relpath(namespace.prefix)
  prefix = relpath(prefix, start=git.root)
  prefix = trail(prefix)
  return Subrepo(repo, prefix)


def performImport(git, namespace):
  """Perform a subrepo import."""
  # If the user has cached changes we do not continue as they would be
  # discarded.
  if git.hasCachedChanges():
    print("Cannot import: Your index contains uncommitted changes.\n"
          "Please commit or stash them.", file=stderr)
    return 1

  subrepo = _retrieveSubrepoFromNamespace(namespace, git)
  # We always resolve the possibly symbolic commit name into a SHA1
  # hash. The main reason is that we want this hash to be contained in
  # the commit message. So for consistency, we should also work with it.
  sha1 = git.resolveRemoteCommit(subrepo.repo, namespace.commit)

  if not namespace.force and not git.belongsToRepository(subrepo.repo, sha1):
    msg = "{sha1} is not a reachable commit in remote repository {repo}."
    msg = msg.format(sha1=sha1, repo=subrepo.repo)
    print(msg, file=stderr)
    return 1

  git.import_(subrepo, sha1)

  if not git.hasCachedChanges():
    # Behave similarly to git commit when invoked with no changes made
    # to the repository's state and return 1.
    print("No changes", file=stderr)
    return 1

  git.commitImport(subrepo, sha1, namespace.edit)
  return 0


def performReimport(git, namespace):
  """Perform a subrepo reimport, if necessary."""
  if git.hasCachedChanges():
    print("Cannot import: Your index contains uncommitted changes.\n"
          "Please commit or stash them.", file=stderr)
    return 1

  git.reimport(branch=namespace.branch, verbose=namespace.verbose)
  return 0


def performDelete(git, namespace):
  """Perform a subrepo deletion."""
  if git.hasCachedChanges():
    print("Cannot delete: Your index contains uncommitted changes.\n"
          "Please commit or stash them.", file=stderr)
    return 1

  subrepo = _retrieveSubrepoFromNamespace(namespace, git)

  git.delete(subrepo)
  git.commitDelete(subrepo, namespace.edit)
  return 0


def performTree(git, namespace):
  """Dump the dependency tree of all imported subrepos."""
  def indent(*args):
    """Retrieve the proper indentation for usage in a tree.

      The function is supplied a variable number of <index, length>
      tuples. The number of tuples determines the amount of indentation
      (i.e., the depth of the resulting tree). Each tuple's length
      represents the total number of elements to print at the respective
      level. The index reflects the current element at this level.

      Using this data, this function can produce the indentation of a
      single line of an arbitrarily deep tree. E.g.:
        ├── <s1>
        │   ├── <s2>
        │   └── <s3>
        └── <s4>
    """
    indentation = ""

    for i, (index, length) in enumerate(args):
      if i < len(args) - 1:
        if index < length - 1:
          indentation += "│   "
        else:
          indentation += "    "
      else:
        if index < length - 1:
          indentation += "├── "
        else:
          indentation += "└── "

    return indentation

  if git._hasHead():
    head_sha1 = git.resolveCommit("HEAD")
    imports = git._searchImportedSubrepos(head_sha1)
    for i, (subrepo, (sha1, dependencies)) in enumerate(imports.items()):
      indentation = indent((i, len(imports)))
      string = "%s at %s" % (subrepo, sha1)
      print("%s%s" % (indentation, string))

      for j, (dependency, dep_sha1) in enumerate(dependencies):
        indentation = indent((i, len(imports)), (j, len(dependencies)))
        string = "%s at %s" % (dependency, dep_sha1)
        print("%s%s" % (indentation, string))

  return 0


def main(argv):
  """The main function interprets the arguments and acts upon them."""
  parser = setupArgumentParser()
  namespace = parser.parse_args(argv[1:])

  try:
    git = GitImporter(namespace.debug_commands)
    assert hasattr(namespace, "perform_command")
    return namespace.perform_command(git, namespace)
  except (AttributeError, ProcessError, SubrepoError) as e:
    if namespace.debug_exceptions:
      raise

    print("%s" % e, file=stderr)
    if isinstance(e, ProcessError):
      # A process failed executing so we mirror its return value.
      assert e.status != 0
      return e.status
    else:
      return 1


if __name__ == "__main__":
  exit(main(sysargv))
