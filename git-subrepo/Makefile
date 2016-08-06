# Makefile

#/***************************************************************************
# *   Copyright (C) 2015-2016 Daniel Mueller (deso@posteo.net)              *
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

ROOT := $(shell pwd)/..
PYTHONPATH := "$(ROOT)/cleanup/src/:$(ROOT)/execute/src/:$(ROOT)/git-repo/src:$(ROOT)/git-subrepo/src:${PYTHONPATH}"


.PHONY: test
test:
	@PYTHONPATH="$(PYTHONPATH)"\
	 PYTHONDONTWRITEBYTECODE=1\
		python -m unittest --verbose --buffer deso.git.subrepo.test.allTests


.PHONY: %
%:
	@echo "Running deso.git.subrepo.test.testGitSubrepo.TestGitSubrepo.$@ ..."
	@PYTHONPATH="$(PYTHONPATH)"\
	 PYTHONDONTWRITEBYTECODE=1\
		python -m unittest --verbose --buffer deso.git.subrepo.test.testGitSubrepo.TestGitSubrepo.$@
