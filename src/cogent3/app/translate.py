from collections import defaultdict

from cogent3.core.alignment import SequenceCollection
from cogent3.core.genetic_code import DEFAULT, get_code
from cogent3.core.moltype import get_moltype

from .composable import ComposableSeq, NotCompleted


__author__ = "Gavin Huttley"
__copyright__ = "Copyright 2007-2019, The Cogent Project"
__credits__ = ["Gavin Huttley"]
__license__ = "BSD-3"
__version__ = "2019.9.13a"
__maintainer__ = "Gavin Huttley"
__email__ = "Gavin.Huttley@anu.edu.au"
__status__ = "Alpha"


def best_frame(seq, gc=DEFAULT, allow_rc=False, require_stop=False):
    """returns reading frame start that has either no stops or a single
    terminal stop codon

    result will be either 1, 2, 3 (or -1, -2, -3)

    Parameters
    ----------
    gc
        genetic code ID, name or instance
    allow_rc
        If False, forward strand considered only. If True, and
          best frame on rc, it will be negative
    require_stop
        a terminal stop must be present
    
    Returns
    -------
    int
        1, 2, 3 if the best frame on the +_ strand; -1, -2, -3 if the best
        frame is on the reverse strand
    
    Raises
    ------
    ValueError
        if the minimum number of stop codons across all frames exceeds 1,
        or the the stop codon is not at the sequence end
    """
    gc = get_code(gc)
    translations = gc.sixframes(seq)
    if not allow_rc:
        translations = translations[:3]

    if not require_stop:
        # don't count stops if they're at the end of the aa sequence
        for i in range(len(translations)):
            if translations[i].endswith("*"):
                translations[i] = translations[i][:-1]

    stops_in_frame = [(tr.count("*"), i) for i, tr in enumerate(translations)]
    stops_in_frame.sort()
    min_stops, frame = stops_in_frame[0]
    # if min_stops > 1, cannot be translated
    if min_stops > 1:
        raise ValueError("%s cannot be robustly translated" % seq.name)
    elif min_stops == 0 and require_stop:
        # find seq with 1 stop
        min_stops = 20  # nonsense value
        for idx, (n, fr) in enumerate(stops_in_frame):
            if n == 1:
                min_stops, frame = n, fr
                break

    if 0 <= min_stops <= 1:
        if min_stops == 1 and not translations[frame].endswith("*"):
            raise ValueError("%s cannot be robustly translated" % seq.name)
    else:
        raise ValueError("%s cannot be robustly translated" % seq.name)

    frame += 1
    if allow_rc and frame > 3:
        frame = 3 - frame
    return frame


def translate_frames(seq, moltype=None, gc=DEFAULT, allow_rc=False):
    """translates a nucleic acid sequence 
    
    Parameters
    ----------
    moltype
        molecular type, must be either DNA or RNA
    gc
        identifer for a genetic code or a genetic code instance
    allow_rc : bool
        includes frames sequence reverse complement
        
    Returns
    -------
    [(frame, translation), ..]
    Reverse complement frame numbers are negative
    """
    gc = get_code(gc)
    if moltype:
        moltype = get_moltype(moltype)
        seq = moltype.make_seq(seq)

    translations = gc.sixframes(seq)
    if not allow_rc:
        translations = translations[:3]

    return translations


def get_fourfold_degenerate_sets(gc, alphabet=None, as_indices=True):
    """returns set() of codons that are 4-fold degenerate for genetic code gc
    
    Parameters
    ----------
    gc
        identifer for a genetic code or a genetic code instance
    alphabet
        nucleic acid Alphabet instance
    as_indices
        codons are represented as indices, rather than strings
    """
    four_fold = set()
    syns = gc.synonyms
    for codons in list(syns.values()):
        if len(codons) < 4:
            continue
        pos12s = defaultdict(list)
        for codon in codons:
            pos12s[codon[:2]].append(codon)

        for groups in list(pos12s.values()):
            if len(groups) == 4:
                four_fold.update([frozenset(groups)])

    if as_indices:
        assert alphabet is not None, "Must provide alphabet to convert to indices"
        ffold = set()
        to_indices = alphabet.to_indices
        for group in four_fold:
            grp = frozenset([tuple(to_indices(element)) for element in group])
            ffold.add(grp)
        four_fold = ffold

    return four_fold


class select_translatable(ComposableSeq):
    """Identifies most likely reading frame. Returns modified sequences / alignment,
    if it could be resolved, NotCompleted otherwise."""

    def __init__(
        self, moltype="dna", gc=DEFAULT, allow_rc=False, trim_terminal_stop=True
    ):
        """selects translatable sequences

        Sequences are truncated to modulo 3. seqs.info has a translation_errors
        entry.

        Parameters
        ----------
        moltype : str
            molecular type, must be either DNA or RNA
        gc
            identifer for a genetic code or a genetic code instance
        allow_rc : bool
            If False, forward strand considered only. If True, and
              best frame on rc, it will be negative
        trim_terminal_stop : bool
            exclude terminal stop codon from seqs
        
        Returns
        -------
        A sequence collection. Sequences that could not be translated
        are excluded.
        """
        super(select_translatable, self).__init__(
            input_types=("sequences", "aligned"),
            output_types="sequences",
            data_types=("ArrayAlignment", "Alignment", "SequenceCollection"),
        )
        self._formatted_params()

        moltype = get_moltype(moltype)
        assert moltype.label.lower() in ("dna", "rna"), "Invalid moltype"

        self._moltype = moltype
        self._gc = get_code(gc)
        self._allow_rc = allow_rc
        self._trim_terminal_stop = trim_terminal_stop
        self.func = self.get_translatable

    def get_translatable(self, seqs):
        """returns the translatable sequences from seqs.

        translation errors are stroed in the info object"""
        seqs = seqs.degap()
        seqs = seqs.to_moltype(self._moltype)
        translatable = []
        error_log = []
        for seq in seqs.seqs:
            try:
                frame = best_frame(seq, self._gc, allow_rc=self._allow_rc)
                if frame < 0:
                    seq = seq.rc()
                    frame *= -1
                frame -= 1  # returned from best frame as 1, 2, 3
                num_codons = (len(seq) - frame) // 3
                seq = seq[frame : frame + (num_codons * 3)]
                if self._trim_terminal_stop:
                    seq = seq.trim_stop_codon(gc=self._gc)
                translatable.append([seq.name, seq])
            except ValueError as msg:
                # TODO handle case where incomplete at end OR beginning
                # plus case where is divisible by 3 but not in frame
                # if not divisible by 3, then calc remainder as len(seq) % 3
                # try translating new[remainder:] and new[:-remainder]
                error_log.append([seq.name, msg.args[0]])

        if translatable:
            translatable = SequenceCollection(
                data=translatable, moltype=self._moltype, info=seqs.info
            )
            translatable.info["translation_errors"] = error_log
        else:
            translatable = NotCompleted("FALSE", self, " ".join(error_log), source=seqs)

        return translatable
