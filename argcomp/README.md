argcomp
=======

Purpose
-------

The **argcomp** package provides automatic argument completion support
for all Python programs that use argparse's ArgumentParser class for
their parameter handling. It does so by providing a drop-in replacement
that transparently provides a (hidden) --_complete argument that can be
invoked to automatically complete arguments. All that has to be done to
hook it up is to register a completion by invocation of the program with
this argument with the shell.


Rationale
---------

There already exist a couple of packages that provide similar
functionality. However, each was identified as inadequate.

* *optcomplete*: The *optcomplete* package, as the name suggests, only
  works with the optparse module which is deprecated and should not be
  used in new programs. It is also incompatible with Python 3,
  disqualifying it immediately.

* *python-selfcompletion*: This package works with argparse but is also
  not Python 3 ready. The code is not very well structured and
  inflexible because support for custom completer functions is missing.

* *argcomplete*: The argcomplete package appears to be Python 3
  compatible. However, in order to provide its functionality it copies,
  pastes, and modifies the argparse code as well as the shlex module.
  This approach comes with the downside of requiring backports of fixes
  to those packages. Not speaking of it plainly being ugly. On the
  bright side, this package supports custom completers and is the only
  viable option but because of the code duplication it was discarded as
  well.

**argcomp** combines the best of the aforementioned packages. It is
fully Python 3 compliant. It interfaces with argparse's ArgumentParser
without duplicating all its code and without peeking into any internals.
Lastly, it provides support for custom completers to allow for context
sensitive completions.


Usage
-----

To make use of the **argcomp** package, the user only needs to replace
the usage of *argparse*'s ``ArgumentParser`` with the provided
``CompletingArgumentParser`` class. Because the latter is fully
compatible to the former no additional work is required.

```diff
--- example.py
+++ example.py
@@ -1,7 +1,7 @@
 #!/usr/bin/python

-from argparse import (
-  ArgumentParser,
+from deso.argcomp import (
+  CompletingArgumentParser as ArgumentParser,
 )

 parser = ArgumentParser(description="Process some integers.")
```

In order to make the completion functionality accessible from the shell,
it needs to be registered first. Typically, this registration happens by
sourcing a prepared completion file upon start of the shell. A sample
completion file (valid for bash) looks like so:

```bash
_complete_example()
{
  local completions=$("${1}" --_complete "${COMP_CWORD}" "${COMP_WORDS[@]}")
  if [ $? -eq 0 ]; then
    readarray -t COMPREPLY < <(echo -n "${completions}")
  fi
}

complete -F _complete_example example.py
```

Here, the script ``example.py`` is registered to be completed by the
newly created shell function ``_complete_example``. Once this file is
sourced in a shell, completion is available.


Completers
----------

**argcomp** supports custom completers. A completer is a simple function
that is registered along with the argument for which to provide
completion. Such a function needs to have a given interface and yield
its completions. Other than that there are practically no limitations on
what a completer can use to provide completions.

A sample completer providing completions for local files and directories
can look like this:

```python
def localFileCompleter(parser, values, word):
  """A completer for files in the current working directory."""
  for value in listdir():
    if value.startswith(word):
      yield value
```

Registration is trivial and happens along with argument specification:
```diff
--- cat.py
+++ cat.py
@@ -13,7 +13,7 @@ def localFileCompleter(parser, values, word):

 parser = CompletingArgumentParser(prog="cat")
 parser.add_argument(
-  "files", nargs="+",
+  "files", nargs="+", completer=localFileCompleter,
   help="Files to cat."
 )

```

Note that completers are not part of *argparse*'s ArgumentParser. As
such, switching back to it requires removal of the completer keyword
parameter.


Installation
------------

The **argcomp** package has no dependencies other than a standard Python
3 installation. In order to install it it suffices to make the src/
directory known to Python by embedding it into the ``PYTHONPATH``.

If you are using [Gentoo Linux](https://www.gentoo.org/),
there is an [ebuild](https://github.com/d-e-s-o/argcomp-ebuild)
available that can be used directly.


Support
-------

The module is tested with Python 3. There is no work going on to
ensure compatibility with Python 2.
