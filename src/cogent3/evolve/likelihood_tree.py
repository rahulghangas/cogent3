#!/usr/bin/env python
"""Leaf and Edge classes that can calculate their likelihoods.
Each leaf holds a sequence.  Used by a likelihood function."""


import numpy

from cogent3.util.modules import ExpectedImportError, importVersionedModule


numpy.seterr(all="ignore")

numerictypes = numpy.core.numerictypes.sctype2char

__author__ = "Peter Maxwell"
__copyright__ = "Copyright 2007-2019, The Cogent Project"
__credits__ = ["Peter Maxwell", "Rob Knight"]
__license__ = "BSD-3"
__version__ = "2019.9.13a"
__maintainer__ = "Peter Maxwell"
__email__ = "pm67nz@gmail.com"
__status__ = "Production"

try:
    from . import _likelihood_tree as pyrex

    # pyrex = importVersionedModule('_likelihood_tree', globals(),
    # (2, 1), "pure Python/NumPy likelihoodihood tree")
except ImportError:
    pyrex = None


class _LikelihoodTreeEdge(object):
    def __init__(self, children, edge_name, alignment=None):
        self.edge_name = edge_name
        self.alphabet = children[0].alphabet

        M = children[0].shape[-1]
        for child in children:
            assert child.shape[-1] == M

        # Unique positions are unique combos of input positions
        if alignment is None:
            # The children are pre-aligned gapped sequences
            assignments = [c.index for c in children]
        else:
            self.alignment = alignment
            # The children are ungapped sequences, 'alignment'
            # indicates where gaps need to go.
            assignments = []
            for (i, c) in enumerate(children):
                a = []
                for align_index in alignment:
                    col = align_index[i]
                    if col is None:
                        u = len(c.uniq) - 1  # gap
                    else:
                        u = c.index[col]
                        assert 0 <= u < len(c.uniq) - 1, (
                            u,
                            len(c.uniq),
                            c.uniq[-1],
                            align_index,
                        )
                    a.append(u)
                assignments.append(a)
        (uniq, counts, self.index) = _indexed(list(zip(*assignments)))

        # extra column for gap
        uniq.append(tuple([len(c.uniq) - 1 for c in children]))
        counts.append(0)

        self.uniq = numpy.asarray(uniq, self.integer_type)

        # For faster math, a contiguous index array for each child
        self.indexes = [
            numpy.array(list(ch), self.integer_type)
            for ch in numpy.transpose(self.uniq)
        ]

        # If this is the root it will need to weight the total
        # log likelihoods by these counts:
        self.counts = numpy.array(counts, self.float_type)

        # For product of child likelihoods
        self._indexed_children = list(zip(self.indexes, children))
        self.shape = [len(self.uniq), M]

        # Derive per-column degree of ambiguity from children's
        ambigs = [child.ambig[index] for (index, child) in self._indexed_children]
        self.ambig = numpy.product(ambigs, axis=0)

    def get_site_patterns(self, cols):
        # Recursive lookup of Site Patterns aka Alignment Columns
        child_motifs = [
            child.get_site_patterns(index[cols])
            for (index, child) in self._indexed_children
        ]
        return ["".join(child[u] for child in child_motifs) for u in range(len(cols))]

    def restrict_motif(self, input_likelihoods, fixed_motif):
        # for reconstruct_ancestral_seqs
        mask = numpy.zeros([input_likelihoods.shape[-1]], self.float_type)
        mask[fixed_motif] = 1.0
        input_likelihoods *= mask

    def select_columns(self, cols):
        children = []
        for (index, child) in self._indexed_children:
            child = child.select_columns(cols)
            children.append(child)
        return self.__class__(children, self.edge_name)

    def get_full_length_likelihoods(self, likelihoods):
        return likelihoods[self.index]

    def calc_G_statistic(self, likelihoods, return_table=False):
        # A Goodness-of-fit statistic
        from cogent3.util.table import Table

        unambig = (self.ambig == 1.0).nonzero()[0]
        observed = self.counts[unambig].astype(int)
        expected = likelihoods[unambig] * observed.sum()
        # chisq = ((observed-expected)**2 / expected).sum()
        G = 2 * observed.dot(numpy.log(observed / expected))

        if return_table:
            motifs = self.get_site_patterns(unambig)
            rows = list(zip(motifs, observed, expected))
            rows.sort(key=lambda row: (-row[1], row[0]))
            table = Table(
                header=["Pattern", "Observed", "Expected"], rows=rows, row_ids=True
            )
            return (G, table)
        else:
            return G

    def get_edge(self, name):
        if self.edge_name == name:
            return self
        else:
            for (i, c) in self._indexed_children:
                r = c.get_edge(name)
                if r is not None:
                    return r
        return None

    def make_partial_likelihoods_array(self):
        return numpy.ones(self.shape, self.float_type)

    def sum_input_likelihoods(self, *likelihoods):
        result = numpy.ones(self.shape, self.float_type)
        self.sum_input_likelihoodsR(result, *likelihoods)
        return result

    def as_leaf(self, likelihoods):
        assert len(likelihoods) == len(self.counts)
        return LikelihoodTreeLeaf(
            likelihoods,
            likelihoods,
            self.counts,
            self.index,
            self.edge_name,
            self.alphabet,
            None,
        )


