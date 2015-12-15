# testExecute.py

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

"""Test command execution wrappers."""

from deso.execute import (
  execute as execute_,
  findCommand,
  formatCommands,
  pipeline as pipeline_,
  ProcessError,
  spring as spring_
)
from deso.execute.execute_ import (
  eventToString,
)
from os import (
  remove,
)
from os.path import (
  isfile,
)
from select import (
  POLLERR,
  POLLHUP,
  POLLIN,
  POLLNVAL,
  POLLOUT,
  POLLPRI,
)
from sys import (
  executable,
)
from tempfile import (
  mktemp,
  NamedTemporaryFile,
  TemporaryFile,
)
from textwrap import (
  dedent,
)
from unittest import (
  TestCase,
  main,
)


_TRUE = findCommand("true")
_FALSE = findCommand("false")
_ECHO = findCommand("echo")
_TOUCH = findCommand("touch")
_CAT = findCommand("cat")
_TR = findCommand("tr")
_DD = findCommand("dd")


def execute(*args, stdin=None, stdout=None, stderr=None):
  """Run a program with reading from stderr disabled by default."""
  return execute_(*args, stdin=stdin, stdout=stdout, stderr=stderr)


def pipeline(commands, stdin=None, stdout=None, stderr=None):
  """Run a pipeline with reading from stderr disabled by default."""
  return pipeline_(commands, stdin=stdin, stdout=stdout, stderr=stderr)


def spring(commands, stdout=None, stderr=None):
  """Run a spring with reading from stderr disabled by default."""
  return spring_(commands, stdout=stdout, stderr=stderr)


