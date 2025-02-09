#!/usr/bin/env python
"""Contains classes that represent biological sequence data. These
provide generic biological sequence manipulation functions, plus functions
that are critical for the EVOLVE calculations.

WARNING: Do not import sequence classes directly! It is expected that you will
access them through the moltype module. Sequence classes depend on information
from the MolType that is _only_ available after MolType has been imported.

Sequences are intended to be immutable. This is not enforced by the code for
performance reasons, but don't alter the MolType or the sequence data after
creation.
"""

import json
import re
import warnings

from functools import total_ordering
from operator import eq, ne
from random import shuffle

from numpy import (
    arange,
    array,
    compress,
    logical_not,
    logical_or,
    nonzero,
    put,
    ravel,
    take,
    zeros,
)
from numpy.random import permutation

from cogent3.core.alphabet import AlphabetError
from cogent3.core.genetic_code import DEFAULT as DEFAULT_GENETIC_CODE
from cogent3.core.genetic_code import GeneticCodes
from cogent3.core.info import Info as InfoClass
from cogent3.format.fasta import alignment_to_fasta
from cogent3.maths.stats.contingency import CategoryCounts, TestResult
from cogent3.maths.stats.number import CategoryCounter
from cogent3.parse import gff
from cogent3.util.dict_array import DictArrayTemplate
from cogent3.util.misc import (
    DistanceFromMatrix,
    bytes_to_string,
    get_object_provenance,
)
from cogent3.util.transform import (
    KeepChars,
    for_seq,
    per_longest,
    per_shortest,
)

from .annotation import Map, _Annotatable


__author__ = "Rob Knight, Gavin Huttley, and Peter Maxwell"
__copyright__ = "Copyright 2007-2019, The Cogent Project"
__credits__ = [
    "Rob Knight",
    "Peter Maxwell",
    "Gavin Huttley",
    "Matthew Wakefield",
    "Daniel McDonald",
]
__license__ = "BSD-3"
__version__ = "2019.9.13a"
__maintainer__ = "Rob Knight"
__email__ = "rob@spot.colorado.edu"
__status__ = "Production"

ARRAY_TYPE = type(array(1))

# standard distance functions: left  because generally useful
frac_same = for_seq(f=eq, aggregator=sum, normalizer=per_shortest)
frac_diff = for_seq(f=ne, aggregator=sum, normalizer=per_shortest)


