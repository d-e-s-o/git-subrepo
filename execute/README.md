execute
=======


Purpose
-------

**execute** provides a process execution facility on top of the POSIX
fork/exec model. It comprises functionality similar to the standard
*subprocess* package but behind a more intuitive and user-friendly
interface. The package is not designed to be compatible with
*subprocess*. Some functionality, such as asynchronous process
execution, is not provided at all. The execution model of a pipeline, on
the other hand, passing the output of one program as input to another is
expressable in a very natural and efficient way. Similarly, handling of
environment variables is much more simple and safe.


Usage
-----

The **execute** package provides the ``execute`` function. This
primitive starts a process in a synchronous manner (i.e., waiting for it
to finish).
```python
>>> from deso.execute import execute
>>> execute("/bin/echo", "-n", "hello")
b''
```

It is possible to control which streams to read from. By default,
everything on standard error is reported (the empty byte object seen),
whereas standard output is not read. The reason for this behavior is
that whenever a program fails (that is, exits with a non-zero status),
an exception is raised and this exception contains the data printed to
standard error. Conversely, "most" programs do not write to standard out
and so by default this data is not captured.

Of course, the user is able to change this default.
```python
>>> execute("/bin/echo", "-n", "hello", stdout=b"", stderr=None)
b'hello'
```

Here, we read the standard output, appending it to an empty bytes
buffer, while simply ignoring any data on standard error. It is also
possible to stream into a file by supplying a file descriptor.
```python
>>> execute("/bin/echo", "hi", stdout=sys.stderr.fileno(), stderr=None)
hi
```

We redirect the output of the ``echo`` invocation directly to standard
error (which will cause it to be displayed immediately). Note that
**execute**, by virtue of the abstraction level it works at, does not
support Python's file-like objects: A file descriptor has to be a
numeric value.

Not only is it possible to read from the output strings, supplying input
is possible equally well.
```python
>>> execute("/bin/tr", "e", "a", stdin=b"hello", stdout=b"", stderr=None)
b'hallo'
```

The ``execute`` function also accepts an ``env`` parameter describing
the environment in which to create the new process. By default, the
entire environment of the parent process is inherited. However, it is
possible to selectively provide a subset of variables or to specify new
ones.
```python
>>> env = {"VAR": "42"}
>>> execute("/bin/sh", "-c", "echo ${VAR}", env=env, stdout=b"", stderr=None)
b'42\n'
```


### Pipelines

**execute** provides native support for another execution primitive, a
*pipeline*. The behavior is similar to the equally named Unix primitive
with the output of one process from a list of processes being provided
as input to the next one.

Pipelines are accessible by means of the ``pipeline`` function. A
pipeline in the package's sense is simply a list of commands and their
parameters. With a command and parameter combination being a list of
strings, a pipeline is a list of a list of strings.

```python
>>> pipeline([
...     ["/bin/echo", "-n", "hello"],
...     ["/bin/tr", "e", "a"],
...   ], stdout=b"", stderr=None
... )
b'hallo'
```


### Springs

The last execution primitive supported natively by **execute** are so
called *springs*. A spring is a series of data producing sources whose
data is accumulated in a sequential fashion. A spring can be seen as a
pipeline with the first element being special in that it can comprise
multiple processes supplying data to the remaining ones.

```python
>>> spring([
...     [["/bin/echo", "hallo"], ["/bin/echo", "axacuta"]],
...     ["/bin/tr", "a", "e"]
...   ], stdout=b"", stderr=None
... )
b'hello\nexecute\n'
```

Because of their very nature of producing output in the first stage of
the pipeline, springs do not support the ``stdin`` keyword parameter.
The remaining accepted parameters, however, are similar to ``execute``
and ``pipeline`` functions.


Installation
------------

In order to use the **execute** package the
[cleanup](https://github.com/d-e-s-o/cleanup) Python module (contained
in the repository in compatible and tested versions) needs to be
accessible by Python (typically by installing it in a directory listed
in ``PYTHONPATH`` or adjusting the latter to point to it). The same
procedure should then be followed for the **execute** package itself.

If you are using [Gentoo Linux](https://www.gentoo.org/), there is an
[ebuild](https://github.com/d-e-s-o/execute-ebuild) available that can
be used directly.


Support
-------

The module is tested with Python 3. There is no work going on to
ensure compatibility with Python 2.