class TestExecute(TestCase):
  """A test case for command execution functionality."""
  def testProcessErrorNoStderr(self):
    """Verify that when not reading stderr output we get a rather generic error report."""
    tmp_file = mktemp()
    regex = r"^\[Status [0-9]+\] %s %s$" % (_CAT, tmp_file)

    with self.assertRaisesRegex(ProcessError, regex):
      # Do not read from stderr here.
      execute(_CAT, tmp_file)


  def testProcessErrorFormattingStderr(self):
    """Verify that the ProcessError class properly handles new lines."""
    tmp_file = mktemp()
    # Note that when using ChildProcessError the newline would not
    # appear as a true newline but rather as the actual text '\n' (i.e.,
    # \\n in a string). With ProcessError we are supposed to get a
    # properly interpreted newline.
    regex = r".*No such file or directory\n"

    with self.assertRaisesRegex(ProcessError, regex):
      execute(_CAT, tmp_file, stderr=b"")


  def testExecuteErrorEventToStringSingle(self):
    """Verify that our event to string conversion works as expected."""
    self.assertEqual(eventToString(POLLERR),  "ERR")
    self.assertEqual(eventToString(POLLHUP),  "HUP")
    self.assertEqual(eventToString(POLLIN),   "IN")
    self.assertEqual(eventToString(POLLNVAL), "NVAL")
    self.assertEqual(eventToString(POLLOUT),  "OUT")
    self.assertEqual(eventToString(POLLPRI),  "PRI")


  def testExecuteErrorEventToStringMultiple(self):
    """Verify that our event to string conversion works as expected."""
    # Note that we cannot say for sure what the order of the event codes
    # in the string will be, so we have to check for all possible
    # outcomes.
    s = eventToString(POLLERR | POLLHUP)
    self.assertTrue(s == "ERR|HUP" or s == "HUP|ERR", s)

    s = eventToString(POLLIN | POLLNVAL)
    self.assertTrue(s == "IN|NVAL" or s == "NVAL|IN", s)

    s = eventToString(POLLHUP | POLLOUT | POLLERR)
    self.assertTrue(s == "HUP|OUT|ERR" or
                    s == "HUP|ERR|OUT" or
                    s == "OUT|HUP|ERR" or
                    s == "OUT|ERR|HUP" or
                    s == "ERR|HUP|OUT" or
                    s == "ERR|OUT|HUP", s)


  def testExecuteAndNoOutput(self):
    """Test command execution and output retrieval for empty output."""
    output, _ = execute(_TRUE, stdout=b"")
    self.assertEqual(output, b"")


  def testExecuteAndOutput(self):
    """Test command execution and output retrieval."""
    output, _ = execute(_ECHO, "success", stdout=b"")
    self.assertEqual(output, b"success\n")


  def testExecuteAndRedirectInput(self):
    """Test command execution and input redirection."""
    with TemporaryFile() as file_:
      file_.write(b"success")
      file_.seek(0)

      out, _ = execute(_CAT, stdin=file_.fileno(), stdout=b"")
      self.assertEqual(out, b"success")


  def testExecuteAndRedirectOutput(self):
    """Test command execution and output redirection."""
    with TemporaryFile() as file_:
      execute(_ECHO, "success", stdout=file_.fileno())
      file_.seek(0)
      self.assertEqual(file_.read(), b"success\n")


  def testExecuteAndRedirectError(self):
    """Test command execution and error redirection."""
    path = mktemp()
    regex = r"No such file or directory"

    with TemporaryFile() as file_:
      with self.assertRaises(ProcessError):
        execute(_CAT, path, stderr=file_.fileno())

      file_.seek(0)
      self.assertRegex(file_.read().decode("utf-8"), regex)


  def testExecuteAndOutputMultipleLines(self):
    """Test command execution with multiple lines of output."""
    string = "first-line\nsuccess"
    output, _ = execute(_ECHO, string, stdout=b"")
    self.assertEqual(output, bytes(string + "\n", "utf-8"))


  def testExecuteAndInputOutput(self):
    """Test that we can redirect stdin and stdout at the same time."""
    output, _ = execute(_CAT, stdin=b"success", stdout=b"")
    self.assertEqual(output, b"success")


  def testExecuteRedirectAll(self):
    """Test that we can redirect stdin, stdout, and stderr at the same time."""
    out, err = execute(_DD, stdin=b"success", stdout=b"", stderr=b"")
    line1, line2, _ = err.decode("utf-8").splitlines()

    self.assertEqual(out, b"success")
    self.assertTrue(line1.endswith("records in"))
    self.assertTrue(line2.endswith("records out"))


  def testExecuteThrowsOnCommandFailure(self):
    """Verify that a failing command causes an exception to be raised."""
    with self.assertRaises(ProcessError):
      execute(_FALSE)


  def testExecuteThrowsAndReportsError(self):
    """Verify that a failing command's exception contains the stderr output."""
    path = mktemp()
    regex = r"No such file or directory"

    with self.assertRaises(AssertionError):
      # This command should fail the assertion because reading from
      # standard error is not turned on and as a result the error message
      # printed on stderr will not be contained in the ProcessError
      # error message.
      with self.assertRaisesRegex(ProcessError, regex):
        execute(_CAT, path)

    # When reading from stderr is turned on the exception must contain
    # the above phrase.
    with self.assertRaisesRegex(ProcessError, regex):
      execute(_CAT, path, stderr=b"")


  def testPipelineThrowsForFirstFailure(self):
    """Verify that if some commands fail in a pipeline, the error of the first is reported."""
    for cmd in [_FALSE, _TRUE]:
      # Note that mktemp does not create the file, it just returns a
      # file name unique at the time of the invocation.
      path = mktemp()
      regex = r"No such file or directory"

      # A pipeline of commands with one or two of them failing.
      commands = [
        [_ECHO, "test"],
        [_CAT, path],
        [cmd],
      ]

      with self.assertRaisesRegex(ProcessError, regex):
        pipeline(commands, stderr=b"")


  def testFormatCommands(self):
    """Test conversion of a series of commands into a string."""
    # Case 1) A single string that could potentially represent a
    #         command. Note that strictly speaking it is not a command
    #         in our sense and it could not be executed using the
    #         'execute' functionality the way it is. We merely support
    #         it because it "just works".
    self.assertEqual(formatCommands(_ECHO), _ECHO)

    # Case 2) A single command.
    command = [_ECHO, "test"]
    expected = "{echo} test".format(echo=_ECHO)
    self.assertEqual(formatCommands(command), expected)

    # Case 3) A very simplistic pipeline.
    commands = [
      [_ECHO, "test"],
      [_ECHO, "test2"],
    ]
    expected = "{echo} test | {echo} test2".format(echo=_ECHO)
    self.assertEqual(formatCommands(commands), expected)

    # Case 4) A more complex pipeline.
    commands = [
      [_ECHO, "test"],
      [_TR, "t", "z"],
      [_TR, "z", "t"],
    ]
    expected = "{echo} test | {tr} t z | {tr} z t"
    expected = expected.format(echo=_ECHO, tr=_TR)
    self.assertEqual(formatCommands(commands), expected)

    # Case 5) A spring without an additional pipeline after it.
    commands = [
      [["echo", "test"], ["echo", "test2"], ["echo", "test3"]],
    ]
    expected = "(echo test + echo test2 + echo test3)"
    expected = expected.format(echo=_ECHO)
    self.assertEqual(formatCommands(commands), expected)

    # Case 6) A fairly complex spring. Note that in addition to the
    #         spring part at the beginning we have another on in the
    #         middle. Such a set of command would not be able to execute
    #         properly using our 'spring' function, since this is a
    #         non-standard command set layout. Again, we support it
    #         because we would have to special case it in order to not
    #         support it.
    commands = [
      [["/bin/echo", "suaaerr"], ["/bin/echo", "yippie"], ["/bin/echo", "wohoo"]],
      ["/bin/tr", "a", "c"],
      ["/bin/tr", "r", "s"],
      [["/bin/echo", "suaaerr"], ["/bin/echo", "yippie"], ["/bin/echo", "wohoo"]],
      ["/bin/tr", "a", "a"],
    ]
    expected = "(/bin/echo suaaerr + /bin/echo yippie + /bin/echo wohoo) | " +\
               "/bin/tr a c | /bin/tr r s | " +\
               "(/bin/echo suaaerr + /bin/echo yippie + /bin/echo wohoo) | " +\
               "/bin/tr a a"
    self.assertEqual(formatCommands(commands), expected)


  def testPipelineSingleProgram(self):
    """Verify that a pipeline can run a single program."""
    path = mktemp()
    commands = [[_TOUCH, path]]

    self.assertFalse(isfile(path))
    pipeline(commands)
    self.assertTrue(isfile(path))

    remove(path)


  def testPipelineMultiplePrograms(self):
    """Verify that a pipeline can run two and more programs."""
    def doTest(intermediates):
      """Actually perform the test for a given pipeline depth."""
      tmp_file = mktemp()
      identity = [_TR, "a", "a"]
      commands = [
        [_ECHO, "test-abc-123"],
        [_DD, "of=%s" % tmp_file],
      ]

      commands[1:1] = [identity] * intermediates

      self.assertFalse(isfile(tmp_file))
      pipeline(commands)
      self.assertTrue(isfile(tmp_file))

      remove(tmp_file)

    for i in range(0, 4):
      doTest(i)


  def testPipelineWithRead(self):
    """Test execution of a pipeline and reading the output."""
    commands = [
      [_ECHO, "suaaerr"],
      [_TR, "a", "c"],
      [_TR, "r", "s"],
    ]
    output, _ = pipeline(commands, stdout=b"")

    self.assertEqual(output, b"success\n")


  def testPipelineWithExcessiveRead(self):
    """Verify that we do not deadlock when receiving large quantities of data."""
    megabyte = 1024 * 1024
    megabytes = 8
    commands = []
    data = b"a" * megabytes * megabyte

    # Test with 1 to 3 programs in the pipeline.
    for _ in range(3):
      commands += [[_DD]]
      # TODO: The following does not work and fails with "[Errno 32]
      #       Broken Pipe". Find out why. Some people suggest it might
      #       be a problem on the Python side. Need to understand in
      #       either case. Note that adding 'iflag=fullblock' to the dd
      #       command solves the issue.
      #commands += [[_DD, 'bs=%s' % megabyte, 'count=%s' % megabytes]]

      out, _ = pipeline(commands, stdin=data, stdout=b"")
      self.assertEqual(len(out), len(data))


  def testPipelineWithFailingCommand(self):
    """Verify that a failing command in a pipeline fails the entire execution."""
    identity = [_TR, "a", "a"]
    commands = [
      [_ECHO, "test-abc-123"],
      identity,
      [_FALSE],
    ]

    # Run twice, once with failing command at the end and once somewhere
    # in the middle.
    for _ in range(2):
      with self.assertRaises(ProcessError):
        pipeline(commands)

      commands += [identity]


  def testSpringNoOutput(self):
    """Execute a spring without capturing its output."""
    commands = [[_ECHO, "test1"], [_ECHO, "test2"]]

    out, _ = spring([commands])
    self.assertEqual(out, b"")


  def testSpringReadOut(self):
    """Execute a spring and verify that it produces the expected output."""
    # TODO: This test occassionally fails. Find out why.
    # ======================================================================
    # FAIL: testSpringReadOut (testExecute.TestExecute)
    # Execute a spring and verify that it produces the expected output.
    # ----------------------------------------------------------------------
    # Traceback (most recent call last):
    #   File "src/btrfs/test/testExecute.py", line 414, in testSpringReadOut
    #     self.assertEqual(out, bytes(expected, 'utf-8'))
    # AssertionError: b'def\nabc\nghi\njkl\nmno\npqr\n' != b'abc\ndef\nghi\njkl\nmno\npqr\n'
    commands = []

    for text in ["abc", "def", "ghi", "jkl", "mno", "pqr", "stu", "vwx", "yz"]:
      commands += [[_ECHO, text]]

      out, _ = spring([commands], stdout=b"")
      expected = "\n".join([t for _, t in commands]) + "\n"
      self.assertEqual(out, bytes(expected, "utf-8"))


  def testSpringReadWithPipeline(self):
    """Execute a spring with a varying pipeline depth following it."""
    identity = [_TR, "a", "a"]
    commands = [
      [[_ECHO, "suaaerr"], [_ECHO, "yippie"], [_ECHO, "wohoo"]],
      [_TR, "a", "c"],
      [_TR, "r", "s"],
    ]

    for _ in range(5):
      commands += [identity]
      output, _ = spring(commands, stdout=b"")

      self.assertEqual(output, b"success\nyippie\nwohoo\n")


  def testSpringError(self):
    """Verify a spring behaves correctly in the face of a command error."""
    path = mktemp()
    regex = r"%s.*No such file or directory" % _CAT
    benign = [_ECHO, "test2"]
    faulty = [_CAT, path]

    for cmd1, cmd2 in [(benign, faulty), (faulty, benign)]:
      commands = [
        [[_ECHO, "test1"], cmd1],
        cmd2,
      ]

      with self.assertRaisesRegex(ProcessError, regex):
        spring(commands, stderr=b"")


  def testSpringWriteFileDescriptor(self):
    """Execute a spring and redirect the accumulated output into a file."""
    # It is important to disable buffering here, otherwise we might not
    # be able to read back the data we just wrote when referencing the
    # file by name (as opposed to the file descriptor).
    with NamedTemporaryFile(buffering=0) as file_in1,\
         NamedTemporaryFile(buffering=0) as file_in2,\
         NamedTemporaryFile(buffering=0) as file_in3,\
         NamedTemporaryFile(buffering=0) as file_out:
      file_in1.write(b"file1\n")
      file_in2.write(b"file2\n")
      file_in3.write(b"file3")

      commands = [
        [_CAT, file_in1.name],
        [_CAT, file_in2.name],
        [_CAT, file_in3.name],
      ]
      spring([commands], stdout=file_out.fileno())

      expected = b"file1\nfile2\nfile3"
      file_out.seek(0)
      self.assertEqual(file_out.read(), expected)


  # TODO: We need more tests for the spring functionality, especially
  #       with respect to the return values.


  def testBackgroundTaskIsWaited(self):
    """Verify that if a started program forks we can see its output as well."""
    def runAndRead(close=False):
      """Run a script and read its output."""
      script = bytes(dedent("""\
        from os import close, fork
        from sys import stdout
        from time import sleep

        pid = fork()
        if pid == 0:
          {cmd}
          sleep(1)
          print("CHILD")
        else:
          print("PARENT")
      """).format(cmd="close(stdout.fileno())" if close else ""), "utf-8")

      stdout, _ = execute(executable, stdin=script, stdout=b"")
      return stdout

    stdout = runAndRead()
    self.assertTrue(stdout == b"PARENT\nCHILD\n" or
                    stdout == b"CHILD\nPARENT\n", stdout)

    stdout = runAndRead(close=True)
    self.assertTrue(stdout == b"PARENT\n", stdout)


if __name__ == "__main__":
  main()
