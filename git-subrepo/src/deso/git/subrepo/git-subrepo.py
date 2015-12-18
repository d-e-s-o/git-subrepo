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

"""This script provides sub-repository functionality for git(1)."""

from argparse import (
  ArgumentParser,
  HelpFormatter,
)
from deso.execute import (
  execute as execute_,
  findCommand,
  formatCommands,
  pipeline as pipeline_,
  ProcessError,
  spring as spring_,
)
from os import (
  curdir,
  devnull,
  sep,
)
from os.path import (
  join,
  lexists,
  relpath,
)
from sys import (
  argv as sysargv,
)


GIT = findCommand("git")
VERBOSE = False


def trail(path):
  """Ensure the path has a trailing separator."""
  return join(path, "")


def execute(*args, **kwargs):
  """Run a program, optionally print the full command."""
  if VERBOSE:
    print(formatCommands(list(args)))

  return execute_(*args, **kwargs)


def pipeline(commands, *args, **kwargs):
  """Run a pipeline, optionally print the full command."""
  if VERBOSE:
    print(formatCommands(commands))

  return pipeline_(commands, *args, **kwargs)


def spring(commands, *args, **kwargs):
  """Run a spring, optionally print the full command."""
  if VERBOSE:
    print(formatCommands(commands))

  return spring_(commands, *args, **kwargs)


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
    "-e", "--edit", action="store_true", default=False, dest="edit",
    help="Open up an editor to allow for editing the commit message.",
  )
  parser.add_argument(
    "-v", "--verbose", action="store_true", default=False, dest="verbose",
    help="Be more verbose about what is being done by displaying the git "
         "commands performed.",
  )


def addAddParser(parser):
  """Add a parser for the 'add' command to another parser."""
  add = parser.add_parser(
    "add", add_help=False, formatter_class=SubLevelHelpFormatter,
    help="Add a subrepo.",
  )

  required = add.add_argument_group("Required arguments")
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

  optional = add.add_argument_group("Optional arguments")
  addOptionalArgs(optional)
  addStandardArgs(optional)


def addUpdateParser(parser):
  """Add a parser for the 'update' command to another parser."""
  add = parser.add_parser(
    "update", add_help=False, formatter_class=SubLevelHelpFormatter,
    help="Update a subrepo.",
  )

  required = add.add_argument_group("Required arguments")
  required.add_argument(
    "remote-repository", action="store",
    help="A name of a remote repository.",
  )
  required.add_argument(
    "prefix", action="store",
    help="The prefix to the subrepo.",
  )
  required.add_argument(
    "commit", action="store",
    help="A commit in the remote repository to update to.",
  )

  optional = add.add_argument_group("Optional arguments")
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

  addAddParser(subparsers)
  addUpdateParser(subparsers)
  return parser


def retrieveRepositoryRoot():
  """Retrieve the root directory of the current git repository."""
  out, _ = execute(GIT, "rev-parse", "--show-toplevel", stdout=b"")
  return out[:-1].decode("utf-8")


def retrieveEmptyTree():
  """Retrieve the SHA1 sum of the empty tree."""
  # Note that the SHA1 sum of the empty tree is constant and *should*
  # not change. It is '4b825dc642cb6eb9a060e54bf8d69288fbee4904'.
  # However, to be safe here (and to document how to derive it), we
  # query it on the fly.
  out, _ = execute(GIT, "hash-object", "-t", "tree", devnull, stdout=b"")
  return out[:-1].decode("utf-8")


def resolveCommit(repo, commit):
  """Resolve a potentially symbolic commit name to a SHA1 hash."""
  try:
    to_import = "refs/remotes/%s/%s" % (repo, commit)
    out, _ = execute(GIT, "rev-parse", to_import, stdout=b"")
    return out.decode("utf-8")[:-1]
  except ProcessError:
    # If we already got supplied a SHA1 hash the above command will fail
    # because we prefixed the hash with the repository, which git will
    # not understand. In such a case we want to make sure we are really
    # dealing with the SHA1 hash (and not something else we do not know
    # how to handle correctly) and ask git to parse it again, which
    # should just return the very same hash.
    out, _ = execute(GIT, "rev-parse", "%s" % commit, stdout=b"")
    out = out.decode("utf-8")[:-1]
    if out != commit:
      # Very likely we will not hit this path because git-rev-parse
      # returns an error and so we raise an exception beforehand. But
      # to be safe we keep it.
      raise RuntimeError("Commit name '%s' was not understood." % commit)

    return commit


