import json
import os
import zipfile

import numpy

from cogent3 import load_aligned_seqs as _load_aligned_seqs
from cogent3 import load_unaligned_seqs as _load_unaligned_seqs
from cogent3.core.alignment import ArrayAlignment, SequenceCollection
from cogent3.core.moltype import get_moltype
from cogent3.core.profile import (
    make_motif_counts_from_tabular,
    make_motif_freqs_from_tabular,
    make_pssm_from_tabular,
)
from cogent3.evolve.fast_distance import DistanceMatrix
from cogent3.format.alignment import FORMATTERS
from cogent3.maths.util import safe_log
from cogent3.parse.sequence import PARSERS
from cogent3.util.deserialise import deserialise_object
from cogent3.util.table import Table, convert2DDict

from .composable import (
    Composable,
    ComposableAligned,
    ComposableSeq,
    ComposableTabular,
    NotCompleted,
    _checkpointable,
)
from .data_store import (
    IGNORE,
    OVERWRITE,
    RAISE,
    SKIP,
    ReadOnlyDirectoryDataStore,
    ReadOnlyTinyDbDataStore,
    ReadOnlyZippedDataStore,
    SingleReadDataStore,
    WritableTinyDbDataStore,
    load_record_from_json,
    make_record_for_json,
)


__author__ = "Gavin Huttley"
__copyright__ = "Copyright 2007-2019, The Cogent Project"
__credits__ = ["Gavin Huttley"]
__license__ = "BSD-3"
__version__ = "2019.9.13a"
__maintainer__ = "Gavin Huttley"
__email__ = "Gavin.Huttley@anu.edu.au"
__status__ = "Alpha"


def findall(base_path, suffix="fa", limit=None, verbose=False):
    """returns glob match to suffix, path is relative to base_path

    Parameters
    ----------
    base_path : str
        path to directory or zipped archive
    suffix : str
        suffix of filenames
    limit : int or None
        the number of matches to return
    """
    if not os.path.exists(base_path):
        raise ValueError(f"'{base_path}' does not exist")

    zipped = zipfile.is_zipfile(base_path)
    klass = ReadOnlyZippedDataStore if zipped else ReadOnlyDirectoryDataStore
    data_store = klass(base_path, suffix=suffix, limit=limit, verbose=verbose)
    return data_store.members


def get_data_store(base_path, suffix=None, limit=None, verbose=False):
    """returns DataStore containing glob matches to suffix in base_path

    Parameters
    ----------
    base_path : str
        path to directory or zipped archive
    suffix : str
        suffix of filenames
    limit : int or None
        the number of matches to return
    Returns
    -------
    ReadOnlyDirectoryDataStore or ReadOnlyZippedDataStore
    """
    if base_path.endswith("tinydb"):
        suffix = "json"

    if suffix is None:
        raise ValueError("suffix required")

    if not os.path.exists(base_path):
        raise ValueError(f"'{base_path}' does not exist")
    if not type(suffix) == str:
        raise ValueError(f"{suffix} is not a string")

    zipped = zipfile.is_zipfile(base_path)
    if base_path.endswith("tinydb"):
        klass = ReadOnlyTinyDbDataStore
    elif zipped:
        klass = ReadOnlyZippedDataStore
    else:
        klass = ReadOnlyDirectoryDataStore
    data_store = klass(base_path, suffix=suffix, limit=limit, verbose=verbose)
    return data_store


class _seq_loader:
    def __init__(self):
        self.func = self.load

    def load(self, path):
        """returns alignment"""
        # if we get a seq object, we try getting abs_path from that now
        try:
            abs_path = path.info.source
        except AttributeError:
            abs_path = str(path)

        if type(path) == str:
            # we use a data store as it's read() handles compression
            path = SingleReadDataStore(path)[0]

        if hasattr(path, "read"):
            data = path.read().splitlines()
            data = dict(record for record in self._parser(data))
            seqs = self.klass(data=data, moltype=self.moltype)
            seqs.info.source = abs_path
        elif not isinstance(path, SequenceCollection):
            func = _load_aligned_seqs if self.aligned else _load_unaligned_seqs
            seqs = func(path, moltype=self.moltype)
        else:
            seqs = path  # it is a SequenceCollection

        if self._output_types & {"sequences"}:
            seqs = seqs.degap()
            seqs.info.source = abs_path

        return seqs


class load_aligned(_seq_loader, ComposableAligned):
    """Loads aligned sequences. Returns an Alignment object."""

    klass = ArrayAlignment

    def __init__(self, moltype=None, format="fasta"):
        """
        Parameters
        ----------
        moltype
            molecular type, string or instance
        format : str
            sequence file format
        """
        super(ComposableAligned, self).__init__(
            input_types=None,
            output_types=("aligned", "serialisable"),
            data_types=("DataStoreMember", "str", "Path"),
        )
        _seq_loader.__init__(self)
        self._formatted_params()
        if moltype:
            moltype = get_moltype(moltype)
        self.moltype = moltype
        self._parser = PARSERS[format.lower()]


