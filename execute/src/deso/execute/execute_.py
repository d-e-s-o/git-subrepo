# execute_.py

#/***************************************************************************
# *   Copyright (C) 2014-2015 Daniel Mueller (deso@posteo.net)              *
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

"""Functions for command execution.

  A command in our sense is a list of strings. The first element
  typically contains the absolute path of the executable to invoke and
  subsequent elements act as arguments being supplied.
  In various scenarios a single command is not enough to accomplish a
  job. To that end, there are two forms in which multiple commands can
  be arranged. The first, the pipeline, is a list of commands. A
  pipeline represents a sequence of commands where the output of the
  previous command is supplied as the input of the next one.
  The second one, a spring, is similar to a pipeline except for the
  first element which is a list of commands itself. The idea is that
  this first set of commands is executed in a serial fashion and the
  output is accumulated and supplied to the remaining commands (which,
  in turn, can be regarded as a pipeline.

  A sample of a pipeline is:
  [
    ['/bin/cat', '/tmp/input'],
    ['/bin/tr', 'a', 'a'],
    ['/bin/dd', 'of=/tmp/output'],
  ]

  Consequently, a spring could look like:
  [
    [['/bin/cat', '/tmp/input1'], ['/bin/cat', '/tmp/input2']],
    ['/bin/tr', 'a', 'a'],
    ['/bin/dd', 'of=/tmp/output'],
  ]
"""

from deso.cleanup import (
  defer,
)
from os import (
  O_RDWR,
  O_CLOEXEC,
  _exit,
  close as close_,
  devnull,
  dup2,
  execv,
  execve,
  fork,
  open as open_,
  pipe2,
  read,
  waitpid as waitpid_,
  write,
  WIFCONTINUED,
  WIFEXITED,
  WIFSIGNALED,
  WIFSTOPPED,
  WEXITSTATUS,
  WTERMSIG,
)
from select import (
  PIPE_BUF,
  POLLERR,
  POLLHUP,
  POLLIN,
  POLLNVAL,
  POLLOUT,
  POLLPRI,
  poll,
)
from sys import (
  stderr as stderr_,
  stdin as stdin_,
  stdout as stdout_,
)


class ProcessError(ChildProcessError):
  """A class enhancing OSError with proper attributes for our use case.

    The OSError attributes errno, filename, and filename2 do not really
    describe our use case. Most importantly, however, OSError does not
    interpret the filename arguments in any way, meaning newline
    characters will be printed directly as '\n' instead of resulting in
    a line break.
  """
  def __init__(self, status, name, stderr=None):
    super().__init__()

    # POSIX let's us have an error range of 8 bits. We do not want to
    # enforce any policy here, so even allow 0. Although it does not
    # make much sense to have that in an error class. Note that we allow
    # negative values equally well, as long as they do not cause an
    # underflow resulting in an effective return code of 0.
    assert -256 < status and status < 256, status

    self._status = status
    self._name = name
    self._stderr = stderr


  def __str__(self):
    """Convert the error into a human readable string."""
    s = "[Status {status:d}] {name}"
    if self._stderr:
      s += ": '{stderr}'"

    # Note that even if _stderr is None (and the string does not contain
    # the {stderr} string) we can apply the formatting for this key
    # anyways.
    s = s.format(status=self._status,
                 name=self._name,
                 stderr=self._stderr)
    return s


  @property
  def status(self):
    """Retrieve the status code of the failed process."""
    return self._status


  @property
  def name(self):
    """Retrieve the name/command of the process that failed."""
    return self._name


  @property
  def stderr(self):
    """Retrieve the stderr output, if any, of the process that failed."""
    return self._stderr


def _exec(*args, env=None):
  """Convenience wrapper around the set of exec* functions."""
  # We do not use the exec*p* set of execution functions here, although
  # that might be tempting. The reason is that by enforcing users to
  # specify the full path of an executable we basically force them to
  # use the findCommand function (or some other means to acquire the
  # full path) and, hence, make them think about what happens when this
  # command is not available. This is generally a good thing because
  # problems are caught earlier.
  if env is None:
    execv(args[0], list(args))
  else:
    execve(args[0], list(args), env)


