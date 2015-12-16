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
  execute,
  findCommand,
  pipeline,
  ProcessError,
)
from os import (
  curdir,
  devnull,
  sep,
)
from os.path import (
  join,
  relpath,
)
from re import (
  search,
)
from sys import (
  argv as sysargv,
)


GIT = findCommand("git")
COMMIT_MSG_BASE = r"subrepo {prefix}:{repo} at {sha1}"


def trail(path):
  """Ensure the path has a trailing separator."""
  return join(path, "")


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


def searchSubrepoCommit(repo, prefix, head):
  """Retrieve the message body of the latest subrepo commit for the given remote repository."""
  pattern = COMMIT_MSG_BASE.format(prefix=prefix, repo=repo, sha1=r"[a-f0-9]\{40\}")
  out, _ = execute(GIT, "rev-list", "--grep=%s" % pattern, "--max-count=1",
                        "--format=format:%B", head, stdout=b"")
  if len(out) == 0:
    return None

  return out[:-1].decode("utf-8")


def retrieveLastSubrepoCommit(repo, prefix, head):
  """Retrieve the most recent subrepo commit for a given remote repository at a given prefix."""
  body = searchSubrepoCommit(repo, prefix, head)
  if body is None:
    error = "No subrepo commit found for {prefix}:{repo}"
    error = error.format(prefix=prefix, repo=repo)
    raise RuntimeError(error)

  regex = COMMIT_MSG_BASE.format(prefix=prefix, repo=repo, sha1=r"([a-f0-9]{40})")
  m = search(regex, body)
  if m is None:
    # The body will usually already contain a newline. However, we add
    # another one to be sure. The output would look weird if there was
    # none.
    error = "Commit {body}\ncontains no subrepo addition/update"
    error = error.format(body=body)
    raise RuntimeError(error)

  commit, = m.groups()
  return commit


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


def main(argv):
  """The main function interprets the arguments and acts upon them."""
  parser = setupArgumentParser()
  namespace = parser.parse_args(argv[1:])

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
  # We always resolve the possibly symbolic commit name into a SHA1
  # hash. The main reason is that we want this hash to be contained in
  # the commit message. So for consistency, we should also work with it.
  sha1 = resolveCommit(repo, commit)

  args = []
  if prefix != "%s%s" % (curdir, sep):
    # We want changes to appear relative to the given prefix. Hence, we
    # need to tell git to generate a patch that contains the appropriate
    # prefixes.
    args += ["--src-prefix=%s" % prefix, "--dst-prefix=%s" % prefix]
  else:
    # Do not add a/ or b/ prefixes. This option is required because we
    # supply -p0 to the apply command.
    args += ["--no-prefix"]

  if cmd == "add":
    # In case we add a new subrepo we need to generate a patch that
    # includes its entire source code up to the desired state. We do
    # that by diffing the desired state against an empty tree (or *the*
    # empty tree in this case, since git has a fixed hash representing
    # such a state).
    base = retrieveEmptyTree()
  elif cmd == "update":
    # In case of an update we need to find the commit at which the given
    # remote repository was imported last. This can then act as the
    # baseline to identify the new changes to import. This commit is
    # contained in a commit message generated by a previous git-subrepo
    # invocation.
    base = retrieveLastSubrepoCommit(repo, prefix, "HEAD")
  else:
    assert False

  args += [base, sha1]

  commands = [
    [GIT, "diff-tree", "--full-index", "--binary", "--no-color"] + args,
    [GIT, "apply", "-p0", "--binary", "--index", "--apply"],
  ]
  pipeline(commands)

  options = ["--edit"] if namespace.edit else []
  template = COMMIT_MSG_BASE.format(prefix=prefix, repo=repo, sha1=sha1)
  message = "{cmd} {template}"
  message = message.format(cmd=cmd, template=template)
  execute(GIT, "commit", "--no-verify", "--message=%s" % message, *options)
  return 0


if __name__ == "__main__":
  exit(main(sysargv))
