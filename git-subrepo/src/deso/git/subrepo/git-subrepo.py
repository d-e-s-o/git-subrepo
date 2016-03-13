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
from deso.execute import (
  execute as execute_,
  findCommand,
  formatCommands,
  ProcessError,
  spring as spring_,
)
from os import (
  curdir,
  devnull,
  sep,
)
from os.path import (
  abspath,
  basename,
  join,
  lexists,
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
VERBOSE = False
IMPORT_MSG = "import subrepo {prefix}:{repo} at {sha1}"
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
# As per git-ls-tree(1) each line has the following format:
# <mode> SP <type> SP <object> TAB <file>
LS_TREE = "{nows} {type} {nows}\t({file})$"
LS_TREE_R = LS_TREE.format(nows=NO_WS_R, type=TREE_R, file=FILE_R)
LS_TREE_RE = compileRe(LS_TREE_R)


def trail(path):
  """Ensure the path has a trailing separator."""
  return join(path, "")


def git(root, *args):
  """Create a git command working in the given repository root."""
  return [GIT, "-C", root] + list(args)


def execute(*args, **kwargs):
  """Run a program, optionally print the full command."""
  if VERBOSE:
    print(formatCommands(list(args)))

  return execute_(*args, **kwargs)


def spring(commands, *args, **kwargs):
  """Run a spring, optionally print the full command."""
  if VERBOSE:
    print(formatCommands(commands))

  return spring_(commands, *args, **kwargs)


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


def addOptionalArgs(parser):
  """Add optional arguments to the argument parser."""
  parser.add_argument(
    "-d", "--debug", action="store_true", default=False, dest="debug",
    help="In addition to the already provided error messages also print "
         "backtraces for encountered errors.",
  )
  parser.add_argument(
    "-e", "--edit", action="store_true", default=False, dest="edit",
    help="Open up an editor to allow for editing the commit message.",
  )
  parser.add_argument(
    "-f", "--force", action="store_true", default=False, dest="force",
    help="Force import of a subrepo at a given state even if the commit "
         "representing the state was not found to belong to the remote "
         "repository from which to import.",
  )
  parser.add_argument(
    "-v", "--verbose", action="store_true", default=False, dest="verbose",
    help="Be more verbose about what is being done by displaying the git "
         "commands performed.",
  )


def addImportParser(parser):
  """Add a parser for the 'import' command to another parser."""
  import_ = parser.add_parser(
    "import", add_help=False, formatter_class=SubLevelHelpFormatter,
    help="Import a subrepo.",
  )

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
  return parser


def importMessage(repo, prefix, sha1):
  """Retrieve an import message for a subrepo import."""
  return IMPORT_MSG.format(prefix=prefix, repo=repo, sha1=sha1)


def importMessageForImports(imports):
  """Retrieve a sorted list of import messages for the given imports."""
  messages = []
  # The imports can occur in basically arbitrary order. We want the
  # final import commit message to be somewhat consistent accross
  # multiple imports so we sort the entries by their final string
  # representation.
  for (repo, prefix), sha1 in imports.items():
    message = importMessage(repo, prefix, sha1)
    insort(messages, message)

  return messages


def importMessageForCommit(repo, prefix, sha1, imports):
  """Craft a commit message for a subrepo import."""
  subject = importMessage(repo, prefix, sha1)
  body = importMessageForImports(imports)
  if not body:
    return subject

  return subject + "\n\n" + "\n".join(body)


def resolveCommit(root, repo, commit):
  """Resolve a potentially symbolic commit name to a SHA1 hash."""
  try:
    to_import = "refs/remotes/%s/%s" % (repo, commit)
    cmd = git(root, "rev-parse", to_import)
    out, _ = execute(*cmd, stdout=b"")
    return out.decode("utf-8")[:-1]
  except ProcessError:
    # If we already got supplied a SHA1 hash the above command will fail
    # because we prefixed the hash with the repository, which git will
    # not understand. In such a case we want to make sure we are really
    # dealing with the SHA1 hash (and not something else we do not know
    # how to handle correctly) and ask git to parse it again, which
    # should just return the very same hash.
    cmd = git(root, "rev-parse", "%s" % commit)
    out, _ = execute(*cmd, stdout=b"")
    out = out.decode("utf-8")[:-1]
    if out != commit:
      # Very likely we will not hit this path because git-rev-parse
      # returns an error and so we raise an exception beforehand. But
      # to be safe we keep it.
      raise RuntimeError("Commit name '%s' was not understood." % commit)

    return commit


def belongsToRepository(root, repo, sha1):
  """Check whether a given commit belongs to a remote repository."""
  def countRemoteCommits(*args):
    """Count the number of reachable commits in a remote repository."""
    cmd = git(root, "rev-list", "--count", "--remotes=%s" % repo) + list(args)
    out, _ = execute(*cmd, stdout=b"")
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


def hasCachedChanges(root):
  """Check if the repository has changes."""
  try:
    # When using the --exit-code option the command will return 1 (i.e.,
    # cause an exception to be raised) in case there are changes and 0
    # otherwise.
    # Note that we cannot safely use git-diff-index or git-diff-tree
    # here because we cannot guarantee that a HEAD exists (and those
    # commands require some form of tree-ish or commit to be provided).
    cmd = git(root, "diff", "--cached", "--no-patch", "--exit-code", "--quiet")
    execute(*cmd)
    return False
  except ProcessError:
    return True


def import_(repo, prefix, sha1, root=None):
  """Import a remote repository at a given commit at a given prefix."""
  def executeSafeApplySpring(apply_cmd, pipe_cmds):
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
    file_ = basename(mktemp(prefix="null", dir=root))
    commands = [
      [
        [ECHO, retrieveDummyPatch(file_)],
      ] + pipe_cmds,
      apply_cmd + ["--exclude=%s" % file_],
    ]
    spring(commands)

  def diffAwayFile(file_):
    """If a file object exists, create a git command for creating a patch to remove it."""
    # Note that we deliberately choose to perform the weakest check
    # possible here to detect presence of the given file/directory (that
    # is, we just check if it exists at all, not if we have write access
    # etc.). We let git handle the rest.
    if lexists(join(root, file_)):
      # Since we diff against an on-disk path, that will already act as
      # a prefix. So we pass in --no-prefix here.
      return [git_diff_index + ["-R", "--no-prefix", empty_tree, file_]]
    else:
      return []

  if root is None:
    root = retrieveRepositoryRoot()

  assert abspath(root) == root, root
  assert trail(prefix) == prefix, prefix
  assert resolveCommit(root, repo, sha1) == sha1, sha1

  # If the prefix resolved to this expression then the subrepo addition
  # is to happen in the root of the repository. This case needs some
  # special treatment later on.
  root_prefix = "%s%s" % (curdir, sep)

  args = ["--full-index", "--binary", "--no-color"]
  if prefix != root_prefix:
    # We want changes to appear relative to the given prefix. Hence, we
    # need to tell git to generate a patch that contains the appropriate
    # prefixes.
    args += ["--src-prefix=%s" % prefix, "--dst-prefix=%s" % prefix]
  else:
    # Do not add a/ or b/ prefixes. This option is required because we
    # supply -p0 to the apply command.
    args += ["--no-prefix"]

  pipe_cmds = []
  empty_tree = retrieveEmptyTree(root)
  remote_tree = "%s^{tree}" % sha1
  remote_imports = {}

  git_diff_tree = git(root, "diff-tree") + args
  git_diff_index = git(root, "diff-index") + args
  git_apply = git(root, "apply", "-p0", "--binary", "--index", "--apply")

  # We need to differentiate two cases here that decide the complexity
  # of the import we want to perform. Simply put, if the import is going
  # to happen into a true prefix (that is, not into the repository's
  # root), things get simpler because we only have to consider the
  # contents of this prefix directory. If we import into the root
  # directory we have to provide a pristine environment first, mainly to
  # make sure we do not miss removing any stale files (from renames in
  # between imports, for example), which could happen if we only applied
  # the changes to the desired state on top.
  if prefix != root_prefix:
    pipe_cmds += diffAwayFile(prefix)
  else:
    files = readCommitFiles(root, sha1)

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
    if hasHead(root):
      # We lookup *all* imports that happened in our history as well as
      # in the past of the given commit.
      current_imports = searchImportedSubrepos(root, "HEAD")
      remote_imports = searchImportedSubrepos(root, sha1)

      # Next we take all repository imports that happened in both
      # repositories (but potentially for different states) plus the
      # latest import of the remote repository to import itself (if any)
      # and revert the files associated with them as well.
      for remote_key in remote_imports.keys() | {(repo, prefix)}:
        if remote_key in current_imports:
          imported_sha1 = current_imports[remote_key]
          if isValidCommit(root, imported_sha1):
            files |= readCommitFiles(root, imported_sha1)

    for file_ in files:
      pipe_cmds += diffAwayFile(file_)

  # Last but not least we need a patch that adds the desired bits of the
  # remote repository to this one.
  pipe_cmds += [git_diff_tree + [empty_tree, remote_tree]]
  executeSafeApplySpring(git_apply, pipe_cmds)
  return remote_imports


def retrieveRepositoryRoot():
  """Retrieve the root directory of the current git repository."""
  # This function does not invoke git with the "-C" parameter because it
  # is the one that retrieves the argument to use with it.
  out, _ = execute(GIT, "rev-parse", "--show-toplevel", stdout=b"")
  return out[:-1].decode("utf-8")


def retrieveEmptyTree(root):
  """Retrieve the SHA1 sum of the empty tree."""
  # Note that the SHA1 sum of the empty tree is constant and *should*
  # not change. It is '4b825dc642cb6eb9a060e54bf8d69288fbee4904'.
  # However, to be safe here (and to document how to derive it), we
  # query it on the fly.
  cmd = git(root, "hash-object", "-t", "tree", devnull)
  out, _ = execute(*cmd, stdout=b"")
  return out[:-1].decode("utf-8")


def isValidCommit(root, commit):
  """Check whether a given SHA1 hash references a valid commit."""
  try:
    cmd = git(root, "rev-parse", "--quiet", "--verify", "%s^{commit}" % commit)
    execute(*cmd, stderr=None)
    return True
  except ProcessError:
    return False


def hasHead(root):
  """Check if the repository has a HEAD."""
  return isValidCommit(root, "HEAD")


def readCommitFiles(root, sha1):
  """Given a commit, retrieve the top-level file objects contained in the state it represents."""
  cmd = git(root, "ls-tree", "%s^{tree}" % sha1)
  out, _ = execute(*cmd, stdout=b"")
  out = out.decode("utf-8")
  files = set()

  for line in out.splitlines():
    match = LS_TREE_RE.match(line)
    if match is not None:
      file_, = match.groups()
      files.add(file_)

  return files


def retrieveProperty(root, commit, format_):
  """Retrieve a property (represented by 'format_') of the given commit."""
  cmd = git(root, "show", "--no-patch", "--format=format:%%%s" % format_, commit)
  out, _ = execute(*cmd, stdout=b"")
  return out.decode("utf-8")


def retrieveMessage(root, commit):
  """Retrieve the message (description) of the given commit."""
  # %B in a git format string represents the raw description, containing
  # the subject line and the description body.
  return retrieveProperty(root, commit, "B")


def searchImportedSubrepos(root, head_commit):
  """Find all subrepos that are imported in the history described by the given commit."""
  component = "([^ :]+)"
  pattern = importMessage(component, component, "(%s)" % SHA1_R)

  cmd = git(root, "rev-list", "--extended-regexp", "--grep=^%s$" % pattern, head_commit)
  out, _ = execute(*cmd, stdout=b"")
  if out == b"":
    return {}

  commits = out.decode("utf-8").splitlines()
  regex = compileRe(pattern)

  imports = {}
  for commit in commits:
    message = retrieveMessage(root, commit)
    # Note that a message can contain multiple imports in case of nested
    # subrepos. We want them all.
    for match in regex.finditer(message):
      prefix, repo, imported_commit = match.groups()
      # Theoretically, a remote repository can be imported multiple
      # times (although that really should be avoided). We support this
      # use case here by indexing with a pair of <repo, prefix> instead
      # of just the repository name, although other parts of the program
      # are free to prohibit such imports.
      key = (repo, prefix)
      # We only want the SHA1 of the last import of a given remote
      # repository.
      if key not in imports:
        imports[key] = imported_commit

  return imports


def main(argv):
  """The main function interprets the arguments and acts upon them."""
  global VERBOSE

  parser = setupArgumentParser()
  namespace = parser.parse_args(argv[1:])
  VERBOSE = namespace.verbose
  repo = getattr(namespace, "remote-repository")

  try:
    root = retrieveRepositoryRoot()
    # The user-given prefix is to be treated relative to the current
    # working directory. This directory is not necessarily equal to the
    # current repository's root. So we have to perform some path magic in
    # order to convert the prefix into one relative to the git
    # repository's root. If we did nothing here git would always treat the
    # prefix relative to the root directory which would result in
    # unexpected behavior.
    prefix = relpath(namespace.prefix)
    prefix = relpath(prefix, start=root)
    prefix = trail(prefix)

    # If the user has cached changes we do not continue as they would be
    # discarded.
    if hasCachedChanges(root):
      print("Cannot import: Your index contains uncommitted changes.\n"
            "Please commit or stash them.", file=stderr)
      return 1

    # We always resolve the possibly symbolic commit name into a SHA1
    # hash. The main reason is that we want this hash to be contained in
    # the commit message. So for consistency, we should also work with it.
    sha1 = resolveCommit(root, repo, namespace.commit)

    if not namespace.force and not belongsToRepository(root, repo, sha1):
      msg = "{commit} is not a reachable commit in remote repository {repo}."
      msg = msg.format(commit=namespace.commit, repo=repo)
      print(msg, file=stderr)
      return 1

    imports = import_(repo, prefix, sha1, root=root)

    if not hasCachedChanges(root):
      # Behave similarly to git commit when invoked with no changes made
      # to the repository's state and return 1.
      print("No changes", file=stderr)
      return 1

    options = ["--edit"] if namespace.edit else []
    message = importMessageForCommit(repo, prefix, sha1, imports)
    command = git(root, "commit", "--no-verify", "--message=%s" % message, *options)
    execute(*command)
    return 0
  except ProcessError as e:
    if namespace.debug:
      raise

    print("%s" % e, file=stderr)
    # A process failed executing so we mirror its return value.
    assert e.status != 0
    return e.status


if __name__ == "__main__":
  exit(main(sysargv))