def _waitpid(pid):
  """Convenience wrapper around the original waitpid invocation."""
  # 0 and -1 trigger a different behavior in waitpid. We disallow those
  # values.
  assert pid > 0

  while True:
    pid_, status = waitpid_(pid, 0)
    assert pid_ == pid

    if WIFEXITED(status):
      return WEXITSTATUS(status)
    elif WIFSIGNALED(status):
      # Signals are usually represented as the negated signal number.
      return -WTERMSIG(status)
    elif WIFSTOPPED(status) or WIFCONTINUED(status):
      # In our current usage scenarios we can simply ignore SIGSTOP and
      # SIGCONT by restarting the wait.
      continue
    else:
      assert False
      return 1


def execute(*args, env=None, stdin=None, stdout=None, stderr=b""):
  """Execute a program synchronously."""
  # Note that 'args' is a tuple. We do not want that so explicitly
  # convert it into a list. Then create another list out of this one to
  # effectively have a pipeline.
  return pipeline([list(args)], env, stdin, stdout, stderr)


def _pipeline(commands, env, fd_in, fd_out, fd_err):
  """Run a series of commands connected by their stdout/stdin."""
  pids = []
  first = True

  for i, command in enumerate(commands):
    last = i == len(commands) - 1

    # If there are more commands upcoming then we need to set up a pipe.
    if not last:
      fd_in_new, fd_out_new = pipe2(O_CLOEXEC)

    pids += [fork()]
    child = pids[-1] == 0

    if child:
      if not first:
        # Establish communication channel with previous process.
        dup2(fd_in_old, stdin_.fileno())
        close_(fd_in_old)
        close_(fd_out_old)
      else:
        dup2(fd_in, stdin_.fileno())

      if not last:
        # Establish communication channel with next process.
        close_(fd_in_new)
        dup2(fd_out_new, stdout_.fileno())
        close_(fd_out_new)
      else:
        dup2(fd_out, stdout_.fileno())

      # Stderr is redirected for all commands in the pipeline because each
      # process' output should be rerouted and stderr is not affected by
      # the pipe between the processes in any way.
      dup2(fd_err, stderr_.fileno())

      _exec(*command, env=env)
      # This statement should never be reached: either exec fails in
      # which case a Python exception should be raised or the program is
      # started in which case this process' image is overwritten anyway.
      # Keep it to be absolutely safe.
      _exit(-1)
    else:
      if not first:
        close_(fd_in_old)
        close_(fd_out_old)
      else:
        first = False

      # If there are further commands then update the "old" pipe file
      # descriptors for future reference.
      if not last:
        fd_in_old = fd_in_new
        fd_out_old = fd_out_new

  return pids


def formatCommands(commands):
  """Convert a command, pipeline, or spring into a string."""
  def depth(l, d):
    """Determine the maximum nesting depth of lists."""
    if not isinstance(l, list):
      return d

    return max(map(lambda x: depth(x, d+1), l))

  def transform(commands, depth):
    """Transform a command or command list into a string."""
    lookup = [
      lambda x: " ".join(x),
      lambda x: " ".join(x),
      lambda x: " | ".join(x),
      lambda x: "(%s)" % " + ".join(x),
    ]
    return lookup[depth](commands)

  def stringify(commands, depth_now, depth_max):
    """Convert a command or command list into a string.

      We retrieve the pre-determined maximum nesting depth of the lists
      in our command set as input parameter and use that as the base to
      determine how to properly format the commands at each level.
    """
    # We have reached a string (or something else "atomic" in our
    # sense). We can stop here.
    if not isinstance(commands, list):
      return commands, depth_now

    strings = []
    d = depth_max

    for command in commands:
      string, depth = stringify(command, depth_now + 1, depth_max)
      strings += [string]
      d = min(depth, d)

    d = depth_max - d
    return transform(strings, d), d

  # We need to calculate the maximum depth of the command list given.
  # Based on this knowledge we can later relate the current depth to the
  # maximum depth in order to decide how to format a command or list of
  # commands.
  d = depth(commands, 0)
  # Now convert the command list into a correctly formatted string.
  s, _ = stringify(commands, 0, d)
  return s


