from unittest import TestCase, main

from cogent3 import DNA, load_aligned_seqs
from cogent3.core.alignment import Aligned
from cogent3.draw.dotplot import (
    Dotplot,
    _convert_coords_for_scatter,
    _convert_input,
    get_align_coords,
    len_seq,
    not_gap,
)


__author__ = "Gavin Huttley"
__copyright__ = "Copyright 2007-2012, The Cogent Project"
__credits__ = ["Gavin Huttley"]
__license__ = "BSD-3"
__version__ = "2019.9.13a"
__maintainer__ = "Gavin Huttley"
__email__ = "gavin.huttley@anu.edu.au"
__status__ = "Alpha"


class TestUtilFunctions(TestCase):
    def test_converting_coords(self):
        """convert [(x1,y1), (x2,y2),..] to plotly style"""
        got = _convert_coords_for_scatter([[(0, 1), (2, 3)], [(3, 4), (2, 8)]])
        expect = [0, 2, None, 3, 2], [1, 3, None, 4, 8]
        self.assertEqual(got, expect)

    def test_len_seq(self):
        """returns length of sequence minus gaps"""
        m, seq = DNA.make_seq("ACGGT--A").parse_out_gaps()
        self.assertEqual(len_seq(m), 6)

    def test_not_gap(self):
        """distinguishes Map instances that include gap or not"""
        m, seq = DNA.make_seq("ACGGT--A").parse_out_gaps()
        self.assertTrue(not_gap(m[0]))
        self.assertFalse(not_gap(m[5]))

    def test_convert_input(self):
        """converts data for dotplotting"""
        m, seq = DNA.make_seq("ACGGT--A").parse_out_gaps()
        aligned_seq = Aligned(m, seq)
        mapped_gap, new_seq = _convert_input(aligned_seq, None)
        self.assertIs(new_seq.moltype, DNA)
        self.assertIs(mapped_gap, m)
        self.assertIs(new_seq, seq)
        mapped_gap, new_seq = _convert_input("ACGGT--A", DNA)
        self.assertEqual(str(mapped_gap), str(m))
        self.assertEqual(str(new_seq), str(seq))

    def test_get_align_coords(self):
        """correctly returns the alignment coordinates"""
        # 01234  5
        # ACGGT--A
        #   012345
        # --GGTTTA
        m1, seq1 = DNA.make_seq("ACGGT--A").parse_out_gaps()
        m2, seq2 = DNA.make_seq("--GGTTTA").parse_out_gaps()
        x, y = get_align_coords(m1, m2)
        expect = [2, 4, None, 5, 5], [0, 2, None, 5, 5]
        self.assertEqual((x, y), expect)

        # we have no gaps, so coords will be None
        m1, s1 = seq1.parse_out_gaps()
        m2, s2 = seq2.parse_out_gaps()
        self.assertEqual(get_align_coords(m1, m2), None)

        # unless we indicate the seqs came from an Alignment
        m1, seq1 = DNA.make_seq("ACGGTTTA").parse_out_gaps()
        m2, seq2 = DNA.make_seq("GGGGTTTA").parse_out_gaps()
        x, y = get_align_coords(m1, m2, aligned=True)
        self.assertEqual((x, y), ([0, len(seq1)], [0, len(seq1)]))

        # raises an exception if the Aligned seqs are different lengths
        m1, seq1 = DNA.make_seq("ACGGTTTA").parse_out_gaps()
        m2, seq2 = DNA.make_seq("GGGGTT").parse_out_gaps()
        with self.assertRaises(AssertionError):
            get_align_coords(m1, m2, aligned=True)

    def test_display2d(self):
        """correctly constructs a Display2d"""
        dp = Dotplot("-TGATGTAAGGTAGTT", "CTGG---AAG---GGT", window=5)
        expect = [0, 2, None, 6, 8, None, 12, 14], [1, 3, None, 4, 6, None, 7, 9]
        self.assertEqual(dp._aligned_coords, expect)
        dp._build_fig()
        traces = dp.traces
        self.assertEqual(len(traces), 2)  # no rev complement
        # we nudge alignment coordinates by 0.2 on x-axis
        expect = [0.2, 2.2, None, 6.2, 8.2, None, 12.2, 14.2]
        self.assertEqual(traces[-1].x, expect)
        self.assertEqual(traces[-1].name, "Alignment")
        self.assertEqual(traces[0].name, "+ strand")
        # check against hand calculated coords
        expect_x = [6, 14, None, 2, 12, None, 3, 11, None, 0, 6]
        expect_y = [0, 8, None, 0, 10, None, 2, 10, None, 2, 8]
        self.assertEqual(traces[0].x, expect_x)
        self.assertEqual(traces[0].y, expect_y)

    def test_remove_trace(self):
        """correctly removes a trace"""
        dp = Dotplot("-TGATGTAAGGTAGTT", "CTGG---AAG---GGT", window=5)
        expect = [0, 2, None, 6, 8, None, 12, 14], [1, 3, None, 4, 6, None, 7, 9]
        self.assertEqual(dp._aligned_coords, expect)
        dp._build_fig()
        traces = dp.traces
        self.assertEqual(len(traces), 2)
        _ = dp.pop_trace("Alignment")
        self.assertEqual(len(traces), 1)
        self.assertEqual(traces[0].name, "+ strand")

        dp = Dotplot("-TGATGTAAGGTAGTT", "CTGG---AAG---GGT", window=5)
        dp._build_fig()
        dp.remove_traces("Alignment")
        self.assertEqual(len(dp.traces), 1)
        self.assertEqual(dp.traces[0].name, "+ strand")

    def test_dotplot_regression(self):
        """Tests whether dotplot produces traces and in correct ordering. Also tests if pop_trace() works"""
        aln = load_aligned_seqs("data/brca1.fasta", moltype="dna")
        aln = aln.take_seqs(["Human", "Chimpanzee"])
        aln = aln[:200]
        dp = aln.dotplot()
        dp.figure
        trace_names = dp.get_trace_titles()

        self.assertTrue(
            dp.get_trace_titles() != [] and len(trace_names) == len(dp.traces),
            "No traces found for dotplot",
        )
        self.assertTrue(
            [trace_names[i] == dp.traces[i]["name"] for i in range(len(trace_names))],
            "Order of traces don't match with get_trace_titles()",
        )

        for trace_name in trace_names:
            dp.pop_trace(trace_name)
            self.assertFalse(
                trace_name in dp.get_trace_titles(),
                "Trace name still present in get_trace_titles() even after popping off trace",
            )


if __name__ == "__main__":
    main()
