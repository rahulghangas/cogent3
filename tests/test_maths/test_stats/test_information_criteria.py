#!/usr/bin/env python
from cogent3.maths.stats.information_criteria import aic, bic
from cogent3.util.unit_test import TestCase, main


__author__ = "Gavin Huttley"
__copyright__ = "Copyright 2007-2019, The Cogent Project"
__credits__ = ["Gavin Huttley"]
__license__ = "BSD-3"
__version__ = "2019.9.13a"
__maintainer__ = "Gavin Huttley"
__email__ = "gavin.huttley@anu.edu.au"
__status__ = "Production"


class InformationCriteria(TestCase):
    """Tests calculation of AIC and BIC measures."""

    def test_aic(self):
        """correctly compute AIC from Burnham & Anderson 2002, p102"""
        self.assertFloatEqual(aic(-9.7039, 4), 27.4078)

    def test_aic_corrected(self):
        """correctly compute AIC corrected for small sample size"""
        # from Burnham & Anderson 2002, p102
        self.assertFloatEqual(aic(-9.7039, 4, sample_size=13), 32.4078)

    def test_bic(self):
        """correctly compute BIC"""
        # against hand calculated
        self.assertFloatEqual(bic(-9.7039, 4, 13), 29.6675974298)


if __name__ == "__main__":
    main()