def _wait(pids, commands, data_err, status=0, failed=None):
  """Wait for all processes represented by a list of process IDs.

    Although it might not seem necessary to wait for any other than the
    last process, we wait for all of them. The main reason is that we
    want to clean up all left-over zombie processes.

    Notes:
      We also check the return code of every child process and raise an
      error in case one of them did not succeed. This behavior differs
      from that of bash, for instance, where no return code checking is
      performed for all but the last process in the chain. This approach
      is considered more safe in the face of failures. That is, unless
      there is some form of error checking being performed on the stream
      being passed through a pipe, there is no way for the last command
      to notice a failure of a previous command. As such, it might
      succeed although not the entire input/output was processed
      overall (because a previous command failed in an intermediate
      stage). We set a high priority on reporting potential failures to
      users.
  """
  # In case of an error during execution of a spring (no error will be
  # detected that early in a pipeline) we might have less pids to wait
  # for than commands passed in because not all commands were executed
  # yet. Also note that although 'commands' might be a spring (i.e.,
  # contain a list of commands itself), the number of pids cannot exceed
  # the top-level length of this list because inside of a spring we
  # already execute (and wait for) all but the last of these "internal"
  # commands.
  assert len(pids) <= len(commands)
  # If an error status is set we also must have received the failed
  # command.
  assert status == 0 or len(failed) > 0

  for i, pid in enumerate(pids):
    this_status = _waitpid(pid)
    if this_status != 0 and status == 0:
      # Only remember the first failure here, then continue clean up.
      failed = formatCommands([commands[i]])
      status = this_status

  if status != 0:
    error = data_err.decode("utf-8") if data_err else None
    raise ProcessError(status, failed, error)


def _write(data):
  """Write data to one of our pipe dicts."""
  # Note that we are only guaranteed to write PIPE_BUF bytes at a time
  # without blocking.
  count = write(data["out"], data["data"][:PIPE_BUF])

  data["data"] = data["data"][count:]
  return not data["data"]


def _read(data):
  """Read data from one of our pipe dicts."""
  # We use 4 KiB as the maximum buffer size. This is quite a bit smaller
  # than the 64 KiB that /bin/cat apparently uses (and that seem to be
  # the default buffer size of pipes on some systems) but we expect way
  # less high-volume data to be read here (it should be piped directly
  # to the next process instead of going through a Python buffer). It
  # still is kind of an arbitrary value. We could also start of with a
  # small(er) value and increase it with every iteration or, if
  # performance measurements suggest it, just pick a larger value
  # altogether.
  buf = read(data["in"], 4 * 1024)
  if buf:
    data["data"] += buf
    return False
  else:
    return True


# The event mask for which to poll for a write channel (such as stdin).
_OUT = POLLOUT | POLLHUP | POLLERR
# The event mask for which to poll for a read channel (such as stdout).
_IN = POLLPRI | POLLHUP | POLLIN


def eventToString(events):
  """Convert an event set to a human readable string."""
  errors = {
    POLLERR:  "ERR",
    POLLHUP:  "HUP",
    POLLIN:   "IN",
    POLLNVAL: "NVAL",
    POLLOUT:  "OUT",
    POLLPRI:  "PRI",
  }
  return "|".join([v for k, v in errors.items() if k & events])