@total_ordering
class SequenceI(object):
    """Abstract class containing Sequence interface.

    Specifies methods that Sequence delegates to its MolType, and methods for
    detecting gaps.
    """

    # String methods delegated to self._seq -- remember to override if self._seq
    # isn't a string in your base class, but it's probably better to make
    # self._seq a property that contains the string.
    LineWrap = None  # used for formatting FASTA strings

    def __str__(self):
        """__str__ returns self._seq unmodified."""
        return self._seq

    def to_fasta(self, make_seqlabel=None, block_size=60):
        """Return string of self in FASTA format, no trailing newline

        Parameters
        ----------
        make_seqlabel
            callback function that takes the seq object and
            returns a label str

        """

        label = "0"

        if make_seqlabel is not None:
            label = make_seqlabel(self)
        elif hasattr(self, "label") and self.label:
            label = self.label
        elif hasattr(self, "name") and self.name:
            label = self.name
        return alignment_to_fasta({label: str(self)}, block_size=block_size)

    def to_rich_dict(self):
        """returns {'name': name, 'seq': sequence, 'moltype': moltype.label}"""
        info = {} if self.info is None else self.info
        if not info.get("Refs", None) is None and "Refs" in info:
            info.pop("Refs")

        info = info or None
        data = dict(
            name=self.name,
            seq=str(self),
            moltype=self.moltype.label,
            info=info,
            type=get_object_provenance(self),
            version=__version__,
        )

        try:
            annotations = [a.to_rich_dict() for a in self.annotations]
        except AttributeError:
            annotations = []

        if annotations:
            data["annotations"] = annotations

        return data

    def to_json(self):
        """returns a json formatted string"""
        return json.dumps(self.to_rich_dict())

    def translate(self, *args, **kwargs):
        """translate() delegates to self._seq."""
        return self._seq.translate(*args, **kwargs)

    def count(self, item):
        """count() delegates to self._seq."""
        return self._seq.count(item)

    def counts(self, motif_length=1, include_ambiguity=False, allow_gap=False):
        """returns dict of counts of motifs

        only non-overlapping motifs are counted.

        Parameters
        ----------
        motif_length
            number of elements per character.
        include_ambiguity
            if True, motifs containing ambiguous characters
            from the seq moltype are included. No expansion of those is attempted.
        allow_gaps
            if True, motifs containing a gap character are included.

        """
        try:
            data = self._seq
        except AttributeError:
            data = self._data

        not_array = isinstance(data, str)

        if motif_length == 1:
            counts = CategoryCounter(data)
        else:
            if len(data) % motif_length != 0:
                warnings.warn(
                    "%s length not divisible by %s, truncating"
                    % (self.name, motif_length)
                )
            limit = (len(data) // motif_length) * motif_length
            data = data[:limit]
            if not_array:
                counts = CategoryCounter(
                    data[i : i + motif_length] for i in range(0, limit, motif_length)
                )
            else:
                counts = CategoryCounter(
                    tuple(v) for v in data.reshape(limit // motif_length, motif_length)
                )
        if not not_array:
            for key in list(counts):
                indices = [key] if motif_length == 1 else key
                motif = self.alphabet.to_chars(indices).astype(str)
                motif = "".join(motif)
                counts[motif] = counts.pop(key)

        exclude = []
        if not include_ambiguity or not allow_gap:
            is_degen = self.moltype.is_degenerate
            is_gap = self.moltype.is_gapped
            for motif in counts:
                if not include_ambiguity and is_degen(motif):
                    exclude.append(motif)
                elif not allow_gap and is_gap(motif):
                    exclude.append(motif)

        for motif in exclude:
            del counts[motif]

        return counts

    def __lt__(self, other):
        """compares based on the sequence string."""
        return self._seq < str(other)

    def __eq__(self, other):
        """compares based on the sequence string."""
        return self._seq == str(other)

    def __ne__(self, other):
        """compares based on the sequence string."""
        return self._seq != str(other)

    def __hash__(self):
        """__hash__ behaves like the sequence string for dict lookup."""
        return hash(self._seq)

    def __contains__(self, other):
        """__contains__ checks whether other is in the sequence string."""
        return other in self._seq

    def shuffle(self):
        """returns a randomized copy of the Sequence object"""
        randomized_copy_list = list(self)
        shuffle(randomized_copy_list)
        return self.__class__("".join(randomized_copy_list), info=self.info)

    def complement(self):
        """Returns complement of self, using data from MolType.

        Always tries to return same type as item: if item looks like a dict,
        will return list of keys.
        """
        return self.__class__(self.moltype.complement(self), info=self.info)

    def strip_degenerate(self):
        """Removes degenerate bases by stripping them out of the sequence."""
        return self.__class__(self.moltype.strip_degenerate(self), info=self.info)

    def strip_bad(self):
        """Removes any symbols not in the alphabet."""
        return self.__class__(self.moltype.strip_bad(self), info=self.info)

    def strip_bad_and_gaps(self):
        """Removes any symbols not in the alphabet, and any gaps."""
        return self.__class__(self.moltype.strip_bad_and_gaps(self), info=self.info)

    def rc(self):
        """Returns reverse complement of self w/ data from MolType.

        Always returns same type self.
        """
        return self.__class__(self.moltype.rc(self), info=self.info)

    def is_gapped(self):
        """Returns True if sequence contains gaps."""
        return self.moltype.is_gapped(self)

    def is_gap(self, char=None):
        """Returns True if char is a gap.

        If char is not supplied, tests whether self is gaps only.
        """
        if char is None:  # no char - so test if self is all gaps
            return len(self) == self.count_gaps()
        else:
            return self.moltype.is_gap(char)

    def is_degenerate(self):
        """Returns True if sequence contains degenerate characters."""
        return self.moltype.is_degenerate(self)

    def is_valid(self):
        """Returns True if sequence contains no items absent from alphabet."""
        return self.moltype.is_valid(self)

    def is_strict(self):
        """Returns True if sequence contains only monomers."""
        return self.moltype.is_strict(self)

    def first_gap(self):
        """Returns the index of the first gap in the sequence, or None."""
        return self.moltype.first_gap(self)

    def first_degenerate(self):
        """Returns the index of first degenerate symbol in sequence, or None."""
        return self.moltype.first_degenerate(self)

    def first_invalid(self):
        """Returns the index of first invalid symbol in sequence, or None."""
        return self.moltype.first_invalid(self)

    def first_non_strict(self):
        """Returns the index of first non-strict symbol in sequence, or None."""
        return self.moltype.first_non_strict(self)

    def disambiguate(self, method="strip"):
        """Returns a non-degenerate sequence from a degenerate one.

        method can be 'strip' (deletes any characters not in monomers or gaps)
        or 'random'(assigns the possibilities at random, using equal
        frequencies).
        """
        return self.__class__(self.moltype.disambiguate(self, method), info=self.info)

    def degap(self):
        """Deletes all gap characters from sequence."""
        return self.__class__(self.moltype.degap(self), info=self.info)

    def gap_indices(self):
        """Returns list of indices of all gaps in the sequence, or []."""
        return self.moltype.gap_indices(self)

    def gap_vector(self):
        """Returns vector of True or False according to which pos are gaps."""
        return self.moltype.gap_vector(self)

    def gap_maps(self):
        """Returns dicts mapping between gapped and ungapped positions."""
        return self.moltype.gap_maps(self)

    def count_gaps(self):
        """Counts the gaps in the specified sequence."""
        return self.moltype.count_gaps(self)

    def count_degenerate(self):
        """Counts the degenerate bases in the specified sequence."""
        return self.moltype.count_degenerate(self)

    def possibilities(self):
        """Counts number of possible sequences matching the sequence.

        Uses self.degenerates to decide how many possibilites there are at
        each position in the sequence.
        """
        return self.moltype.possibilities(self)

    def mw(self, method="random", delta=None):
        """Returns the molecular weight of (one strand of) the sequence.

        If the sequence is ambiguous, uses method (random or strip) to
        disambiguate the sequence.

        If delta is passed in, adds delta per strand (default is None, which
        uses the alphabet default. Typically, this adds 18 Da for terminal
        water. However, note that the default nucleic acid weight assumes
        5' monophosphate and 3' OH: pass in delta=18.0 if you want 5' OH as
        well.

        Note that this method only calculates the MW of the coding strand. If
        you want the MW of the reverse strand, add self.rc().mw(). DO NOT
        just multiply the MW by 2: the results may not be accurate due to
        strand bias, e.g. in mitochondrial genomes.
        """
        return self.moltype.mw(self, method, delta)

    def can_match(self, other):
        """Returns True if every pos in self could match same pos in other.

        Truncates at length of shorter sequence.
        gaps are only allowed to match other gaps.
        """
        return self.moltype.can_match(self, other)

    def can_mismatch(self, other):
        """Returns True if any position in self could mismatch with other.

        Truncates at length of shorter sequence.
        gaps are always counted as matches.
        """
        return self.moltype.can_mismatch(self, other)

    def must_match(self, other):
        """Returns True if all positions in self must match positions in other."""
        return self.moltype.must_match(self, other)

    def can_pair(self, other):
        """Returns True if self and other could pair.

        Pairing occurs in reverse order, i.e. last position of other with
        first position of self, etc.

        Truncates at length of shorter sequence.
        gaps are only allowed to pair with other gaps, and are counted as 'weak'
        (same category as GU and degenerate pairs).

        NOTE: second must be able to be reverse
        """
        return self.moltype.can_pair(self, other)

    def can_mispair(self, other):
        """Returns True if any position in self could mispair with other.

        Pairing occurs in reverse order, i.e. last position of other with
        first position of self, etc.

        Truncates at length of shorter sequence.
        gaps are always counted as possible mispairs, as are weak pairs like GU.
        """
        return self.moltype.can_mispair(self, other)

    def must_pair(self, other):
        """Returns True if all positions in self must pair with other.

        Pairing occurs in reverse order, i.e. last position of other with
        first position of self, etc.
        """
        return not self.moltype.can_mispair(self, other)

    def diff(self, other):
        """Returns number of differences between self and other.

        NOTE: truncates at the length of the shorter sequence. Case-sensitive.
        """
        return self.distance(other)

    def distance(self, other, function=None):
        """Returns distance between self and other using function(i,j).

        other must be a sequence.

        function should be a function that takes two items and returns a
        number. To turn a 2D matrix into a function, use
        cogent3.util.miscs.DistanceFromMatrix(matrix).

        NOTE: Truncates at the length of the shorter sequence.

        Note that the function acts on two _elements_ of the sequences, not
        the two sequences themselves (i.e. the behavior will be the same for
        every position in the sequences, such as identity scoring or a function
        derived from a distance matrix as suggested above). One limitation of
        this approach is that the distance function cannot use properties of
        the sequences themselves: for example, it cannot use the lengths of the
        sequences to normalize the scores as percent similarities or percent
        differences.

        If you want functions that act on the two sequences themselves, there
        is no particular advantage in making these functions methods of the
        first sequences by passing them in as parameters like the function
        in this method. It makes more sense to use them as standalone functions.
        The factory function cogent3.util.transform.for_seq is useful for
        converting per-element functions into per-sequence functions, since it
        takes as parameters a per-element scoring function, a score aggregation
        function, and a normalization function (which itself takes the two
        sequences as parameters), returning a single function that combines
        these functions and that acts on two complete sequences.
        """
        if function is None:
            # use identity scoring function
            function = lambda a, b: a != b
        distance = 0
        for first, second in zip(self, other):
            distance += function(first, second)
        return distance

    def matrix_distance(self, other, matrix):
        """Returns distance between self and other using a score matrix.

        WARNING: the matrix must explicitly contain scores for the case where
        a position is the same in self and other (e.g. for a distance matrix,
        an identity between U and U might have a score of 0). The reason the
        scores for the 'diagonals' need to be passed explicitly is that for
        some kinds of distance matrices, e.g. log-odds matrices, the 'diagonal'
        scores differ from each other. If these elements are missing, this
        function will raise a KeyError at the first position that the two
        sequences are identical.
        """
        return self.distance(other, DistanceFromMatrix(matrix))

    def frac_same(self, other):
        """Returns fraction of positions where self and other are the same.

        Truncates at length of shorter sequence.
        Note that frac_same and frac_diff are both 0 if one sequence is empty.
        """
        return frac_same(self, other)

    def frac_diff(self, other):
        """Returns fraction of positions where self and other differ.

        Truncates at length of shorter sequence.
        Note that frac_same and frac_diff are both 0 if one sequence is empty.
        """
        return frac_diff(self, other)

    def frac_same_gaps(self, other):
        """Returns fraction of positions where self and other share gap states.

        In other words, if self and other are both all gaps, or both all
        non-gaps, or both have gaps in the same places, frac_same_gaps will
        return 1.0. If self is all gaps and other has no gaps, frac_same_gaps
        will return 0.0. Returns 0 if one sequence is empty.

        Uses self's gap characters for both sequences.
        """
        if not self or not other:
            return 0.0

        is_gap = self.moltype.gaps.__contains__
        return sum([is_gap(i) == is_gap(j) for i, j in zip(self, other)]) / min(
            len(self), len(other)
        )

    def frac_diff_gaps(self, other):
        """Returns frac. of positions where self and other's gap states differ.

        In other words, if self and other are both all gaps, or both all
        non-gaps, or both have gaps in the same places, frac_diff_gaps will
        return 0.0. If self is all gaps and other has no gaps, frac_diff_gaps
        will return 1.0.

        Returns 0 if one sequence is empty.

        Uses self's gap characters for both sequences.
        """
        if not self or not other:
            return 0.0
        return 1.0 - self.frac_same_gaps(other)

    def frac_same_non_gaps(self, other):
        """Returns fraction of non-gap positions where self matches other.

        Doesn't count any position where self or other has a gap.
        Truncates at the length of the shorter sequence.

        Returns 0 if one sequence is empty.
        """
        if not self or not other:
            return 0.0

        is_gap = self.moltype.gaps.__contains__
        count = 0
        identities = 0
        for i, j in zip(self, other):
            if is_gap(i) or is_gap(j):
                continue
            count += 1
            if i == j:
                identities += 1

        if count:
            return identities / count
        else:  # there were no positions that weren't gaps
            return 0

    def frac_diff_non_gaps(self, other):
        """Returns fraction of non-gap positions where self differs from other.

        Doesn't count any position where self or other has a gap.
        Truncates at the length of the shorter sequence.

        Returns 0 if one sequence is empty. Note that this means that
        frac_diff_non_gaps is _not_ the same as 1 - frac_same_non_gaps, since both
        return 0 if one sequence is empty.
        """
        if not self or not other:
            return 0.0

        is_gap = self.moltype.gaps.__contains__
        count = 0
        diffs = 0
        for i, j in zip(self, other):
            if is_gap(i) or is_gap(j):
                continue
            count += 1
            if i != j:
                diffs += 1

        if count:
            return diffs / count
        else:  # there were no positions that weren't gaps
            return 0

    def frac_similar(self, other, similar_pairs):
        """Returns fraction of positions where self[i] is similar to other[i].

        similar_pairs must be a dict such that d[(i,j)] exists if i and j are
        to be counted as similar. Use PairsFromGroups in cogent3.util.misc to
        construct such a dict from a list of lists of similar residues.

        Truncates at the length of the shorter sequence.

        Note: current implementation re-creates the distance function each
        time, so may be expensive compared to creating the distance function
        using for_seq separately.

        Returns 0 if one sequence is empty.
        """
        if not self or not other:
            return 0.0

        return for_seq(f=lambda x, y: (x, y) in similar_pairs, normalizer=per_shortest)(
            self, other
        )

    def with_termini_unknown(self):
        """Returns copy of sequence with terminal gaps remapped as missing."""
        gaps = self.gap_vector()
        first_nongap = last_nongap = None
        for i, state in enumerate(gaps):
            if not state:
                if first_nongap is None:
                    first_nongap = i
                last_nongap = i
        missing = self.moltype.missing
        if first_nongap is None:  # sequence was all gaps
            result = self.__class__([missing for i in len(self)], info=self.info)
        else:
            prefix = missing * first_nongap
            mid = str(self[first_nongap : last_nongap + 1])
            suffix = missing * (len(self) - last_nongap - 1)
            result = self.__class__(prefix + mid + suffix, info=self.info)
        return result

    def replace(self, oldchar, newchar):
        """return new instance with oldchar replaced by newchar"""
        NotImplemented

    def strand_symmetry(self, *args, **kwargs):
        raise TypeError("must be DNA or RNA moltype")


@total_ordering
class Sequence(_Annotatable, SequenceI):
    """Holds the standard Sequence object. Immutable."""

    moltype = None  # connected to ACSII when moltype is imported

    def __init__(
        self,
        seq="",
        name=None,
        info=None,
        check=True,
        preserve_case=False,
        gaps_allowed=True,
        wildcards_allowed=True,
    ):
        """Initialize a sequence.

        Parameters
        ----------
            seq: the raw sequence string, default is ''

            name: the sequence name

            check: if True (the default), validates against the MolType
        """
        if name is None and hasattr(seq, "name"):
            name = seq.name
        self.name = name
        orig_seq = seq
        if isinstance(seq, Sequence):
            seq = seq._seq
        elif isinstance(seq, ArraySequence):
            seq = str(seq)
        elif isinstance(seq, bytes):
            seq = seq.decode("utf-8")
        elif not isinstance(seq, str):
            try:
                seq = "".join(seq)
            except TypeError:
                seq = "".join(map(str, seq))

        seq = self._seq_filter(seq)
        if not preserve_case and not seq.isupper():
            seq = seq.upper()
        self._seq = seq

        if check:
            self.moltype.verify_sequence(self._seq, gaps_allowed, wildcards_allowed)

        if not isinstance(info, InfoClass):
            try:
                info = InfoClass(info)
            except TypeError:
                info = InfoClass()
        if hasattr(orig_seq, "info"):
            try:
                info.update(orig_seq.info)
            except:
                pass
        self.info = info

        if isinstance(orig_seq, _Annotatable):
            self.copy_annotations(orig_seq)

    def to_moltype(self, moltype):
        """returns copy of self with moltype seq

        Parameters
        ----------
        moltype : str
            molecular type
        """
        from cogent3 import get_moltype

        moltype = get_moltype(moltype)
        make_seq = moltype.make_seq
        new_seq = make_seq(self)
        new = self.__class__(seq=new_seq)
        new.clear_annotations()
        for ann in self.annotations:
            ann.copy_to_seq(new)
        return new

    def _seq_filter(self, seq):
        """Returns filtered seq; used to do DNA/RNA conversions."""
        return seq

    def get_colour_scheme(self, colours):
        return {}

    def get_color_scheme(self, colors):  # alias to support US spelling
        return self.get_colour_scheme(colours=colors)

    def copy_annotations(self, other):
        self.annotations = other.annotations[:]

    def annotate_from_gff(self, f):
        first_seqname = None
        for (
            seqname,
            source,
            feature,
            start,
            end,
            score,
            strand,
            frame,
            attributes,
            comments,
        ) in gff.GffParser(f):
            if first_seqname is None:
                first_seqname = seqname
            else:
                assert seqname == first_seqname, (seqname, first_seqname)
            feat_label = gff.parse_attributes(attributes)
            self.add_feature(feature, feat_label, [(start, end)])

    def with_masked_annotations(self, annot_types, mask_char=None, shadow=False):
        """returns a sequence with annot_types regions replaced by mask_char
        if shadow is False, otherwise all other regions are masked.

        Parameters
        ----------
        annot_types
            annotation type(s)
        mask_char
            must be a character valid for the seq MolType. The
            default value is the most ambiguous character, eg. '?' for DNA
        shadow
            whether to mask the annotated regions, or everything but
            the annotated regions

        """
        if mask_char is None:
            ambigs = [(len(v), c) for c, v in list(self.moltype.ambiguities.items())]
            ambigs.sort()
            mask_char = ambigs[-1][1]
        assert mask_char in self.moltype, "Invalid mask_char %s" % mask_char

        annotations = []
        annot_types = [annot_types, [annot_types]][isinstance(annot_types, str)]
        for annot_type in annot_types:
            annotations += self.get_annotations_matching(annot_type)

        region = self.get_region_covering_all(annotations)
        if shadow:
            region = region.get_shadow()

        i = 0
        segments = []
        for b, e in region.get_coordinates():
            segments.append(self._seq[i:b])
            segments.append(mask_char * (e - b))
            i = e
        segments.append(self._seq[i:])

        new = self.__class__(
            "".join(segments), name=self.name, check=False, info=self.info
        )
        new.annotations = self.annotations[:]
        return new

    def gapped_by_map_segment_iter(self, map, allow_gaps=True, recode_gaps=False):
        for span in map.spans:
            if span.lost:
                if allow_gaps:
                    unknown = span.terminal or recode_gaps
                    seg = "-?"[unknown] * span.length
                else:
                    raise ValueError("gap(s) in map %s" % map)
            else:
                seg = self._seq[span.start : span.end]
                if span.reverse:
                    complement = self.moltype.complement
                    seg = [complement(base) for base in seg[::-1]]
                    seg = "".join(seg)
            yield seg

    def gapped_by_map_motif_iter(self, map):
        for segment in self.gapped_by_map_segment_iter(map):
            for motif in segment:
                yield motif

    def gapped_by_map(self, map, recode_gaps=False):
        segments = self.gapped_by_map_segment_iter(map, True, recode_gaps)
        new = self.__class__(
            "".join(segments), name=self.name, check=False, info=self.info
        )
        annots = self._sliced_annotations(new, map)
        new.annotations = annots
        return new

    def _mapped(self, map):
        # Called by generic __getitem__
        segments = self.gapped_by_map_segment_iter(map, allow_gaps=False)
        new = self.__class__("".join(segments), self.name, info=self.info)
        return new

    def __add__(self, other):
        """Adds two sequences (other can be a string as well)."""
        if hasattr(other, "moltype"):
            if self.moltype != other.moltype:
                raise ValueError(
                    "MolTypes don't match: (%s,%s)" % (self.moltype, other.moltype)
                )
            other_seq = other._seq
        else:
            other_seq = other
        new_seq = self.__class__(self._seq + other_seq)
        # Annotations which extend past the right end of the left sequence
        # or past the left end of the right sequence are dropped because
        # otherwise they will annotate the wrong part of the constructed
        # sequence.
        left = [
            a for a in self._shifted_annotations(new_seq, 0) if a.map.end <= len(self)
        ]
        if hasattr(other, "_shifted_annotations"):
            right = [
                a
                for a in other._shifted_annotations(new_seq, len(self))
                if a.map.start >= len(self)
            ]
            new_seq.annotations = left + right
        else:
            new_seq.annotations = left
        return new_seq

    def __repr__(self):
        myclass = "%s" % self.__class__.__name__
        myclass = myclass.split(".")[-1]
        if len(self) > 10:
            seq = str(self._seq[:7]) + "... %s" % len(self)
        else:
            seq = str(self._seq)
        return "%s(%s)" % (myclass, seq)

    def get_name(self):
        """Return the sequence name -- should just use name instead."""

        return self.name

    def __len__(self):
        return len(self._seq)

    def __iter__(self):
        return iter(self._seq)

    def gettype(self):
        """Return the sequence type."""

        return self.moltype.label

    def resolveambiguities(self):
        """Returns a list of tuples of strings."""
        ambigs = self.moltype.resolve_ambiguity
        return [ambigs(motif) for motif in self._seq]

    def sliding_windows(self, window, step, start=None, end=None):
        """Generator function that yield new sequence objects
        of a given length at a given interval.

        Parameters
        ----------
        window
            The length of the returned sequence
        step
            The interval between the start of the returned
            sequence objects
        start
            first window start position
        end
            last window start position

        """
        start = [start, 0][start is None]
        end = [end, len(self) - window + 1][end is None]
        end = min(len(self) - window + 1, end)
        if start < end and len(self) - end >= window - 1:
            for pos in range(start, end, step):
                yield self[pos : pos + window]

    def get_in_motif_size(self, motif_length=1, log_warnings=True):
        """returns sequence as list of non-overlapping motifs

        Parameters
        ----------
        motif_length
            length of the motifs
        log_warnings
            whether to notify of an incomplete terminal motif

        """
        seq = self._seq
        if motif_length == 1:
            return seq
        else:
            length = len(seq)
            remainder = length % motif_length
            if remainder and log_warnings:
                warnings.warn(
                    'Dropped remainder "%s" from end of sequence' % seq[-remainder:]
                )
            return [
                seq[i : i + motif_length]
                for i in range(0, length - remainder, motif_length)
            ]

    def parse_out_gaps(self):
        gapless = []
        segments = []
        nongap = re.compile("([^%s]+)" % re.escape("-"))
        for match in nongap.finditer(self._seq):
            segments.append(match.span())
            gapless.append(match.group())
        map = Map(segments, parent_length=len(self)).inverse()
        seq = self.__class__(
            "".join(gapless), name=self.get_name(), info=self.info, preserve_case=True
        )
        if self.annotations:
            seq.annotations = [a.remapped_to(seq, map) for a in self.annotations]
        return (map, seq)

    def replace(self, oldchar, newchar):
        """return new instance with oldchar replaced by newchar"""
        new = self._seq.replace(oldchar, newchar)
        return self.__class__(new, name=self.name, info=self.info)

    def is_annotated(self):
        """returns True if sequence has any annotations"""
        return self.annotations != ()


class ProteinSequence(Sequence):
    """Holds the standard Protein sequence. MolType set in moltype module."""

    pass


class ProteinWithStopSequence(Sequence):
    """Holds the standard Protein sequence, allows for stop codon

    MolType set in moltype module
    """

    pass


class NucleicAcidSequence(Sequence):
    """base class for DNA and RNA sequences. Abstract."""

    PROTEIN = None  # will set in moltype
    codon_alphabet = None  # will set in moltype

    def reverse_complement(self):
        """Converts a nucleic acid sequence to its reverse complement.
        Synonymn for rc."""
        return self.rc()

    def rc(self):
        """Converts a nucleic acid sequence to its reverse complement."""
        complement = self.moltype.rc(self)
        rc = self.__class__(complement, name=self.name, info=self.info)
        self._annotations_nucleic_reversed_on(rc)
        return rc

    def _gc_from_arg(self, gc):
        # codon_alphabet is being deprecated in favor of genetic codes.
        if gc is None:
            gc = DEFAULT_GENETIC_CODE
        elif isinstance(gc, (int, str)):
            gc = GeneticCodes[gc]
        return gc

    def has_terminal_stop(self, gc=None, allow_partial=False):
        """Return True if the sequence has a terminal stop codon.

        Parameters
        ----------
        gc
            genetic code object
        allow_partial
            if True and the sequence length is not dividisble
            by 3, ignores the 3' terminal incomplete codon

        """
        gc = self._gc_from_arg(gc)
        codons = self._seq
        divisible_by_3 = len(codons) % 3 == 0
        end3 = self.__class__(self._seq[-3:]).degap()
        if not allow_partial and (not divisible_by_3 or len(end3) != 3):
            raise ValueError("seq length not divisible by 3")

        if not divisible_by_3:
            return False

        return codons and gc.is_stop(codons[-3:])

    def trim_stop_codon(self, gc=None, allow_partial=False):
        """Removes a terminal stop codon from the sequence

        Parameters
        ----------
        gc
            genetic code object
        allow_partial
            if True and the sequence length is not divisible
            by 3, ignores the 3' terminal incomplete codon

        """
        gc = self._gc_from_arg(gc)
        codons = self._seq
        divisible_by_3 = len(codons) % 3 == 0

        if not allow_partial and not divisible_by_3:
            raise ValueError("seq length not divisible by 3")

        if divisible_by_3 and codons and gc.is_stop(codons[-3:]):
            codons = codons[:-3]

        return self.__class__(codons, name=self.name, info=self.info)

    def get_translation(self, gc=None, incomplete_ok=False):
        """
        translation to amino acid sequence
        Parameters
        ----------
        gc
            name or ID of genetic code
        incomplete_ok : bool
            codons that are mixes of nucleotide and gaps converted to '?'.
            raises a ValueError if False
        Returns
        -------
        sequence of PROTEIN moltype
        """
        gc = self._gc_from_arg(gc)
        codon_alphabet = self.codon_alphabet(gc).with_gap_motif()
        # translate the codons
        translation = []
        for posn in range(0, len(self._seq) - 2, 3):
            orig_codon = self._seq[posn : posn + 3]
            try:
                resolved = codon_alphabet.resolve_ambiguity(orig_codon)
            except AlphabetError:
                if not incomplete_ok or "-" not in orig_codon:
                    raise
                resolved = (orig_codon,)
            trans = []
            for codon in resolved:
                if codon == "---":
                    aa = "-"
                elif "-" in codon:
                    aa = "?"
                    if not incomplete_ok:
                        raise AlphabetError(f"incomplete codon {codon} in {self.name}")
                else:
                    aa = gc[codon]
                    if aa == "*":
                        continue
                trans.append(aa)
            if not trans:
                raise ValueError(orig_codon)
            aa = self.protein.what_ambiguity(trans)
            translation.append(aa)

        translation = self.protein.make_seq(seq="".join(translation), name=self.name)

        return translation

    def get_orf_positions(self, gc=None, atg=False):
        gc = self._gc_from_arg(gc)
        orfs = []
        start = None
        protein = self.get_translation(gc=gc)
        for (posn, aa) in enumerate(protein):
            posn *= 3
            if aa == "*":
                if start is not None:
                    orfs.append((start, posn))
                start = None
            else:
                if start is None:
                    if (not atg) or gc.is_start(self[posn : posn + 3]):
                        start = posn
        if start is not None:
            orfs.append((start, posn + 3))
        return orfs

    def to_rna(self):
        """Returns copy of self as RNA."""
        return RnaSequence(self)

    def to_dna(self):
        """Returns copy of self as DNA."""
        return DnaSequence(self)

    def strand_symmetry(self, motif_length=1):
        """returns G-test for strand symmetry"""
        counts = self.counts(motif_length=motif_length)
        ssym_pairs = self.moltype.strand_symmetric_motifs(motif_length=motif_length)

        motifs = []
        obs = []
        for plus, minus in sorted(ssym_pairs):
            row = array([counts[plus], counts[minus]], dtype=int)
            if row.max() == 0:  # we ignore motifs missing on both strands
                continue

            obs.append(row)
            motifs.append(plus)

        template = DictArrayTemplate(motifs, ["+", "-"])
        obs = template.wrap(obs)
        cat = CategoryCounts(obs)
        result = cat.G_fit()
        return result


class DnaSequence(NucleicAcidSequence):
    def get_colour_scheme(self, colours):
        return {
            "A": colours.black,
            "T": colours.red,
            "C": colours.blue,
            "G": colours.green,
        }

    def _seq_filter(self, seq):
        """Converts U to T."""
        return seq.replace("u", "t").replace("U", "T")


class RnaSequence(NucleicAcidSequence):
    def get_colour_scheme(self, colours):
        return {
            "A": colours.black,
            "U": colours.red,
            "C": colours.blue,
            "G": colours.green,
        }

    def _seq_filter(self, seq):
        """Converts T to U."""
        return seq.replace("t", "u").replace("T", "U")


class ABSequence(Sequence):
    """Used for two-state modeling; MolType set in moltypes."""

    pass


class ByteSequence(Sequence):
    """Used for storing arbitrary bytes."""

    def __init__(self, seq="", name=None, info=None, check=False, preserve_case=True):
        return super(ByteSequence, self).__init__(
            seq, name=name, info=info, check=check, preserve_case=preserve_case
        )


@total_ordering
class ArraySequenceBase(object):
    """Holds the information for a non-degenerate sequence. Mutable.

    A ArraySequence is an array of indices of symbols, where those symbols are
    defined by an Alphabet. This representation of Sequence is convenient for
    counting symbol frequencies or tuple frequencies, remapping data (e.g. for
    reverse-complement), looking up model parameters, etc. Its main drawback is
    that the sequences can no longer be treated as strings, and conversion
    to/from strings can be fairly time-consuming. Also, any symbol not in the
    Alphabet cannot be represented at all.

    A sequence can have a name, which will be used for output in formats
    such as FASTA.

    A sequence Class has an alphabet (which can be overridden in instances
    where necessary), a delimiter used for string conversions, a LineWrap
    for wrapping characters into lines for e.g. FASTA output.

    Note that a ArraySequence _must_ have an Alphabet, not a MolType,
    because it is often important to store just a subset of the possible
    characters (e.g. the non-degenerate bases) for modeling purposes.
    """

    alphabet = None  # REPLACE IN SUBCLASSES
    moltype = None  # REPLACE IN SUBCLASSES
    Delimiter = ""  # Used for string conversions
    LineWrap = 80  # Wrap sequences at 80 characters by default.

    def __init__(self, data="", alphabet=None, name=None, info=None, check="ignored"):
        """Initializes sequence from data and alphabet.

        WARNING: Does not validate the data or alphabet for compatibility.
        This is for speed. Use is_valid() to check whether the data
        is consistent with the alphabet.

        WARNING: If data has name and/or info, gets ref to same object rather
        than copying in each case.
        """
        if name is None and hasattr(data, "name"):
            name = data.name
        if info is None and hasattr(data, "info"):
            info = data.info
        # set the label
        self.name = name
        # override the class alphabet if supplied
        if alphabet is not None:
            self.alphabet = alphabet
        # if we haven't already set self._data (e.g. in a subclass __init__),
        # guess the data type and set it here
        if not hasattr(self, "_data"):
            # if data is a sequence, copy its data and alphabet
            if isinstance(data, ArraySequence):
                self._data = data._data
                self.alphabet = data.alphabet
            # if it's an array
            elif type(data) == ARRAY_TYPE:
                self._data = data
            else:  # may be set in subclass init
                data = bytes_to_string(data)
                self._from_sequence(data)

        self.moltype = self.alphabet.moltype
        self.info = info

    def __getitem__(self, *args):
        """__getitem__ returns char or slice, as same class."""
        if len(args) == 1 and not isinstance(args[0], slice):
            result = array([self._data[args[0]]])
        else:
            result = self._data.__getitem__(*args)
        return self.__class__(result)

    def __lt__(self, other):
        """compares based on string"""
        return str(self) < other

    def __eq__(self, other):
        """compares based on string"""
        return str(self) == other

    def _from_sequence(self, data):
        """Fills self using the values in data, via the alphabet."""
        if self.alphabet:
            indices = self.alphabet.to_indices(data)
            self._data = array(indices, self.alphabet.array_type)
        else:
            self._data = array(data)

    def __str__(self):
        """Uses alphabet to convert self to string, using delimiter."""
        if hasattr(self.alphabet, "to_string"):
            return self.alphabet.to_string(self._data)
        else:
            return self.Delimiter.join(map(str, self.alphabet.from_indices(self._data)))

    def __len__(self):
        """Returns length of data."""
        return len(self._data)

    def to_fasta(self, make_seqlabel=None, block_size=60):
        """Return string of self in FASTA format, no trailing newline

        Parameters
        ----------
        make_seqlabel
            callback function that takes the seq object and
            returns a label str

        """

        label = "0"

        if make_seqlabel is not None:
            label = make_seqlabel(self)
        elif hasattr(self, "label") and self.label:
            label = self.label
        elif hasattr(self, "name") and self.name:
            label = self.name

        return alignment_to_fasta({label: str(self)}, block_size=block_size)

    def to_phylip(self, name_len=28, label_len=30):
        """Return string of self in one line for PHYLIP, no newline.

        Default: max name length is 28, label length is 30.
        """
        return str(self.name)[:name_len].ljust(label_len) + str(self)

    def is_valid(self):
        """Checks that no items in self are out of the alphabet range."""
        return self._data == self._data.clip(0, len(self.alphabet) - 1)

    def __iter__(self):
        """iter returns characters of self, rather than slices."""
        if hasattr(self.alphabet, "to_string"):
            return iter(self.alphabet.to_string(self._data))
        else:
            return iter(self.Alpabet.from_indices(self._data))

    def tostring(self):
        """to_string delegates to self._data."""
        return self._data.tostring()

    def gaps(self):
        """Returns array containing 1 where self has gaps, 0 elsewhere.

        WARNING: Only checks for standard gap character (for speed), and
        does not check for ambiguous gaps, etc.
        """
        return self._data == self.alphabet.gap_index

    def nongaps(self):
        """Returns array contining 0 where self has gaps, 1 elsewhere.

        WARNING: Only checks for standard gap character (for speed), and
        does not check for ambiguous gaps, etc.
        """
        return self._data != self.alphabet.gap_index

    def regap(self, other, strip_existing_gaps=False):
        """Inserts elements of self into gaps specified by other.

        WARNING: Only checks for standard gap character (for speed), and
        does not check for ambiguous gaps, etc.
        """
        if strip_existing_gaps:
            s = self.degap()
        else:
            s = self
        c = self.__class__
        a = self.alphabet.gapped
        result = zeros(len(other), a.array_type) + a.gap_index
        put(result, nonzero(other.nongaps()), s._data)
        return c(result)

    def degap(self):
        """Returns ungapped copy of self, not changing alphabet."""
        if not hasattr(self.alphabet, "gap") or self.alphabet.gap is None:
            return self.copy()
        d = take(self._data, nonzero(logical_not(self.gap_array()))[0])
        return self.__class__(d, alphabet=self.alphabet, name=self.name, info=self.info)

    def copy(self):
        """Returns copy of self, always separate object."""
        return self.__class__(
            self._data.copy(), alphabet=self.alphabet, name=self.name, info=self.info
        )

    def __contains__(self, item):
        """Returns true if item in self (converts to strings)."""
        return item in str(self)

    def disambiguate(self, *args, **kwargs):
        """Disambiguates self using strings/moltype. Should recode if demand."""
        return self.__class__(self.moltype.disambiguate(str(self), *args, **kwargs))

    def distance(self, other, function=None, use_indices=False):
        """Returns distance between self and other using function(i,j).

        other must be a sequence.

        function should be a function that takes two items and returns a
        number. To turn a 2D matrix into a function, use
        cogent3.util.miscs.DistanceFromMatrix(matrix).

        use_indices: if False, maps the indices onto items (e.g. assumes
        function relates the characters). If True, uses the indices directly.

        NOTE: Truncates at the length of the shorter sequence.

        Note that the function acts on two _elements_ of the sequences, not
        the two sequences themselves (i.e. the behavior will be the same for
        every position in the sequences, such as identity scoring or a function
        derived from a distance matrix as suggested above). One limitation of
        this approach is that the distance function cannot use properties of
        the sequences themselves: for example, it cannot use the lengths of the
        sequences to normalize the scores as percent similarities or percent
        differences.

        If you want functions that act on the two sequences themselves, there
        is no particular advantage in making these functions methods of the
        first sequences by passing them in as parameters like the function
        in this method. It makes more sense to use them as standalone functions.
        The factory function cogent3.util.transform.for_seq is useful for
        converting per-element functions into per-sequence functions, since it
        takes as parameters a per-element scoring function, a score aggregation
        function, and a normalization function (which itself takes the two
        sequences as parameters), returning a single function that combines
        these functions and that acts on two complete sequences.
        """
        if function is None:
            # use identity scoring
            shortest = min(len(self), len(other))
            if not hasattr(other, "_data"):
                other = self.__class__(other)
            distance = (self._data[:shortest] != other._data[:shortest]).sum()
        else:
            distance = 0
            if use_indices:
                self_seq = self._data
                if hasattr(other, "_data"):
                    other_seq = other._data
            else:
                self_seq = self.alphabet.from_indices(self._data)
                if hasattr(other, "_data"):
                    other_seq = other.alphabet.from_indices(other._data)
                else:
                    other_seq = other
            for first, second in zip(self_seq, other_seq):
                distance += function(first, second)
        return distance

    def matrix_distance(self, other, matrix, use_indices=False):
        """Returns distance between self and other using a score matrix.

        if use_indices is True (default is False), assumes that matrix is
        an array using the same indices that self uses.

        WARNING: the matrix must explicitly contain scores for the case where
        a position is the same in self and other (e.g. for a distance matrix,
        an identity between U and U might have a score of 0). The reason the
        scores for the 'diagonals' need to be passed explicitly is that for
        some kinds of distance matrices, e.g. log-odds matrices, the 'diagonal'
        scores differ from each other. If these elements are missing, this
        function will raise a KeyError at the first position that the two
        sequences are identical.
        """
        return self.distance(other, DistanceFromMatrix(matrix))

    def shuffle(self):
        """Returns shuffled copy of self"""
        return self.__class__(permutation(self._data), info=self.info)

    def gap_array(self):
        """Returns array of 0/1 indicating whether each position is a gap."""
        gap_indices = []
        a = self.alphabet
        for c in self.moltype.gaps:
            if c in a:
                gap_indices.append(a.index(c))
        gap_vector = None
        for i in gap_indices:
            if gap_vector is None:
                gap_vector = self._data == i
            else:
                gap_vector = logical_or(gap_vector, self._data == i)
        return gap_vector

    def gap_indices(self):
        """Returns list of gap indices."""
        return list(self.gap_array().nonzero()[0])

    def frac_same_gaps(self, other):
        """Returns fraction of positions where gaps match other's gaps.
        """
        if not other:
            return 0
        self_gaps = self.gap_array()
        if hasattr(other, "gap_array"):
            other_gaps = other.gap_array()
        elif hasattr(other, "gap_vector"):
            other_gaps = array(other.gap_vector())
        else:
            other_gaps = array(self.moltype.gap_vector(other))
        min_len = min(len(self), len(other))
        self_gaps, other_gaps = self_gaps[:min_len], other_gaps[:min_len]
        return (self_gaps == other_gaps).sum() / float(min_len)


class ArraySequence(ArraySequenceBase, SequenceI):
    """ArraySequence provides an array-based implementation of Sequence.

    Use ArraySequenceBase if you need a stripped-down, fast implementation.
    ArraySequence implements everything that SequenceI implements.

    See docstrings for ArraySequenceBase and SequenceI for information about
    these respective classes.
    """

    def strip_bad(self):
        """Returns copy of self with bad chars excised"""
        valid_indices = self._data < len(self.alphabet)
        result = compress(valid_indices, self._data)
        return self.__class__(result, info=self.info)

    def strip_bad_and_gaps(self):
        """Returns copy of self with bad chars and gaps excised."""
        gap_indices = list(map(self.alphabet.index, self.moltype.gaps))
        valid_indices = self._data < len(self.alphabet)
        for i in gap_indices:
            valid_indices[self._data == i] = False
        result = compress(valid_indices, self._data)
        return self.__class__(result, info=self.info)

    def strip_degenerate(self):
        """Returns copy of self without degenerate symbols.

        NOTE: goes via string intermediate because some of the algorithms
        for resolving degenerates are complex. This could be optimized if
        speed becomes critical.
        """
        return self.__class__(self.moltype.strip_degenerate(str(self)), info=self.info)

    def count_gaps(self):
        """Returns count of gaps in self."""
        return self.gap_array().sum()

    def gap_vector(self):
        """Returns list of bool containing whether each pos is a gap."""
        return list(map(bool, self.gap_array()))

    def gap_maps(self):
        """Returns dicts mapping gapped/ungapped positions."""
        nongaps = logical_not(self.gap_array())
        indices = arange(len(self)).compress(nongaps)
        new_indices = arange(len(indices))
        return (
            dict(list(zip(new_indices, indices))),
            dict(list(zip(indices, new_indices))),
        )

    def first_gap(self):
        """Returns position of first gap, or None."""
        a = self.gap_indices()
        try:
            return a[0]
        except IndexError:
            return None

    def is_gapped(self):
        """Returns True of sequence contains gaps."""
        return len(self.gap_indices())

    def mw(self, *args, **kwargs):
        """Returns molecular weight.

        Works via string intermediate: could optimize using array of MW if
        speed becomes important.
        """
        return self.moltype.mw(str(self), *args, **kwargs)

    def frac_similar(self, other, similar_pairs):
        """Returns fraction of positions where self[i] is similar to other[i].

        similar_pairs must be a dict such that d[(i,j)] exists if i and j are
        to be counted as similar. Use PairsFromGroups in cogent3.util.misc to
        construct such a dict from a list of lists of similar residues.

        Truncates at the length of the shorter sequence.

        Note: current implementation re-creates the distance function each
        time, so may be expensive compared to creating the distance function
        using for_seq separately.

        Returns 0 if one sequence is empty.

        NOTE: goes via string intermediate, could optimize using array if
        speed becomes important. Note that form of similar_pairs input would
        also have to change.
        """
        if not self or not other:
            return 0.0

        return for_seq(f=lambda x, y: (x, y) in similar_pairs, normalizer=per_shortest)(
            str(self), str(other)
        )

    def replace(self, oldchar, newchar):
        """return new instance with oldchar replaced by newchar"""
        oldindex = self.alphabet.index(oldchar)
        newindex = self.alphabet.index(newchar)
        new = self._data.copy()
        new[new == oldindex] = newindex
        return self.__class__(new, name=self.name, info=self.info)


class ArrayNucleicAcidSequence(ArraySequence):
    """Abstract class defining ops for codons, translation, etc."""

    def to_codons(self):
        """Returns copy of self in codon alphabet. Assumes ungapped."""
        alpha_len = len(self.alphabet)
        return ArrayCodonSequence(
            alpha_len * (alpha_len * self._data[::3] + self._data[1::3])
            + self._data[2::3],
            name=self.name,
            alphabet=self.alphabet.Triples,
        )

    def complement(self):
        """Returns complement of sequence"""
        return self.__class__(
            self.alphabet._complement_array.take(self._data), info=self.info
        )

    def rc(self):
        """Returns reverse-complement of sequence"""
        comp = self.alphabet._complement_array.take(self._data)
        return self.__class__(comp[::-1], info=self.info)

    def to_rna(self):
        """Returns self as RNA"""
        return ArrayRnaSequence(self._data)

    def to_dna(self):
        """Returns self as DNA"""
        return ArrayDnaSequence(self._data)


class ArrayRnaSequence(ArrayNucleicAcidSequence):
    moltype = None  # set to RNA in moltype.py
    alphabet = None  # set to RNA.alphabets.degen_gapped in moltype.py

    def __init__(self, data="", *args, **kwargs):
        """Returns new ArrayRnaSequence, converting T -> U"""
        if hasattr(data, "upper"):
            data = data.upper().replace("T", "U")
        return super(ArrayNucleicAcidSequence, self).__init__(data, *args, **kwargs)


class ArrayDnaSequence(ArrayNucleicAcidSequence):
    moltype = None  # set to DNA in moltype.py
    alphabet = None  # set to DNA.alphabets.degen_gapped in moltype.py

    def __init__(self, data="", *args, **kwargs):
        """Returns new ArrayRnaSequence, converting U -> T"""
        if hasattr(data, "upper"):
            data = data.upper().replace("U", "T")
        return super(ArrayNucleicAcidSequence, self).__init__(data, *args, **kwargs)


class ArrayCodonSequence(ArraySequence):
    """Abstract base class for codon sequences, incl. string conversion."""

    SequenceClass = ArrayNucleicAcidSequence

    def __str__(self):
        """Joins triplets together as string."""
        return self.Delimiter.join(map("".join, self.alphabet.from_indices(self._data)))

    def _from_string(self, s):
        """Reads from a raw string, rather than a DnaSequence."""
        s = s.upper().replace("U", "T")  # convert to uppercase DNA
        d = self.SequenceClass(s, alphabet=self.alphabet.sub_enumerations[0])
        self._data = d.to_codons()._data

    def __init__(self, data="", alphabet=None, name=None, info=None):
        """Override __init__ to handle init from string."""
        if isinstance(data, str):
            self._from_string(data)
        ArraySequence.__init__(self, data, alphabet, name, info=info)

    def to_codons(self):
        """Converts self to codons -- in practice, just returns self.

        Supports interface of other NucleicAcidSequences."""
        return self

    def to_dna(self):
        """Returns a ArrayDnaSequence from the data in self"""
        unpacked = self.alphabet.unpack_arrays(self._data)
        result = zeros((len(self._data), 3))
        for i, v in enumerate(unpacked):
            result[:, i] = v
        return ArrayDnaSequence(ravel(result), name=self.name)

    def to_rna(self):
        """Returns a ArrayDnaSequence from the data in self."""
        unpacked = self.alphabet.unpack_arrays(self._data)
        result = zeros((len(self._data), 3))
        for i, v in enumerate(unpacked):
            result[:, i] = v
        return ArrayRnaSequence(ravel(result), name=self.name)


class ArrayDnaCodonSequence(ArrayCodonSequence):
    """Holds non-degenerate DNA codon sequence."""

    alphabet = None  # set to DNA.alphabets.base.Triples in moltype.py
    SequenceClass = ArrayDnaSequence


class ArrayRnaCodonSequence(ArrayCodonSequence):
    """Holds non-degenerate DNA codon sequence."""

    alphabet = None  # set to RNA.alphabets.base.Triples in motype.py
    SequenceClass = ArrayRnaSequence

    def _from_string(self, s):
        """Reads from a raw string, rather than a DnaSequence."""
        s = s.upper().replace("T", "U")  # convert to uppercase DNA
        d = self.SequenceClass(s, alphabet=self.alphabet.sub_enumerations[0])
        self._data = d.to_codons()._data


class ArrayProteinSequence(ArraySequence):
    moltype = None  # set to PROTEIN in moltype.py
    alphabet = None  # set to PROTEIN.alphabets.degen_gapped in moltype.py


class ArrayProteinWithStopSequence(ArraySequence):
    moltype = None  # set to PROTEIN_WITH_STOP in moltype.py
    alphabet = None  # set to PROTEIN_WITH_STOP.alphabets.degen_gapped in moltype.py
