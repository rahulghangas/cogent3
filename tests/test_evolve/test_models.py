from unittest import TestCase, main
from cogent3.evolve.models import (JC69, F81, HKY85, TN93, GTR, GN, ssGN,
                                   MG94HKY, MG94GTR, GY94, H04G, H04GK, H04GGK,
                                   DSO78, AH96, AH96_mtmammals, JTT92, WG01,
                                   CNFGTR, CNFHKY, GNC, WG01_matrix, WG01_freqs,
                                   get_model, models)
from cogent3.evolve.models import nucleotide_models, codon_models, protein_models, models
from cogent3.evolve.models import available_models
from cogent3.evolve import models as models_module
from itertools import chain


__author__ = "Gavin Huttley"
__copyright__ = "Copyright 2007-2016, The Cogent Project"
__credits__ = ["Gavin Huttley"]
__license__ = "GPL"
__version__ = "3.0a2"
__maintainer__ = "Gavin Huttley"
__email__ = "gavin.huttley@anu.edu.au"
__status__ = "Production"


class CannedModelsTest(TestCase):
    """Check each canned model can actually be instantiated."""

    def _instantiate_models(self, models, **kwargs):
        for model in models:
            model(**kwargs)

    def test_nuc_models(self):
        """excercising nucleotide model construction"""
        self._instantiate_models([JC69, F81, HKY85, GTR, GN, ssGN])

    def test_codon_models(self):
        """excercising codon model construction"""
        self._instantiate_models([CNFGTR, CNFHKY, MG94HKY, MG94GTR, GY94,
                                  H04G, H04GK, H04GGK, GNC])

    def test_aa_models(self):
        """excercising aa model construction"""
        self._instantiate_models([DSO78, AH96, AH96_mtmammals, JTT92, WG01])

    def test_bin_options(self):
        kwargs = dict(with_rate=True, distribution='gamma')
        model = WG01(**kwargs)
        model = GTR(**kwargs)

    def test_empirical_values_roundtrip(self):
        model = WG01()
        assert model.get_motif_probs() == WG01_freqs
        assert (model.calc_exchangeability_matrix('dummy_mprobs') ==
                WG01_matrix).all()

    def test_solved_models(self):
        for klass in [TN93, HKY85, F81]:
            for scaled in [True, False]:
                model = klass(rate_matrix_required=False, do_scaling=scaled)
                model.check_psub_calculations_match()

    def test_get_model(self):
        """get_models successfully creates model instances"""
        for name in models:
            model = get_model(name)

        with self.assertRaises(ValueError):
            # unknown model raises exception
            _ = get_model('blah')


def get_sample_model_types(mod_type=None):
    if mod_type == "nucleotide_models":
        available_mods = nucleotide_models

    if mod_type == "codon_models":
        available_mods = codon_models

    if mod_type == "protein_models":
        available_mods = protein_models

    else:
        available_mods = models

    return available_mods


class AvailableModelsTest(TestCase):

    def setUp(self):
        self.nucleotide_models = get_sample_model_types("nucleotide_model")
        self.codon_models = get_sample_model_types("codon_model")
        self.protein_models = get_sample_model_types("protein_model")
        self.all_models = get_sample_model_types()

    def test_model_abbreviation(self):
        """make sure getting model abbreviations that exist"""
        got = set(available_models().tolist("Abbreviation"))
        expect = set(['JC69', 'CNFGTR', 'DSO78'])
        self.assertTrue(expect < got)

    def test_model_by_type(self):
        """correctly obtain models by type"""
        for model_type in "codon_model nucleotide_model protein_model".split():
            table = available_models(model_type)
            got = table.distinct_values('Model Type')
            self.assertEqual(got, {model_type})

    def test_model_description(self):
        """correctly grabs function descriptions"""
        all_available = available_models()
        for abbrev, desc in all_available.tolist(['Abbreviation', 'Description']):
            func = getattr(models_module, abbrev)
            doc = func.__doc__.split()
            self.assertEqual(desc.split(), doc)


if __name__ == "__main__":
    main()
