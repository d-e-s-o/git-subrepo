# __init__.py

#/***************************************************************************
# *   Copyright (C) 2014,2016 Daniel Mueller (deso@posteo.net)              *
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

"""Initialization file of the deso.execute.test module."""


def allTests():
  """Retrieve a test suite containing all tests."""
  from os.path import (
    dirname,
  )
  from unittest import (
    TestLoader,
    TestSuite,
  )

  # Explicitly load all tests by name and not using a single discovery
  # to be able to easily deselect parts.
  tests = [
    "testExecute.py",
    "testUtil.py",
  ]

  loader = TestLoader()
  directory = dirname(__file__)
  suites = [loader.discover(directory, pattern=test) for test in tests]
  return TestSuite(suites)
