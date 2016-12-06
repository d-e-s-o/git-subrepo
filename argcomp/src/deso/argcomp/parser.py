# parser.py

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

"""Argument completion functionality for the argparse module."""

from argparse import (
  Action,
  ArgumentParser,
  REMAINDER,
  SUPPRESS,
)
from collections import (
  namedtuple,
)
from itertools import (
  chain,
)
from sys import (
  argv,
  maxsize,
)


COMPLETE_OPTION = "--_complete"


class Argument(namedtuple("Argument", ["min_", "max_"])):
  """A tuple describing arguments."""
  def __new__(cls, min_=0, max_=0):
    """Overwrite class creation to provide proper default arguments."""
    return super().__new__(cls, min_, max_)


  def decrement(self):
    """Retrieve a new tuple with the min_ and max_ value decremented by one."""
    return Argument(self.min_ - 1, self.max_ - 1)


class Arguments(namedtuple("Arguments", ["positionals", "keywords"])):
  """A tuple describing possible program options."""
  def __new__(cls, positionals=None, keywords=None):
    """Overwrite class creation to provide proper default arguments."""
    if positionals is None:
      positionals = []
    if keywords is None:
      keywords = {}

    return super().__new__(cls, positionals, keywords)


def escapeDoubleDash(args, index=0):
  """Escape all '--' strings in the array."""
  first = args[:index]
  second = map(lambda x: x.replace(r"--", r"\--"), args[index:])
  return chain(first, second)


def unescapeDoubleDash(args):
  """Unescape all escaped '--' strings in the array."""
  return map(lambda x: x.replace(r"\--", r"--"), args)


def complete(arguments, words):
  """Complete the last word in the given list of words."""
  def getPositional():
    """Retrieve the positional argument at 'pos_idx'."""
    if pos_idx < len(arguments.positionals):
      return arguments.positionals[pos_idx]
    else:
      return Argument()

  # Without loss of generality, we attempt completing the last word in
  # the list of words. The assumption here is that only context before
  # this word matters, so everything found afterwards is irrelevant and
  # must be removed by the caller.
  *words, to_complete = words
  # The index to the next parser-level positional argument.
  pos_idx = 0
  # The parser-level positional arguments for the given argument.
  pos = getPositional()
  # The minimum and maximum keyword-level positional arguments.
  key = Argument()

  for word in words:
    # Try matching any keyword arguments. They take precedence over
    # positional arguments below.
    if word in arguments.keywords:
      value = arguments.keywords[word]
      key = Argument()
      if isinstance(value, Arguments):
        arguments = value
      elif isinstance(value, Argument):
        key = value
    # Try matching it as a positional. Keyword argument positionals
    # take precedence over parser level ones.
    elif key.max_ > 0:
      key = key.decrement()
    elif pos.max_ > 0:
      pos = pos.decrement()
    else:
      for pos_idx in range(pos_idx + 1, len(arguments.positionals)):
        pos = getPositional()
        if pos.max_ > 0:
          pos = pos.decrement()
          break
      else:
        # We were unable to find a matching positional argument.
        return

  # If there are open keyword-level positional arguments then we
  # should not start completion of keyword arguments.
  if key.min_ <= 0:
    for word in arguments.keywords:
      if word.startswith(to_complete):
        yield word


def decodeNargs(nargs):
  """Decode the nargs value as accepted by the ArgumentParser's add_argument method."""
  if nargs == "*" or nargs == REMAINDER:
    # Any number of arguments.
    return 0, maxsize
  elif nargs == "?":
    # Zero or one argument.
    return 0, 1
  elif nargs == "+":
    # More than zero arguments.
    return 1, maxsize
  elif nargs is None:
    # In some scenarios (custom actions; probably others as well) the
    # nargs value might be None. The behavior in this case is to require
    # a single argument (similar to the default store action).
    return 1, 1
  else:
    # A specific number of arguments.
    assert isinstance(nargs, int), nargs
    return nargs, nargs


def decodeAction(action):
  """Decode the number of arguments for an action."""
  lookup = {
    # An action of None is the default and is equal to the "store"
    # action, both of which default to a single argument.
    None: 1,
    "store": 1,
    "store_const": 0,
    "store_true": 0,
    "store_false": 0,
    "append": 1,
    "append_const": 0,
    "count": 0,
    "help": 0,
    "version": 0,
  }

  try:
    return decodeNargs(lookup[action])
  except KeyError:
    # We must be dealing with an action object/class or an object
    # implementing the same interface. Any such object must have a
    # public 'nargs' member.
    # TODO: We assume we got passed in an object but a class is equally
    #       valid. It is unclear how we would deal with the latter.
    return decodeNargs(action.nargs)


class CompleteAction(Action):
  """An action used for completing command line arguments."""
  def __call__(self, parser, namespace, values, option_string=None):
    """Invoke the action to attempt to complete a command line argument."""
    values = list(unescapeDoubleDash(values))

    # The values array we got passed in here contains all arguments as
    # they were passed in to the --_complete option, in our case, the
    # word index ($COMP_CWORD) and words as parsed by the shell
    # ($COMP_WORDS[@]). The first word in the words array is typically
    # the Python script invoked. It might not be if the script was
    # invoked by indirectly by passing it as an argument to the
    # interpreter.
    index, script, *words = values
    index = int(index)

    # The approach we take here is to print all completions (separated
    # by a new line symbol) and then exit. The latter step is rather
    # clumsy but then no better solution that requires no additional
    # work on the client side was found.
    completions = list(complete(parser.arguments, words[:index]))
    if len(completions) > 0:
      print("\n".join(completions))

    parser.exit(0 if len(completions) > 0 else 1)


