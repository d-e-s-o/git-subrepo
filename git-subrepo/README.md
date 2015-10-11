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

**git-subrepo** offers two commands for working with subrepos: 'add' and
'update'. In order to import a new subrepo, the 'add' command can be
used. A subrepo captures the state of a remote repository at a specific
commit. As such, the first thing to do is to have an up-to-date state of
the remote repository of interest. If the remote repository is not know
yet, it can be added like so:

``$ git remote add -f lib <url>``

This command would add a remote repository called 'lib' referencing the
``git`` repository found at '<url>'. Please refer to the git-remote(1)
manual for more information.

Using a remote repository, a new subrepo can be created:

``$ git subrepo add lib src/lib master``

The above command imports the source code from the remote repository
'lib' at commit 'master' (which in that case likely references a branch)
into the directory 'src/lib/' (relative to the importing repository's
root).

Similarly, a subrepo can be updated to reference the state of a remote
repository at a different revision:

``$ git subrepo update lib src/lib feature``

After invocation of this command the source code below 'src/lib' will
represent the state of 'lib' at commit 'feature'.


Installation
------------

Being a simple script, there are multiple ways to perform an
installation. If you are using [Gentoo Linux](https://www.gentoo.org/),
there is an [ebuild](https://github.com/d-e-s-o/git-subrepo-ebuild)
available that can be used directly.

In the general case, all that has to be done is to make the script
executable and to link it symbolically (or copy/move) into a directory
contained in the ``PATH`` environment variable. Usually, one also wants
to rename it to not contain the .py extension anymore.


Support
-------

The module is tested with Python 3. There is no work going on to
ensure compatibility with Python 2.
