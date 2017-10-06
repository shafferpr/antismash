# License: GNU Affero General Public License v3 or later
# A copy of GNU AGPL v3 should have been included in this software package in LICENSE.txt.

# for test files, silence irrelevant and noisy pylint warnings
# pylint: disable=no-self-use,protected-access,missing-docstring

import unittest

from antismash.modules.clusterblast import svg_builder

class TestSVGHelpers(unittest.TestCase):
    def test_make_neighbours_distinct(self):
        def run(values):
            res = svg_builder.make_neighbours_distinct(values)
            # ensure that we haven't dropped or gained any values
            assert len(res) == len(values)
            return res
        assert run([1]) == [1]
        assert run([2]) == [2]
        assert run(range(3)) == [0, 2, 1]
        assert run(range(4)) == [0, 2, 1, 3]
        assert run(range(5)) == [4, 0, 2, 1, 3]
        assert run(range(6)) == [0, 3, 1, 4, 2, 5]
        assert run(range(7)) == [6, 0, 3, 1, 4, 2, 5]