class _PipelineFileDescriptors:
  """This class manages file descriptors for use with any pipeline of commands."""
  def __init__(self, later, here, stdin, stdout, stderr):
    """Initialize the pipe infrastructure on demand."""
    # We got two defer objects here. So here is how it works: Some of
    # the resources should be freed latest after the pipeline finished
    # its work. That is what 'here' is for. Others need to be freed
    # later (by 'later'), think, the file descriptors we need to poll.
    def pipeWrite(argument, data):
      """Setup a pipe for writing data."""
      data["in"], data["out"] = pipe2(O_CLOEXEC)
      data["data"] = argument
      data["close"] = later.defer(close_, data["out"])
      here.defer(close_, data["in"])

    def pipeRead(argument, data):
      """Setup a pipe for reading data."""
      data["in"], data["out"] = pipe2(O_CLOEXEC)
      data["data"] = argument
      data["close"] = later.defer(close_, data["in"])
      here.defer(close_, data["out"])

    # By default we are blockable, i.e., we invoke poll without a
    # timeout. This property has to be an attribute of the object
    # because we might want to change it during an invocation of the
    # poll method that yielded.
    self._timeout = None

    # We need three dict objects, each representing one of the available
    # data channels. Depending on whether the channel is actually used
    # or not they get populated on demand or stay empty, respectively.
    self._stdin = {}
    self._stdout = {}
    self._stderr = {}

    # We want to redirect all file descriptors that we do not want
    # anything from to /dev/null. But we only want to open the latter
    # in case someone really requires it, i.e., if not all three
    # channels are connected to pipes or user-defined file descriptors
    # anyway.
    if stdin is None or stdout is None or stderr is None:
      null = open_(devnull, O_RDWR | O_CLOEXEC)
      here.defer(close_, null)

      if stdin is None:
        stdin = null
      if stdout is None:
        stdout = null
      if stderr is None:
        stderr = null

    # At this point stdin, stdout, and stderr are all either a valid
    # file descriptor (i.e., of type int) or some data.

    # Now, depending on whether we got passed in a file descriptor (an
    # object of type int), remember it or create a pipe to read or write
    # data.
    if isinstance(stdin, int):
      self._file_in = stdin
    else:
      pipeWrite(stdin, self._stdin)

    if isinstance(stdout, int):
      self._file_out = stdout
    else:
      pipeRead(stdout, self._stdout)

    if isinstance(stderr, int):
      self._file_err = stderr
    else:
      pipeRead(stderr, self._stderr)


  def poll(self):
    """Poll the file pipe descriptors for more data until each indicated that it is done.

      There are two modes in which this method can work. In blocking
      mode (the default), we will block waiting for new data to become
      available for processing. In non-blocking mode we yield if no more
      data is currently available but can resume polling later. The
      blocking mode can be influenced via the blockable member function.
      Note that this change can even happen after we yielded execution
      in the non blockable case.

      Note that because we require non-blocking behavior in order to
      support springs, this function uses 'yield' instead of 'return'
      for conveying any results to the caller (even in the blockable
      case). The reason is a little Python oddity where a function that
      yields anything (even in a path that is never reached), always
      implicitly returns a generator rather as opposed to a "direct"
      result.
    """
    def pollWrite(data):
      """Conditionally set up polling for write events."""
      if data:
        poll_.register(data["out"], _OUT)
        data["unreg"] = d.defer(poll_.unregister, data["out"])
        polls[data["out"]] = data

    def pollRead(data):
      """Conditionally set up polling for read events."""
      if data:
        poll_.register(data["in"], _IN)
        data["unreg"] = d.defer(poll_.unregister, data["in"])
        polls[data["in"]] = data

    # We need a poll object if we want to send any data to stdin or want
    # to receive any data from stdout or stderr.
    if self._stdin or self._stdout or self._stderr:
      poll_ = poll()

    # We use a dictionary here to elegantly look up the entry (which is,
    # another dictionary) for the respective file descriptor we received
    # an event for and to decide if we need to poll more.
    polls = {}

    with defer() as d:
      # Set up the polling infrastructure.
      pollWrite(self._stdin)
      pollRead(self._stdout)
      pollRead(self._stderr)

      while polls:
        events = poll_.poll(self._timeout)

        for fd, event in events:
          close = False
          data = polls[fd]

          # Note that reading (POLLIN or POLLPRI) and writing (POLLOUT)
          # are mutually exclusive operations on a pipe. All can be
          # combined with a HUP or with other errors (POLLERR or
          # POLLNVAL; even though we did not subscribe to them), though.
          if event & POLLOUT:
            close = _write(data)
          elif event & POLLIN or event & POLLPRI:
            if event & POLLHUP:
              # In case we received a combination of a data-is-available
              # and a HUP event we need to make sure that we flush the
              # entire pipe buffer before we stop the polling. Otherwise
              # we might leave data unread that was successfully sent to
              # us.
              # Note that from a logical point of view this problem
              # occurs only in the receive case. In the write case we
              # have full control over the file descriptor ourselves and
              # if the remote side closes its part there is no point in
              # sending any more data.
              while not _read(data):
                pass
            else:
              close = _read(data)

          # We explicitly (and early, compared to the defers we
          # scheduled previously) close the file descriptor on POLLHUP,
          # when we received EOF (for reading), or run out of data to
          # send (for writing).
          if event & POLLHUP or close:
            data["close"]()
            data["unreg"]()
            del polls[fd]

          # All error codes are reported to clients such that they can
          # deal with potentially incomplete data.
          if event & (POLLERR | POLLNVAL):
            string = eventToString(event)
            error = "Error while polling for new data, event: {s} ({e})"
            error = error.format(s=string, e=event)
            raise ConnectionError(error)

        if self._timeout is not None:
          yield

      yield


  def blockable(self, can_block):
    """Set whether or not polling is allowed to block."""
    self._timeout = None if can_block else 0


  def stdin(self):
    """Retrieve the stdin file descriptor ready to be handed to a process."""
    return self._stdin["in"] if self._stdin else self._file_in


  def stdout(self):
    """Retrieve the stdout file descriptor ready to be handed to a process."""
    return self._stdout["out"] if self._stdout else self._file_out


  def stderr(self):
    """Retrieve the stderr file descriptor ready to be handed to a process."""
    return self._stderr["out"] if self._stderr else self._file_err


  def data(self):
    """Retrieve the data polled so far as a (stdout, stderr) tuple."""
    return self._stdout["data"] if self._stdout else b"",\
           self._stderr["data"] if self._stderr else b""


