from numpy import array, diag, diagonal, dot, eye, log, sqrt
from numpy.linalg import slogdet
from numpy.testing import assert_allclose, assert_equal

import cogent3.util.misc

from cogent3.maths.util import safe_p_log_p

from .util import safe_log


__author__ = "Gavin Huttley"
__copyright__ = "Copyright 2007-2019, The Cogent Project"
__credits__ = ["Gavin Huttley"]
__license__ = "BSD-3"
__version__ = "2019.9.13a"
__maintainer__ = "Gavin Huttley"
__email__ = "Gavin.Huttley@anu.edu.au"
__status__ = "Alpha"


def paralinear_discrete_time(P, pi, validate=False):
    """
    Parameters
    ----------
    P : numpy array
        row stochastic matrix
    pi : numpy array
        row vector state frequencies
    validate : bool
    Returns
    -------
    the paralinear metric of Lake (1994) for a discrete time process
    """
    if validate:
        assert_equal(P.shape[0], pi.shape[0], err_msg="pi mismatched shape")
        assert pi.ndim == 1, "pi has incorrect dimension"
        assert_allclose(P.sum(axis=1), 1, err_msg="invalid P")
        assert_allclose(pi.sum(), 1, err_msg="invalid pi")

    pi_end = diag(dot(pi, P))
    pi = diag(pi)
    J = dot(pi, P)
    sign, b = slogdet(J)
    b *= sign
    b *= -1
    sign, a = slogdet(pi)
    a *= sign / 2

    sign, c = slogdet(pi_end)
    c *= sign / 2
    return b + a + c


def paralinear_continuous_time(P, pi, Q, validate=False):
    """
    Parameters
    ----------
    P : numpy array
        row stochastic matrix
    pi : numpy array
        row vector state frequencies
    Q : numpy array
        rate-matrix, rows sum to zero, off-diagnoal >= 0. If None, returns
        paralinear_discrete_time(P, pi, validate)
    validate : bool
    Returns
    -------
    the paralinear metric of Lake (1994)
    """
    if validate:
        assert_equal(Q.shape, P.shape, err_msg="Q/P mismatched shape")
        assert_equal(Q.shape[0], pi.shape[0], err_msg="pi mismatched shape")
        assert pi.ndim == 1, "pi has incorrect dimension"
        assert_allclose(Q.sum(axis=1), 0, err_msg="invalid Q", atol=1e-12)
        assert_allclose(P.sum(axis=1), 1, err_msg="invalid P")
        assert_allclose(pi.sum(), 1, err_msg="invalid pi")
        off_diag = ~eye(Q.shape[0])
        assert not (Q[off_diag] < 0).any(), "invalid Q"

    # todo need to implement a safe natural log to handle possible 0 elements
    a = -log(pi).sum() / 2
    b = -diagonal(Q).sum()
    c = log(dot(pi, P)).sum() / 2
    pl = a + b + c
    pl = getattr(pl, "real", pl)
    return pl


def jsd(freqs1, freqs2, validate=False):
    """
    Parameters
    ----------
    freqs1 : one dimensional array
        row vector frequencies, sum to 1
    freqs2 : one dimensional array
        row vector frequencies, sum to 1
    validate : bool
    Returns
    -------
    the mathematical calculation of Jensen–Shannon divergence
    between two probability distributions
    """
    # Convert input arrays into numpy arrays
    freqs1 = array(freqs1)
    freqs2 = array(freqs2)

    if validate:
        assert_equal(
            freqs1.shape, freqs2.shape, err_msg="freqs1/freqs2 mismatched shape"
        )
        assert freqs1.ndim == 1, "freqs1 has incorrect dimension"
        assert freqs2.ndim == 1, "freqs2 has incorrect dimension"
        assert_allclose(sum(freqs1), 1, err_msg="invalid freqs1")
        assert_allclose(sum(freqs2), 1, err_msg="invalid freqs2")

    H_mn = safe_p_log_p(freqs1 / 2 + freqs2 / 2).sum()
    mn_H = sum([sum(i) for i in map(safe_p_log_p, [freqs1, freqs2])]) / 2
    return H_mn - mn_H


@cogent3.util.misc.extend_docstring_from(jsd)
def jsm(*args, **kwargs):
    """
    Returns
    -------
    The square root of the Jensen–Shannon divergence,
    which is a metric often referred to as Jensen-Shannon distance (2003)
    """
    val = jsd(*args, **kwargs)
    return sqrt(val)