def hasHead():
  """Check if the repository has a HEAD."""
  try:
    execute(GIT, "rev-parse", "HEAD", stderr=None)
    return True
  except ProcessError:
    return False


def main(argv):
  """The main function interprets the arguments and acts upon them."""
  global VERBOSE

  parser = setupArgumentParser()
  namespace = parser.parse_args(argv[1:])
  VERBOSE = namespace.verbose

  cmd = namespace.command
  repo = getattr(namespace, "remote-repository")
  root = retrieveRepositoryRoot()
  commit = namespace.commit
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
  # If the prefix resolved to this expression then the subrepo addition
  # is to happen in the root of the repository. This case needs some
  # special treatment later on.
  root_prefix = "%s%s" % (curdir, sep)
  # We always resolve the possibly symbolic commit name into a SHA1
  # hash. The main reason is that we want this hash to be contained in
  # the commit message. So for consistency, we should also work with it.
  sha1 = resolveCommit(repo, commit)

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

  head_tree = "HEAD^{tree}"
  empty_tree = retrieveEmptyTree()
  remote_tree = "%s^{tree}" % sha1

  git_diff_tree = [GIT, "diff-tree"] + args
  git_diff_index = [GIT, "diff-index"] + args
  git_diff_cache = [GIT, "diff-index", "--cached"] + args
  git_apply = [GIT, "apply", "-p0", "--binary", "--index", "--apply"]

  # We need to differentiate two cases here that decide the complexity
  # of the import we want to perform. Simply put, if the import is going
  # to happen into a true prefix (that is, not into the repository's
  # root), things get simpler because we only have to consider the
  # contents of this prefix directory. As a special case, this is also
  # the path we can take if the repository contains no commits yet
  # (i.e., if there is no HEAD commit).
  if prefix != root_prefix or not hasHead():
    # Adding a subrepo into its own directory (specified by 'prefix')
    # works as follow: in case there is nothing on disk for the given
    # prefix we simply pull in the changes making up the desired subrepo
    # state. If there is something on disk we create a patch reverting
    # those contents first and then apply the full diff as before.

    pipe_cmds = []
    # Note that we deliberately choose to perform the weakest check
    # possible here to detect presence of the given prefix (that is, we
    # just check if prefix exists at all, not if it is a directory, if
    # we have write access etc.). We let git handle the rest.
    if lexists(prefix):
      # This git-diff-index invocation is slightly different. Since we
      # diff against an on-disk path, that will already act as a prefix.
      # So we pass in --no-prefix here to void any previous prefix
      # related arguments.
      pipe_cmds += [git_diff_index + ["-R", "--no-prefix", empty_tree, prefix]]

    pipe_cmds += [git_diff_tree + [empty_tree, remote_tree]]

    commands = [
      pipe_cmds,
      git_apply,
    ]
    spring(commands)
  else:
    # The case of importing a subrepo into the repository's root is
    # somewhat more complex. We do some patch arithmetic here to achieve
    # the desired outcome: first, we find the difference between the
    # HEAD (that is, the entire content of the repository at the
    # current state) and the desired state of the remote repository.
    # This patch will revert *everything* in the repository except for
    # the remote repository bits (that might already exist). Next, we
    # additionally revert the entire subrepo state as it exists
    # currently. What we have now are cached changes that we need to
    # revert back once we updated the state of the subrepo in order to
    # not change any other unrelated parts of the repository.
    commands = [
      [
        git_diff_tree + [head_tree, remote_tree],
        git_diff_tree + ["-R", empty_tree, remote_tree],
      ],
      git_apply,
    ]
    spring(commands)

    # So the next step is to revert the currently cached changes and
    # then apply the difference of our HEAD against the desired state of
    # the remote repository on top. The result of this operation is that
    # we effectively imported the changes required to get the subrepo to
    # the desired state without touching any files that do not "belong"
    # to this subrepo.
    commands = [
      [
        git_diff_cache + ["-R", head_tree],
        git_diff_tree + [head_tree, remote_tree],
      ],
      git_apply,
    ]
    spring(commands)

  options = ["--edit"] if namespace.edit else []
  message = "{cmd} subrepo {prefix}:{repo} at {sha1}"
  message = message.format(cmd=cmd, prefix=prefix, repo=repo, sha1=sha1)
  execute(GIT, "commit", "--no-verify", "--message=%s" % message, *options)
  return 0


if __name__ == "__main__":
  exit(main(sysargv))