class load_unaligned(ComposableSeq, _seq_loader):
    """Loads unaligned sequences. Returns a SequenceCollection."""

    klass = SequenceCollection

    def __init__(self, moltype=None, format="fasta"):
        """
        Parameters
        ----------
        moltype
            molecular type, string or instance
        format : str
            sequence file format
        """
        super(ComposableSeq, self).__init__(
            input_types=None,
            output_types=("sequences", "serialisable"),
            data_types=(
                "DataStoreMember",
                "str",
                "Path",
                "ArrayAlignment",
                "Alignment",
                "SequenceCollection",
            ),
        )
        _seq_loader.__init__(self)
        self._formatted_params()
        if moltype:
            moltype = get_moltype(moltype)
        self.moltype = moltype
        self._parser = PARSERS[format.lower()]


class load_tabular(ComposableTabular):
    """Loads delimited data. Returns a Table."""

    def __init__(
        self,
        with_title=False,
        with_header=True,
        limit=None,
        sep="\t",
        strict=True,
        as_type="table",
    ):
        """

        Parameters
        ----------
        with_title
            files have a title
        with_header
            files have a header
        limit
            number of records to read
        sep
            field delimiter
        strict
            all rows MUST have the same number of records
        """
        super(ComposableTabular, self).__init__(
            input_types=None,
            output_types=("tabular", "serialisable"),
            data_types=("DataStoreMember", "str", "Path"),
        )
        self._formatted_params()
        self._sep = sep
        self._with_title = with_title
        self._with_header = with_header
        self._limit = limit
        self.func = self.load
        self.strict = strict
        self.as_type = as_type

    def _parse(self, data):
        """returns header, records, title"""
        title = header = None
        sep = self._sep
        strict = self.strict
        read = data.open()
        if self._with_title or self._with_header:
            for line in read:
                line = line.strip()
                if not line:
                    continue
                if self._with_title and title is None:
                    title = line
                elif self._with_header and header is None:
                    line = [e.strip() for e in line.split(sep)]
                    header = line
                    break
        num_records = None if header is None else len(header)
        rows = []
        for i, line in enumerate(read):
            if i == self._limit:
                break
            line = line.strip()
            line = [e.strip() for e in line.split(sep)]
            if num_records is None:
                num_records = len(line)
            if strict and len(line) != num_records:
                read.close()
                msg = f"Inconsistent number of fields: {len(line)} " "!= {num_records}"
                raise AssertionError(msg)
            rows.append(line)
        data.close()
        records = []
        for record in zip(*rows):
            record = numpy.array(record, dtype="O")
            try:
                record = record.astype(int)
            except ValueError:
                try:
                    record = record.astype(float)
                except ValueError:
                    pass
            records.append(record)
        records = numpy.array(records, dtype="O").T
        return header, records, title

    def load(self, path):
        if type(path) == str:
            # we use a data store as it's read() handles compression
            path = SingleReadDataStore(path)[0]

        try:
            header, data, title = self._parse(path)
        except Exception as err:
            result = NotCompleted("ERROR", self, err.args[0], source=str(path))

        if self.as_type == "table":
            return Table(header, rows=data, title=title)

        assert data.shape[1] == 3, "Invalid tabular data"

        if self.as_type == "distances":
            # records is of the form [ [dim-1, dim-2, value] for entries in DistanceMatrix ]
            return DistanceMatrix({(e[0], e[1]): e[2] for e in data})

        if self.as_type == "motif_counts":
            return make_motif_counts_from_tabular(data)
        if self.as_type == "motif_freqs":
            return make_motif_freqs_from_tabular(data)
        if self.as_type == "pssm":
            return make_pssm_from_tabular(data)

        return None


class write_tabular(_checkpointable, ComposableTabular):
    """writes tabular data"""

    def __init__(
        self, data_path, format="tsv", name_callback=None, create=False, if_exists=SKIP
    ):
        """
        Parameters
        ----------
        data_path
            path to write output, if ends with .zip will be a compressed zip
            archive
        format : str
            one of 'tsv', 'csv', 'tex', 'md'
        name_callback
            function that takes the data object and returns a base
            file name
        create : bool
            whether to create the output directory
        if_exists : str
            behaviour if output exists. Either 'skip', 'raise' (raises an
            exception), 'overwrite'
        """
        super(write_tabular, self).__init__(
            input_types=("tabular_result", "tabular"),
            output_types="identifier",
            data_types=("Table", "DictArray", "DistanceMatrix"),
            data_path=data_path,
            name_callback=name_callback,
            create=create,
            if_exists=if_exists,
            suffix=format,
        )
        self._formatted_params()
        self._format = format

    def write(self, data, identifier=None):
        if identifier is None:
            identifier = self._make_output_identifier(data)
        output = data.to_string(format=self._format)
        self.data_store.write(identifier, output)
        return identifier


