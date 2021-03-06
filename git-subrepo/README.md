git-subrepo
===========


Purpose
-------

**git-subrepo** provides another approach for connecting dependent
``git`` repositories.
Out of the box ``git`` offers two mechanisms for having one git
repository reference others: 'submodules' and 'subtrees'. Each has
particular drawbacks rendering it unusable in many scenarios. Submodules
are cumbersome to manage because a lot of management commands are
necessary. They also do not actually embed the source code of the
submodule into the repository where the module is to be used, but merely
store a reference to the hash. That means a subrepository (reference)
becomes stale in case the referenced repository's referenced branch is
rebased. Similarly, if a submodule refers to a non-published commit the
approach fails.

Subtrees came to the rescue by actually embedding the source code into
the repository. Yet, they have other, more subtle, drawbacks. Once a
subtree is imported (which happens via a merge) in a true subdirectory
("prefix") one cannot rebase over this commit without merge conflicts.
The reason is that git forgets about the "prefix" and subsequently tries
to merge the commit in the root. Rebasing being an operation that,
depending on the workflow, is essential and should not be limited just
because a library is being used, subtrees are not a satisfactory
solution either.

This is where **git-subrepo** steps in by introducing a third mechanism:
'subrepos'.
Just like subtrees, subrepos embed the referenced repository's source
code into the current ``git`` repository. However, inclusion does not
happen in the form of a merge but as a simple commit adding the remote
repository's files. Hence, rebasing over this commit is not special in
any way and will not cause conflicts.
When updating the subrepo, the most intuitive thing happens: the
difference between the addition/last update of the subrepo to the commit
to import is taken and applied in the form of a single commit. Again, no
merge commit is created.


Usage
-----

**git-subrepo** offers two commands for working with subrepos: 'import'
and 'delete'. An import can be used for both the initial addition of a
subrepo as well as an incremental update. A delete removes the
respective subrepo and its dependencies again.

A subrepo captures the state of a remote repository at a specific
commit. As such, the first thing to do is to have an up-to-date state of
the remote repository of interest.

If the remote repository is not know yet, it can be added like so:

``$ git remote add -f lib <url>``

This command would add a remote repository called 'lib' referencing the
``git`` repository found at '<url>'. Please refer to the git-remote(1)
manual for more information.

Using a remote repository, a new subrepo can be created:

``$ git subrepo import lib src/lib master``

The above command imports the source code from the remote repository
'lib' at commit 'master' (which in that case likely references a branch)
into the directory 'src/lib/' (relative to the importing repository's
root).

Similarly, in order to update a subrepo based on changes that happened
to the referenced remote repository, specifying a different revision is
enough:

``$ git subrepo import lib src/lib feature``

After invocation of this command the source code below 'src/lib' will
represent the state of 'lib' at commit 'feature'. The usual ``git``
syntax for conveying revisions is understood as the last parameter (see
git-rev-parse(1)).

The current state of imports can be visualized using the 'tree' command:

``$ git subrepo tree``                                            <br />
``└── src/lib/:lib at 1e0db5fa317743484948b65d417174358c38938a``

The output illustrates that the remote repository 'lib' has been
imported at a prefix src/lib within the repository. It also depicts the
commit at which the import happened.

If development crosses multiple repositories, managed in the form of
subrepos, it might become necessary to rebase one of the dependencies
and then update the respective subrepo. To aid with the latter part of
the workflow, **git-subrepo** provides the 'reimport' command that
checks if the 'HEAD' commit is a subrepo import and, if so, updates the
subrepo by importing the new state of the remote repository. Typically,
it is used during an interactive rebase operation:

``$ git rebase --interactive --exec='git subrepo reimport' HEAD^^^``

This command checks each of the top three commits whether it is a
subrepo import and updates the source code by reimporting it. Matching
of commits happens based on the subject, i.e., the topmost line in the
commit message.

Over the lifetime of a project dependencies come and go. If a dependency
that got imported in the form of a subrepo is no longer required, it can
be removed. The 'delete' command takes care of the removal, like so:

``$ git subrepo delete lib src/lib``

After execution of this command the subrepo 'lib' which got imported
below 'src/lib' got removed from the repository. The removal happened as
a normal commit, so the previous state can easily be restored.