class CompletingArgumentParser(ArgumentParser):
  """An ArgumentParser derivate with argument completion support."""
  def __init__(self, *args, prefix_chars=None, fromfile_prefix_chars=None,
               arguments=None, **kwargs):
    """Create an argument parser with argument completion support."""
    assert prefix_chars is None, ("The prefix_chars argument is not "
                                  "supported. Got %s." % prefix_chars)
    assert fromfile_prefix_chars is None, ("The fromfile_prefix_chars "
                                           "argument is not supported. "
                                           "Got %s." % fromfile_prefix_chars)

    if arguments is None:
      self._arguments = Arguments()
    else:
      self._arguments = arguments

    # Note that in case the add_help option is true the argment parser
    # will add two arguments -h/--help. Because it uses the add_argument
    # method to do so there is nothing to do special from our side.
    super().__init__(*args, **kwargs)

    self.add_argument(
      COMPLETE_OPTION, action=CompleteAction, complete=False,
      default=SUPPRESS, nargs=REMAINDER, help=SUPPRESS,
    )


  def _addCompletion(self, arg, **kwargs):
    """Register a completion for the given argument."""
    # We only fall back to interpreting the action to deduce the
    # argument count if no nargs parameter is given.
    if "nargs" in kwargs:
      cur_min_, cur_max_ = decodeNargs(kwargs["nargs"])
    elif "action" in kwargs:
      cur_min_, cur_max_ = decodeAction(kwargs["action"])
    else:
      # If no action is given the store action expecting a single
      # argument is the default.
      cur_min_, cur_max_ = (1, 1)

    argument = Argument(cur_min_, cur_max_)
    keyword = arg.startswith("-")
    if keyword:
      # We are dealing with a keyword argument.
      self._arguments.keywords[arg] = argument
    else:
      # We are dealing with a positional argument.
      self._arguments.positionals.append(argument)


  def _addArgument(self, *args, complete=True, **kwargs):
    """Add completions for an argument to the parser."""
    if complete:
      for arg in args:
        self._addCompletion(arg, **kwargs)


  def add_argument(self, *args, complete=True, **kwargs):
    """Add an argument to the parser."""
    self._addArgument(*args, complete=complete, **kwargs)
    return super().add_argument(*args, **kwargs)


  def parse_known_args(self, args=None, namespace=None):
    """Parse all known arguments from a list of arguments."""
    # Note that the parse_args method is implemented in terms of
    # parse_known_args so the moment we overwrite the latter we
    # effectively change the behavior of both.
    # TODO: We are relying on an implementation detail here which is not
    #       what we want. The difficulty is to not escape arguments
    #       twice.
    if args is None:
      args = argv[1:]

    # Unfortunately, any '--' argument is interpreted by the
    # ArgumentParser causing it to treat all follow up arguments as
    # positional ones. This behavior is undesired for the --_complete
    # option where '--' is a valid prefix of an argument to complete and
    # so we escape it here (and unescape it later).
    # Alternatively, we could use two other approaches:
    # 1) Pass in the entire line instead of a pre-split list of words as
    #    provided by the $COMP_WORDS shell variable. The downside here
    #    is that we would manually need to perform argument
    #    parsing/splitting here (which is what we want to avoid, even in
    #    the face of the shlex module).
    # 2) Do not pass in arguments to --_complete but rather treat
    #    everything else as positional arguments. With this approach we
    #    have to find a way to define those (optional!) positional
    #    arguments but also to pass them in to the CompleteAction.
    try:
      # TODO: This approach likely breaks assignments, e.g.,
      #       --_complete="${COMP_WORDS[@]}"
      index = args.index(COMPLETE_OPTION) + 1
      args = list(escapeDoubleDash(args, index=index))
    except ValueError:
      pass

    return super().parse_known_args(args=args, namespace=namespace)


  def add_subparsers(self, *args, **kwargs):
    """Add subparsers to the argument parser."""
    def addParser(add_parser, name, *args, **kwargs):
      """A replacement method for the add_parser method."""
      sub_arguments = Arguments()
      self._arguments.keywords[name] = sub_arguments

      # Invoke the original add_parser function. We need to do that
      # because this function takes care of handling special keyword
      # arguments such as 'help' which must not be passed through to our
      # argument parser directly.
      return add_parser(name, *args, arguments=sub_arguments, **kwargs)

    assert "parser_class" not in kwargs, ("parser_class argument not supported. "
                                          "Got %s." % kwargs["parser_class"])

    # We create the subparsers object as would be done by a "real"
    # ArgumentParser but also overwrite the add_parser method.
    subparsers = super().add_subparsers(*args, parser_class=CompletingArgumentParser, **kwargs)

    add_parser = subparsers.add_parser
    subparsers.add_parser = lambda *a, **k: addParser(add_parser, *a, **k)

    return subparsers


  def _addGroup(self, add_func, *args, **kwargs):
    """Add an argument group to an argument parser."""
    def addArgument(add_argument, *args, complete=True, **kwargs):
      """A replacement method for the add_argument method."""
      self._addArgument(*args, complete=complete, **kwargs)
      return add_argument(*args, **kwargs)

    group = add_func(*args, **kwargs)

    add_argument = group.add_argument
    group.add_argument = lambda *a, **k: addArgument(add_argument, *a, **k)
    return group


  def add_argument_group(self, *args, **kwargs):
    """Add a named argument group to an argument parser."""
    return self._addGroup(super().add_argument_group, *args, **kwargs)


  def add_mutually_exclusive_group(self, *args, **kwargs):
    """Add a group to the argument parser whose options are mutually exclusive."""
    return self._addGroup(super().add_mutually_exclusive_group, *args, **kwargs)


  @property
  def arguments(self):
    """Retrieve the arguments."""
    return self._arguments