class write_seqs(_checkpointable):
    """Writes sequences to text files in standard format."""

    def __init__(
        self,
        data_path,
        format="fasta",
        suffix="fa",
        name_callback=None,
        create=False,
        if_exists=SKIP,
    ):
        """
        Parameters
        ----------
        data_path
            path to write output, if ends with .zip will be a compressed zip
            archive
        format : str
            sequence file format
        suffix : str
            filename suffix for output
        name_callback
            function that takes the data object and returns a base
            file name
        create : bool
            whether to create the output directory
        if_exists : str
            behaviour if output exists. Either 'skip', 'raise' (raises an
            exception), 'overwrite'
        """
        super(write_seqs, self).__init__(
            input_types=("sequences", "aligned"),
            output_types=("sequences", "aligned", "identifier"),
            data_types=("ArrayAlignment", "Alignment", "SequenceCollection"),
            data_path=data_path,
            name_callback=name_callback,
            create=create,
            if_exists=if_exists,
            suffix=suffix,
        )
        self._formatted_params()
        self._format = format
        self._formatter = FORMATTERS[format]

    def _set_checkpoint_loader(self):
        loader = {"sequences": load_unaligned}.get(self._out._type, load_aligned)
        loader = loader(format=self._format)
        self._load_checkpoint = loader

    def write(self, data, identifier=None):
        if identifier is None:
            identifier = self._make_output_identifier(data)
        data.info.stored = self.data_store.write(identifier, data.to_fasta())
        return identifier


class load_json(Composable):
    """Loads json serialised cogent3 objects from a json file. 
    Returns whatever object type was stored."""

    _type = "output"

    def __init__(self):
        super(load_json, self).__init__(input_types=None, output_types="serialisable")
        self.func = self.read

    def read(self, path):
        """returns object deserialised from json at path"""
        if type(path) == str:
            path = SingleReadDataStore(path)[0]

        data = path.read()
        identifier, data, completed = load_record_from_json(data)

        result = deserialise_object(data)
        if hasattr(result, "info"):
            result.info["source"] = result.info.get("source", identifier)
        else:
            try:
                identifier = getattr(result, "source", identifier)
                setattr(result, "source", identifier)
            except AttributeError:
                pass
        return result


class write_json(_checkpointable):
    """Writes json serialised objects to individual json files."""

    _type = "output"

    def __init__(
        self, data_path, name_callback=None, create=False, if_exists=SKIP, suffix="json"
    ):
        super(write_json, self).__init__(
            input_types="serialisable",
            output_types=("identifier", "serialisable"),
            data_path=data_path,
            name_callback=name_callback,
            create=create,
            if_exists=if_exists,
            suffix=suffix,
        )
        self.func = self.write

    def _set_checkpoint_loader(self):
        self._load_checkpoint = self

    def write(self, data, identifier=None):
        if identifier is None:
            identifier = self._make_output_identifier(data)
        out = make_record_for_json(os.path.basename(identifier), data, True)
        out = json.dumps(out)
        stored = self.data_store.write(identifier, out)
        # todo is anything actually using this stored attriubte? if not, delete this
        #  code and all other cases
        if hasattr(data, "info"):
            data.info["stored"] = stored
        else:
            try:
                data.stored = stored
            except AttributeError:
                pass
        return identifier


class load_db(Composable):
    """Loads json serialised cogent3 objects from a TinyDB file. 
    Returns whatever object type was stored."""

    _type = "output"

    def __init__(self):
        super(load_db, self).__init__(input_types=None, output_types="serialisable")
        self.func = self.read

    def read(self, identifier):
        """returns object deserialised from a TinyDb"""
        id_ = getattr(identifier, "id", None)
        if id_ is None:
            msg = (
                f"{identifier} not connected to a TinyDB. "
                "If a json file path, use io.load_json()"
            )
            raise TypeError(msg)
        data = identifier.read()

        result = deserialise_object(data)
        if hasattr(result, "info"):
            result.info["source"] = result.info.get("source", identifier)
        else:
            try:
                identifier = getattr(result, "source", identifier)
                setattr(result, "source", identifier)
            except AttributeError:
                pass
        return result


class write_db(_checkpointable):
    """Writes json serialised objects to a TinyDB instance."""

    _type = "output"

    def __init__(
        self, data_path, name_callback=None, create=False, if_exists=SKIP, suffix="json"
    ):
        super(write_db, self).__init__(
            input_types="serialisable",
            output_types=("identifier", "serialisable"),
            data_path=data_path,
            name_callback=name_callback,
            create=create,
            if_exists=if_exists,
            suffix=suffix,
            writer_class=WritableTinyDbDataStore,
        )
        self.func = self.write

    def _set_checkpoint_loader(self):
        self._load_checkpoint = self

    def write(self, data, identifier=None):
        if identifier is None:
            identifier = self._make_output_identifier(data)
        # todo revisit this when we establish immutability behaviour of database
        try:
            out = data.to_json()
        except AttributeError:
            out = json.dumps(data)
        stored = self.data_store.write(identifier, out)
        # todo is anything actually using this stored attriubte? if not, delete this
        #  code and all other cases
        if hasattr(data, "info"):
            data.info["stored"] = stored
        else:
            try:
                data.stored = stored
            except AttributeError:
                pass
        return identifier