def pipeline(commands, env=None, stdin=None, stdout=None, stderr=b""):
  """Execute a pipeline, supplying the given data to stdin and reading from stdout & stderr.

    This function executes a pipeline of commands and connects their
    stdin and stdout file descriptors as desired. All keyword parameters
    can be either None (in which case they get implicitly redirected
    to/from a null device), a valid file descriptor, or some data. In
    case data is given (which should be a byte-like object) it will be
    fed into the standard input of the first command (in case of stdin)
    or be used as the initial buffer content of data to read (stdout and
    stderr) of the last command (which means all actually read data will
    just be appended).
  """
  with defer() as later:
    with defer() as here:
      # Set up the file descriptors to pass to our execution pipeline.
      fds = _PipelineFileDescriptors(later, here, stdin, stdout, stderr)

      # Finally execute our pipeline and pass in the prepared file
      # descriptors to use.
      pids = _pipeline(commands, env, fds.stdin(), fds.stdout(), fds.stderr())

    for _ in fds.poll():
      pass

    data_out, data_err = fds.data()

  # We have read or written all data that was available, the last thing
  # to do is to wait for all the processes to finish and to clean them
  # up.
  _wait(pids, commands, data_err)
  return data_out, data_err


def _spring(commands, env, fds):
  """Execute a series of commands and accumulate their output to a single destination.

    Due to the nature of springs control flow here is a bit tricky. We
    want to execute the first set of commands in a serial manner.
    However, we need to get the remaining processes running in order to
    not stall everything (because nobody consumes any of the output).
    Furthermore, we need to poll for incoming data to be processed. That
    in turn is a process that must not block. Last but not least,
    because the first set of commands runs in a serial manner, we need
    to wait for each process to finish, which might be done with an
    error code. In such a case we return early but still let the _wait
    function handle the error propagation.
  """
  def pollData(poller):
    """Poll for new data."""
    # The poller might become exhausted here under certain
    # circumstances. We do not care, it will always quit with an
    # StopIteration exception which we kindly ignore.
    try:
      next(poller)
    except StopIteration:
      pass

  assert len(commands) > 0, commands
  assert len(commands[0]) > 0, commands
  assert isinstance(commands[0][0], list), commands

  pids = []
  first = True
  status = 0
  failed = None
  poller = None

  fd_in = fds.stdin()
  fd_out = fds.stdout()
  fd_err = fds.stderr()

  # A spring consists of a number of commands executed in a serial
  # fashion with their output accumulated to a single destination and a
  # (possibly empty) pipeline that processes the output of the spring.
  spring_cmds = commands[0]
  pipe_cmds = commands[1:]
  pipe_len = len(pipe_cmds)

  # We need a pipe to connect the spring's output with the pipeline's
  # input, if there is a pipeline following the spring.
  if pipe_cmds:
    fd_in_new, fd_out_new = pipe2(O_CLOEXEC)
  else:
    fd_in_new = fd_in
    fd_out_new = fd_out

  for i, command in enumerate(spring_cmds):
    last = i == len(spring_cmds) - 1

    pid = fork()
    child = pid == 0

    if child:
      dup2(fd_in, stdin_.fileno())
      dup2(fd_out_new, stdout_.fileno())
      dup2(fd_err, stderr_.fileno())

      if pipe_cmds:
        close_(fd_in_new)
        close_(fd_out_new)

      _exec(*command, env=env)
      _exit(-1)
    else:
      # After we started the first command from the spring we need to
      # make sure that there is a consumer of the output data. If there
      # were none, the new process could potentially block forever
      # trying to write data. To that end, start the remaining commands
      # in the form of a pipeline.
      if first:
        if pipe_cmds:
          pids += _pipeline(pipe_cmds, env, fd_in_new, fd_out, fd_err)

        first = False

      # The pipeline could still be stalled at some point if there is no
      # final consumer of the data. We are required here to poll for
      # data in order to prevent starvation.
      if not poller:
        poller = fds.poll()
      else:
        pollData(poller)

      if not last:
        status = _waitpid(pid)
        if status != 0:
          # One command failed. Do not start any more commands and
          # indicate failure to the caller. He may try reading data from
          # stderr (if any and if reading from it is enabled) and will
          # raise an exception.
          failed = formatCommands(command)
          break
      else:
        # If we reached the last command in the spring we can just have
        # it run in background and wait for it to finish later on -- no
        # more serialization is required at that point.
        # We insert the pid just before the pids for the pipeline. The
        # pipeline is started early but it runs the longest (because it
        # processes the output of the spring) and we must keep this
        # order in the pid list.
        pids[-pipe_len:-pipe_len] = [pid]

  if pipe_cmds:
    close_(fd_in_new)
    close_(fd_out_new)

  assert poller
  return pids, poller, status, failed


def spring(commands, env=None, stdout=None, stderr=b""):
  """Execute a series of commands and accumulate their output to a single destination."""
  with defer() as later:
    with defer() as here:
      # A spring never receives any input from stdin, i.e., we always
      # want it to be redirected from /dev/null.
      fds = _PipelineFileDescriptors(later, here, None, stdout, stderr)
      # When running the spring we need to alternate between spawning
      # new processes and polling for data. In that scenario, we do not
      # want the polling to block until we started processes for all
      # commands passed in.
      fds.blockable(False)

      # Finally execute our spring and pass in the prepared file
      # descriptors to use.
      pids, poller, status, failed = _spring(commands, env, fds)

    # We started all processes and will wait for them to finish. From
    # now on we can allow any invocation of poll to block.
    fds.blockable(True)

    # Poll until there is no more data.
    for _ in poller:
      pass

    data_out, data_err = fds.data()

  _wait(pids, commands, data_err, status=status, failed=failed)
  return data_out, data_err
