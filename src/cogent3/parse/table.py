#!/usr/bin/env python

import csv
import pickle

from collections.abc import Callable
from gzip import open as open_

from .record_finder import is_empty


__author__ = "Gavin Huttley"
__copyright__ = "Copyright 2007-2019, The Cogent Project"
__credits__ = ["Gavin Huttley"]
__license__ = "BSD-3"
__version__ = "2019.9.13a"
__maintainer__ = "Gavin Huttley"
__email__ = "gavin.huttley@anu.edu.au"
__status__ = "Production"


class ConvertFields(object):
    """converter for input data to Table"""

    def __init__(self, conversion, by_column=True):
        """handles conversions of columns or lines

        Parameters
        ----------
        by_column
            conversion will by done for each column, otherwise
            done by entire line

        """
        super(ConvertFields, self).__init__()
        self.conversion = conversion
        self.by_column = by_column

        self._func = self.convert_by_columns

        if not self.by_column:
            assert isinstance(
                conversion, Callable
            ), "conversion must be callable to convert by line"
            self._func = self.convert_by_line

    def convert_by_columns(self, line):
        """converts each column in a line"""
        for index, cast in self.conversion:
            line[index] = cast(line[index])
        return line

    def convert_by_line(self, line):
        """converts each column in a line"""
        return self.conversion(line)

    def _call(self, *args, **kwargs):
        return self._func(*args, **kwargs)

    __call__ = _call


def SeparatorFormatParser(
    with_header=True,
    converter=None,
    ignore=None,
    sep=",",
    strip_wspace=True,
    limit=None,
    **kw,
):
    """Returns a parser for a delimited tabular file.

    Parameters
    ----------
    with_header
        when True, first line is taken to be the header. Not
        passed to converter.
    converter
        a callable that returns a correctly formatted line.
    ignore
        lines for which ignore returns True are ignored. White
        lines are always skipped.
    sep
        the delimiter deparating fields.
    strip_wspace
        removes redundant white
    limit
        exits after this many lines

    """
    sep = kw.get("delim", sep)
    if ignore is None:  # keep all lines
        ignore = lambda x: False

    by_column = getattr(converter, "by_column", True)

    def callable(lines):
        num_lines = 0
        header = None
        for line in lines:
            if is_empty(line):
                continue

            line = line.strip("\n").split(sep)
            if strip_wspace and by_column:
                line = [field.strip() for field in line]

            if with_header and not header:
                header = True
                yield line
                continue

            if converter:
                line = converter(line)

            if ignore(line):
                continue

            yield line

            num_lines += 1
            if limit is not None and num_lines >= limit:
                break

    return callable


def autogen_reader(infile, sep, with_title, limit=None):
    """returns a SeparatorFormatParser with field convertor for numeric column
    types."""
    seen_title_line = False
    for first_data_row in infile:
        if seen_title_line:
            break
        if sep in first_data_row and not seen_title_line:
            seen_title_line = True

    infile.seek(0)  # reset to start of file

    typed_fields = []
    bool_map = {"True": True, "False": False}
    for index, value in enumerate(first_data_row.strip().split(sep)):
        try:
            v = eval(value)
            if type(v) in (float, int, complex):
                typed_fields.append((index, v.__class__))
            elif type(v) == bool:
                typed_fields.append((index, lambda x: bool_map.get(x)))
        except:
            pass

    return SeparatorFormatParser(
        converter=ConvertFields(typed_fields), sep=sep, limit=limit
    )


def load_delimited(
    filename,
    header=True,
    delimiter=",",
    with_title=False,
    with_legend=False,
    limit=None,
):
    if limit is not None:
        limit += 1  # don't count header line

    if filename.endswith("gz"):
        f = open_(filename, "rt")
    else:
        f = open(filename, newline=None)

    reader = csv.reader(f, dialect="excel", delimiter=delimiter)
    rows = []
    num_lines = 0
    for row in reader:
        rows.append(row)
        num_lines += 1
        if limit is not None and num_lines >= limit:
            break
    f.close()
    if with_title:
        title = "".join(rows.pop(0))
    else:
        title = ""
    if header:
        header = rows.pop(0)
    else:
        header = None
    if with_legend:
        legend = "".join(rows.pop(-1))
    else:
        legend = ""
    # now do type casting in the order int, float, default is string
    for row in rows:
        for cdex, cell in enumerate(row):
            try:
                cell = int(cell)
                row[cdex] = cell
            except ValueError:
                try:
                    cell = float(cell)
                    row[cdex] = cell
                except ValueError:
                    pass
                pass
    return header, rows, title, legend