Root Imports
------------

One advantage of subrepos over git's native submodules is the fact that
the source code of the destination is embedded in the repository. The
ability to have ordinary commits as opposed to merges as they are
created when subtrees are in use is beneficial for rebasing over
imports.

However, there is another feature that is unique to subrepos: the
ability to import remote repositories directly into the root directory
of the owning repository. Consider the following example:

```
  lib1
  └── src
      └── lib1.py
```

```
  lib2
  └── src
      ├── lib1
      │   └── src
      │       └── lib1.py
      └── lib2.py
```

In this example we have two libraries, 'lib1' and 'lib2'. The latter
depends on the former and, hence, imports it in the form of a subrepo.
Now imagine an application, 'app', using 'lib2'. Once 'app' imports
'lib2' it will implicitly import 'lib1' as well (which is intended
because it is an implicit dependency).

```
  app
  └── src
      ├── app.py
      └── lib2
          └── src
              ├── lib1
              │   └── src
              │       └── lib1.py
              └── lib2.py
```

With each import the level of nesting increases. Not only that, there is
also a non-uniformity in the directory layout: the source code in the
owning repository is scattered counter-intuitively over different
directory levels, making it unnecessarily complex to find files. These
problems are inherent the moment a repository starts having
subdirectories.
Such problems vanish when we restructure the repositories slightly and
then import each directly into the owning repository's root directory,
like so:

```
  lib1
  └── lib1
      └── src
          └── lib1.py
```

```
  lib2
  ├── lib1
  │   └── src
  │       └── lib1.py
  └── lib2
      └── src
          └── lib2.py
```

```
  app
  ├── app
  │   └── src
  │       └── app.py
  ├── lib1
  │   └── src
  │       └── lib1.py
  └── lib2
      └── src
          └── lib2.py
```

Now an interesting question arises: since the root name space of the
owning repository is shared, how are conflicts handled? The answer is
simple: the last import will take precedence and applied are the changes
from the current state of the owning repository to one where the subrepo
to import is at the desired state.

This approach also solves another otherwise inherent problem, namely
that if each subrepo pulls in its dependencies and two subrepos have the
same dependency, the source code of this last dependency will reside in
the repository at two places. From a logical point of view that is not
necessary a problem. However, if one considers how the module systems of
a variety of languages or their compilers/interpreters work it becomes
apparent that one of the two is effectively dead code: the path to each
subrepo has to be registered somewhere and this path will be searched
for a match during compile or run time. Yet, only the first match that
is found is used. This constraint in turn implies that both versions of
the subrepo need to be "compatible" if they are to be used in a common
application and we must be able to agree on using a single version.

Extending the example from before with a third library, 'lib3' that
depends on 'lib1' as well, and making 'app' require 'lib3' in addition
to 'lib2', we get away with the following structure:

```
  app
  ├── app
  │   └── src
  │       └── app.py
  ├── lib1
  │   └── src
  │       └── lib1.py
  ├── lib2
  │   └── src
  │       └── lib2.py
  └── lib3
      └── src
          └── lib3.py
```

Here, 'lib1' is used by both 'lib2' and 'lib3' without the need to have
a private copy in each. By design, it must be compatible with both.


Installation
------------

In order to run **git-subrepo** the
[cleanup](https://github.com/d-e-s-o/cleanup),
[execute](https://github.com/d-e-s-o/execute), and
[argcomp](https://github.com/d-e-s-o/argcomp) Python modules (contained
in the repository in compatible and tested versions) need to be
accessible by Python (typically by installing them in a directory listed
in ``PYTHONPATH`` or adjusting the latter to point to each of them).

All that has to be done in addition is to make the script executable and
to link it symbolically (or copy/move) into a directory contained in the
``PATH`` environment variable. Usually, one also wants to rename it to
not contain the .py extension anymore.

**git-subrepo** comes with full tab completion support for all commands,
options, and arguments of the same (a feature currently only tested with
bash(1)). It ships with a file providing the completion function that
has to be sourced in the shell of interest. In typical installations,
this file would be loaded in one of the shell initialization files,
``~/.bashrc``, for example.


Support
-------

The module is tested with Python 3. There is no work going on to
ensure compatibility with Python 2.