class _PyLikelihoodTreeEdge(_LikelihoodTreeEdge):
    # Should be a subclass of regular tree edge?

    float_type = numerictypes(float)
    integer_type = numerictypes(int)

    # For scaling very very small numbers
    BASE = 2.0 ** 100
    LOG_BASE = numpy.log(BASE)

    def sum_input_likelihoodsR(self, result, *likelihoods):
        result[:] = 1.0
        for (i, index) in enumerate(self.indexes):
            result *= numpy.take(likelihoods[i], index, 0)
        return result

    # For root

    def log_dot_reduce(self, patch_probs, switch_probs, plhs):
        exponent = 0
        state_probs = patch_probs.copy()
        for site in self.index:
            state_probs = numpy.dot(switch_probs, state_probs) * plhs[site]
            while max(state_probs) < 1.0:
                state_probs *= self.BASE
                exponent -= 1
        return numpy.log(sum(state_probs)) + exponent * self.LOG_BASE

    def get_total_log_likelihood(self, input_likelihoods, mprobs):
        lhs = numpy.inner(input_likelihoods, mprobs)
        return self.get_log_sum_across_sites(lhs)

    def get_log_sum_across_sites(self, lhs):
        return numpy.inner(numpy.log(lhs), self.counts)


class _PyxLikelihoodTreeEdge(_LikelihoodTreeEdge):
    integer_type = numerictypes(int)  # match checkArrayInt1D
    float_type = numerictypes(float)  # match checkArrayDouble1D/2D

    def sum_input_likelihoodsR(self, result, *likelihoods):
        pyrex.sum_input_likelihoods(self.indexes, result, likelihoods)
        return result

    # For root

    def log_dot_reduce(self, patch_probs, switch_probs, plhs):
        return pyrex.log_dot_reduce(self.index, patch_probs, switch_probs, plhs)

    def get_total_log_likelihood(self, input_likelihoods, mprobs):
        return pyrex.get_total_log_likelihood(self.counts, input_likelihoods, mprobs)

    def get_log_sum_across_sites(self, lhs):
        return pyrex.get_log_sum_across_sites(self.counts, lhs)


if pyrex is None:
    LikelihoodTreeEdge = _PyLikelihoodTreeEdge
else:
    LikelihoodTreeEdge = _PyxLikelihoodTreeEdge

FLOAT_TYPE = LikelihoodTreeEdge.float_type
INTEGER_TYPE = LikelihoodTreeEdge.integer_type


