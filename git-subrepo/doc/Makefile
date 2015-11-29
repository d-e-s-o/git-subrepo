# Makefile

#/***************************************************************************
# *   Copyright (C) 2015 Daniel Mueller (deso@posteo.net)                   *
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

TXT := git-subrepo.txt
MAN := git-subrepo.1
XML := git-subrepo.xml
HTML := git-subrepo.html

.PHONY: doc
doc: $(MAN) $(XML) $(HTML)

$(HTML): $(TXT)
	asciidoc -a git-asciidoc-no-roff -f asciidoc.conf -b xhtml11 -d manpage -o $@ $<

$(XML): $(TXT)
	asciidoc -a git-asciidoc-no-roff -f asciidoc.conf -b docbook -d manpage -o $@ $<

$(MAN): $(XML)
	xmlto -m manpage-normal.xsl man $<
