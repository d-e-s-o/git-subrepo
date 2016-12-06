# testCompletingArgumentParser.py

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

"""Tests for the CompletingArgumentParser class."""

from argparse import (
  Action,
)
from deso.argcomp import (
  CompletingArgumentParser,
)
from deso.argcomp.parser import (
  decodeAction,
  decodeNargs,
  escapeDoubleDash,
  unescapeDoubleDash,
)
from io import (
  StringIO,
)
from sys import (
  argv as sysargv,
  executable,
  maxsize,
)
from unittest import (
  TestCase,
  main,
)
from unittest.mock import (
  patch,
)


class TestMisc(TestCase):
  """Tests for miscellaneous functionality accompanying the argument parser."""
  def testEscape(self):
    """Test the escapeDoubleDash function."""
    escaped = escapeDoubleDash([r"--"])
    self.assertEqual(list(escaped), [r"\--"])


  def testEscapeFromIndex(self):
    """Test the escapeDoubleDash function with a start index."""
    # No escaping should occur if we start at the second element.
    args = [r"--", r"foo"]
    escaped = escapeDoubleDash(args, 1)
    self.assertEqual(list(escaped), [r"--", r"foo"])


  def testEscapeAndUnescape(self):
    """Verify that escaping and unescaping an argument vector results in the original."""
    args = [r"bar", r"\\--", r"\--", r"--", r"--fo", r"foo"]
    transformed = unescapeDoubleDash(escapeDoubleDash(args))
    self.assertEqual(list(transformed), args)


  def testDecodeNargs(self):
    """Check that the decodeNargs() function works as expected."""
    min_, max_ = decodeNargs("*")
    self.assertEqual(min_, 0)
    self.assertEqual(max_, maxsize)

    min_, max_ = decodeNargs("?")
    self.assertEqual(min_, 0)
    self.assertEqual(max_, 1)

    min_, max_ = decodeNargs("+")
    self.assertEqual(min_, 1)
    self.assertEqual(max_, maxsize)

    min_, max_ = decodeNargs(50)
    self.assertEqual(min_, 50)
    self.assertEqual(max_, 50)


  def testDecodeAction(self):
    """Verify that the decodeAction() function works properly."""
    min_, max_ = decodeAction("store_false")
    self.assertEqual(min_, 0)
    self.assertEqual(max_, 0)

    min_, max_ = decodeAction("help")
    self.assertEqual(min_, 0)
    self.assertEqual(max_, 0)

    class TestAction(Action):
      """A action used for testing purposes."""
      def __call__(self, parser, namespace, values, option_string=None):
        """Invoke the action."""
        setattr(namespace, self.dest, values)

    min_, max_ = decodeAction(TestAction("-f", "foo", nargs=13))
    self.assertEqual(min_, 13)
    self.assertEqual(max_, 13)