def _indexed(values):
    # >>> _indexed(['a', 'b', 'c', 'a', 'a'])
    # (['a', 'b', 'c'], [3, 1, 1], [0, 1, 2, 0, 0])
    index = numpy.zeros([len(values)], INTEGER_TYPE)
    unique = []
    counts = []
    seen = {}
    for (c, key) in enumerate(values):
        if key in seen:
            i = seen[key]
            counts[i] += 1
        else:
            i = len(unique)
            unique.append(key)
            counts.append(1)
            seen[key] = i
        index[c] = i
    return unique, counts, index


def make_likelihood_tree_leaf(sequence, alphabet=None, seq_name=None):
    if alphabet is None:
        alphabet = sequence.moltype.alphabet
    if seq_name is None:
        seq_name = sequence.get_name()

    motif_len = alphabet.get_motif_len()
    sequence2 = sequence.get_in_motif_size(motif_len)

    # Convert sequence to indexed list of unique motifs
    (uniq_motifs, counts, index) = _indexed(sequence2)

    # extra column for gap
    uniq_motifs.append("?" * motif_len)
    counts.append(0)

    counts = numpy.array(counts, FLOAT_TYPE)

    # Convert list of unique motifs to array of unique profiles
    try:
        likelihoods = alphabet.get_matched_array(uniq_motifs, FLOAT_TYPE)
    except alphabet.AlphabetError as detail:
        motif = str(detail)
        posn = list(sequence2).index(motif) * motif_len
        raise ValueError("%s at %s:%s not in alphabet" % (repr(motif), seq_name, posn))

    return LikelihoodTreeLeaf(
        uniq_motifs, likelihoods, counts, index, seq_name, alphabet, sequence
    )


class LikelihoodTreeLeaf(object):
    def __init__(self, uniq, likelihoods, counts, index, edge_name, alphabet, sequence):
        if sequence is not None:
            self.sequence = sequence
        self.alphabet = alphabet
        self.name = self.edge_name = edge_name
        self.uniq = uniq
        self.motifs = numpy.asarray(uniq)
        self.input_likelihoods = likelihoods
        self.counts = counts
        self.index = index
        self.shape = likelihoods.shape
        self.ambig = numpy.sum(self.input_likelihoods, axis=-1)

    def backward(self):
        index = numpy.array(self.index[::-1, ...])
        result = self.__class__(
            self.uniq,
            self.input_likelihoods,
            self.counts,
            index,
            self.edge_name,
            self.alphabet,
            None,
        )
        return result

    def __len__(self):
        return len(self.index)

    def __getitem__(self, index):
        cols = list(range(*index.indices(len(self.index))))
        return self.select_columns(cols)

    def get_motif_counts(self, include_ambiguity=False):
        weights = self.counts / self.ambig
        profile = self.input_likelihoods * weights[..., numpy.newaxis]
        if not include_ambiguity:
            unambig = self.ambig == 1.0
            profile = numpy.compress(unambig, profile, axis=0)
        return numpy.sum(profile, axis=0)

    def get_ambiguous_positions(self):
        ambig = {}
        for (i, u) in enumerate(self.index):
            if self.ambig[u] != 1.0:
                ambig[i] = self.uniq[u]
        return ambig

    def select_columns(self, cols):
        sub_index = [self.index[i] for i in cols]
        (keep, counts, index) = _indexed(sub_index)
        keep.append(len(self.uniq) - 1)  # extra column for gap
        counts.append(0)
        counts = numpy.array(counts, FLOAT_TYPE)
        uniq = [self.uniq[u] for u in keep]
        likelihoods = self.input_likelihoods[keep]
        return self.__class__(
            uniq, likelihoods, counts, index, self.edge_name, self.alphabet, None
        )

    def get_edge(self, name):
        if self.edge_name == name:
            return self
        else:
            return None

    def get_site_patterns(self, cols):
        return numpy.asarray(self.uniq)[cols]