class TestCompletingArgumentParser(TestCase):
  """Test cases for the CompletingArgumentParser class."""
  def testNoArgumentInNamespace(self):
    """Verify that the completion leaves no argument in the resulting namespace."""
    parser = CompletingArgumentParser(prog="test")
    parser.add_argument("--test", action="store_true")

    namespace = parser.parse_args(["--test"])
    self.assertEqual(vars(namespace), {"test": True})


  def testKnownArgsParsing(self):
    """Verify that the parse_known_args method works as expected."""
    parser = CompletingArgumentParser(prog="known")
    parser.add_argument("--foo", action="store_false", default=True)

    namespace, remainder = parser.parse_known_args(["-f"])
    self.assertEqual(vars(namespace), {"foo": True})
    self.assertEqual(remainder, ["-f"])

    namespace, remainder = parser.parse_known_args(["--foo"])
    self.assertEqual(vars(namespace), {"foo": False})
    self.assertEqual(remainder, [])


  def performCompletion(self, parser, to_complete, expected,
                        exit_code=0, known_only=False):
    """Attempt a completion and compare the result against the expectation."""
    argv = [
      executable,
      __file__,
      "--_complete",
      # For now we always complete the second argument (argument indices
      # are zero based).
      "%d" % len(to_complete),
      sysargv[0],
    ] + to_complete

    with patch("sys.stdout", new_callable=StringIO) as mock_stdout:
      # After performing a completion we expect the parser to exit but
      # we want to avoid an exit for testing purposes.
      with self.assertRaises(SystemExit) as e:
        if known_only:
          parser.parse_known_args(argv[2:])
        else:
          parser.parse_args(argv[2:])

      completions = set(mock_stdout.getvalue().splitlines())
      self.assertSetEqual(completions, expected)
      self.assertEqual(e.exception.code, exit_code)


  def testSimpleKeywordArguments(self):
    """Verify that simple keyword arguments can be completed properly."""
    def doTest(known_only=False):
      """Perform the completion test."""
      k = {"known_only": known_only}
      parser = CompletingArgumentParser(prog="foo", add_help=False)

      parser.add_argument("--foo", action="store_true")
      self.performCompletion(parser, ["-"], {"--foo"}, **k)

      parser.add_argument("-b", "--bar", action="store_true")
      self.performCompletion(parser, ["-"], {"--foo", "-b", "--bar"}, **k)
      self.performCompletion(parser, ["--"], {"--foo", "--bar"}, **k)
      self.performCompletion(parser, ["-b"], {"-b"}, **k)
      self.performCompletion(parser, ["-b", "--foo", "-b"], {"-b"}, **k)
      self.performCompletion(parser, ["-b", "--foo", ""], {"--foo", "-b", "--bar"}, **k)

      # Also verify that an error is reported if there is no matching
      # completion.
      self.performCompletion(parser, ["--var"], set(), exit_code=1, **k)
      self.performCompletion(parser, ["-z"], set(), exit_code=1, **k)
      self.performCompletion(parser, ["-b", "-a"], set(), exit_code=1, **k)

    for known_only in (True, False):
      doTest(known_only)


  def testCompleteAfterPositional(self):
    """Verify that a single keyword argument following a positional argument can be completed."""
    parser = CompletingArgumentParser(add_help=False)
    parser.add_argument("positional")
    parser.add_argument("--foo", action="store_true")

    self.performCompletion(parser, ["foobar", ""], {"--foo"})


  def testCompleteAfterPositionals(self):
    """Verify that keyword arguments following positional arguments can be completed."""
    parser = CompletingArgumentParser(add_help=False)
    parser.add_argument("positional1")
    parser.add_argument("positional2")
    parser.add_argument("--foo", action="store_true")
    parser.add_argument("-b", "--bar", action="store_true")

    self.performCompletion(parser, ["foobar", ""], {"-b", "--bar", "--foo"})
    self.performCompletion(parser, ["-b", "foobar", "--"], {"--bar", "--foo"})
    self.performCompletion(parser, ["foobar", "bazzer", ""], {"-b", "--bar", "--foo"})
    self.performCompletion(parser, ["foobar", "--bar", "bazzer", ""], {"-b", "--bar", "--foo"})
    self.performCompletion(parser, ["foobar", "--bar", "bazzer", "booh"], set(), exit_code=1)


  def testMultipleArguments(self):
    """Verify that options with arguments can be handled and completed."""
    parser = CompletingArgumentParser()
    parser.add_argument("--test", nargs=1, type=str)
    parser.add_argument("-f", nargs="*", type=int)
    parser.add_argument("-b", "--bar", action="store_true")

    self.performCompletion(parser, ["--test", ""], set(), exit_code=1)


  def testArgumentsWithAllActions(self):
    """Check that we can add arguments for all sorts of actions."""
    parser = CompletingArgumentParser(add_help=False)
    parser.add_argument("store", action="store")
    parser.add_argument("store", action="store", nargs=42)
    parser.add_argument("store_const", action="store_const", const="foo")
    parser.add_argument("store_false", action="store_false")
    parser.add_argument("append", action="append")
    parser.add_argument("append_const", action="append_const", const="foo")
    parser.add_argument("count", action="count")

    parser.add_argument("--store", action="store", dest="store")
    parser.add_argument("--store2", action="store", nargs=3, dest="store2")
    parser.add_argument("--store_const", action="store_const", const="foo", dest="store_const")
    parser.add_argument("--store_false", action="store_false", dest="store_false")
    parser.add_argument("--append", action="append", dest="append")
    parser.add_argument("--append_const", action="append_const", const="foo", dest="append_const")
    parser.add_argument("--count", action="count", dest="count")
    parser.add_argument("--help", action="help")
    parser.add_argument("--version", action="version")

    # We don't actually do anything else here. We merely wanted to check
    # that we can successfully add completions for all "built-in"
    # actions.


  def testHelpCompletion(self):
    """Verify that the -h/--help arguments can be completed properly."""
    parser = CompletingArgumentParser(prog="foo")
    parser.add_argument("--foo", action="store_true")

    self.performCompletion(parser, ["-"], {"-h", "--foo", "--help"})
    self.performCompletion(parser, ["--h"], {"--help"})


  def testCompletionWithSubparser(self):
    """Verify that completion also works with sub parsers."""
    parser = CompletingArgumentParser(prog="subfoo", add_help=False)
    parser.add_argument("--foo", action="store_true")

    subparsers = parser.add_subparsers()
    bar = subparsers.add_parser("bar", add_help=False)
    bar.add_argument("-b", "--baz", action="store_true")

    foobar = subparsers.add_parser("foobar")
    foobar.add_argument("--foobar", action="store_true")

    subparsers2 = foobar.add_subparsers()
    foobarbaz = subparsers2.add_parser("foobarbaz", add_help=False)
    foobarbaz.add_argument("--test", action="store_true")

    self.performCompletion(parser, ["-"], {"--foo"})
    self.performCompletion(parser, ["b"], {"bar"})
    self.performCompletion(parser, ["bar", ""], {"-b", "--baz"})
    self.performCompletion(parser, ["foobar", ""], {"foobarbaz", "-h", "--foobar", "--help"})
    self.performCompletion(parser, ["--foo", "foobar", ""], {"foobarbaz", "-h", "--foobar", "--help"})
    self.performCompletion(parser, ["foobar", "--f"], {"--foobar"})
    self.performCompletion(parser, ["foobar", "f"], {"foobarbaz"})
    self.performCompletion(parser, ["foobar", "--foobar", "foobarbaz", ""], {"--test"})
    self.performCompletion(parser, ["--foo", "foobar", "foobarbaz", ""], {"--test"})


  def testSubparsersCanCompleteSubCommands(self):
    """Verify that sub parsers can complete arguments themselves."""
    root = CompletingArgumentParser(prog="root", add_help=False)
    root.add_argument("--rootopt", action="store_true")

    subparsers = root.add_subparsers()
    sub1 = subparsers.add_parser("sub1", add_help=False, help="Perform sub1.")
    sub1.add_argument("-s", "--sub1opt", action="store_true")

    sub2 = subparsers.add_parser("sub2", add_help=False)
    sub2.add_argument("-s", "--sub2opt", action="store_true")

    subparsers2 = sub2.add_subparsers()
    sub21 = subparsers2.add_parser("sub21", help="Perform sub21.")
    sub21.add_argument("--sub21opt", action="store_true")

    self.performCompletion(root, [""], {"--rootopt", "sub1", "sub2"})
    self.performCompletion(sub1, [""], {"-s", "--sub1opt"})
    self.performCompletion(sub1, ["--"], {"--sub1opt"})
    self.performCompletion(sub2, [""], {"sub21", "-s", "--sub2opt"})
    self.performCompletion(sub21, [""], {"-h", "--help", "--sub21opt"})


  def testCompleteAnyPositionals(self):
    """Verify that we can handle a '*' parser-level positional argument correctly."""
    parser = CompletingArgumentParser(prog="posUnlimited")
    parser.add_argument("positionals", nargs="*")

    self.performCompletion(parser, ["-"], {"-h", "--help"})
    self.performCompletion(parser, ["pos1", "--"], {"--help"})
    self.performCompletion(parser, ["pos1", "pos2", ""], {"-h", "--help"})


  def testCompleteSinglePositionalMax(self):
    """Verify that parser-level positionals can be exhausted."""
    parser = CompletingArgumentParser(prog="posLimited")
    parser.add_argument("positionals", nargs="?")

    self.performCompletion(parser, ["-"], {"-h", "--help"})
    self.performCompletion(parser, ["pos1", "--"], {"--help"})
    self.performCompletion(parser, ["pos1", "pos2", ""], set(), exit_code=1)


  def testCompleteFixedPositionals(self):
    """Verify that completion stops after exceeding the maximum parser-level positionals."""
    parser = CompletingArgumentParser(prog="posFixed")
    parser.add_argument("positionals", nargs=3)

    self.performCompletion(parser, ["-"], {"-h", "--help"})
    self.performCompletion(parser, ["pos1", "--"], {"--help"})
    self.performCompletion(parser, ["pos1", "pos2", ""], {"-h", "--help"})
    self.performCompletion(parser, ["pos1", "pos2", "pos3", ""], {"-h", "--help"})
    self.performCompletion(parser, ["pos1", "pos2", "pos3", "pos4", ""], set(), exit_code=1)


  def testCompleteWithArgumentGroups(self):
    """Verify that argument groups are considered in completions."""
    parser = CompletingArgumentParser(prog="withGroups", add_help=False)
    parser.add_argument("-t", action="store_true")

    group1 = parser.add_argument_group("test group 1")
    group1.add_argument("-f", "--foo", action="store_true")
    group1.add_argument("-h", "--help", action="store_true")

    group2 = parser.add_argument_group("test group 2")
    group2.add_argument("--bar", action="store_true")

    self.performCompletion(parser, ["-"], {"-f", "-h", "-t", "--bar", "--foo", "--help"})
    self.performCompletion(parser, ["--"], {"--bar", "--foo", "--help"})
    self.performCompletion(parser, ["-f"], {"-f"})


  def testCompleteWithMutuallyExclusiveGroup(self):
    """Verify that mutually exclusive argument groups are handled correctly."""
    parser = CompletingArgumentParser(prog="mutexGroup", add_help=False)

    group = parser.add_mutually_exclusive_group()
    group.add_argument("--bar", action="store_true")
    group.add_argument("--baz", action="store_true")

    self.performCompletion(parser, ["-"], {"--bar", "--baz"})
    self.performCompletion(parser, ["--bar"], {"--bar"})


if __name__ == "__main__":
  main()
