# License: GNU Affero General Public License v3 or later
# A copy of GNU AGPL v3 should have been included in this software package in LICENSE.txt.

"""Test suite for the cassis cluster detection plugin"""

# for test files, silence irrelevant and noisy pylint warnings
# pylint: disable=no-self-use,protected-access,missing-docstring

import os
from shutil import copy
from tempfile import TemporaryDirectory
import unittest

from Bio.Seq import Seq
from Bio.SeqFeature import FeatureLocation
from minimock import mock, restore

from antismash.common import path, secmet
from antismash.common.test import helpers
from antismash.config import build_config, destroy_config
from antismash.detection import cassis
from antismash.detection.cassis.runners import run_fimo


# helper methods
def convert_newline(string):
    """Convert all line endings to \n for OS independency"""
    return "\n".join(string.splitlines())


def read_generated_expected_file(generated_file, expected_file):
    """Read generated and expected files and save to string variables"""
    generated_string = ""
    with open(generated_file) as handle:
        generated_string = handle.read()
    generated_string = convert_newline(generated_string.rstrip())

    expected_string = ""
    with open(path.get_full_path(__file__, "data", expected_file)) as handle:
        expected_string = handle.read()
    expected_string = convert_newline(expected_string.rstrip())

    return [generated_string, expected_string]


def create_fake_record():
    """Set up a fake sequence record"""
    seq_record = helpers.DummyRecord(seq=Seq("acgtacgtacgtacgtacgtacgtacgtacgtacgtacgtacgtacgta" * 196))
    seq_record.name = "test"
    locations = [FeatureLocation(100, 300, strand=1), FeatureLocation(101, 299, strand=-1),
                 FeatureLocation(250, 350, strand=1), FeatureLocation(500, 1000, strand=1),
                 FeatureLocation(1111, 1500, strand=-1), FeatureLocation(2000, 2200, strand=-1),
                 FeatureLocation(2999, 4000, strand=1), FeatureLocation(4321, 5678, strand=1),
                 FeatureLocation(6660, 9000, strand=-1)]
    for i in range(9):
        cds = helpers.DummyCDS(locus_tag="gene" + str(i+1))
        cds.location = locations[i]
        seq_record.add_cds_feature(cds)
        seq_record.add_gene(secmet.Gene(locations[i], locus_tag="gene" + str(i+1)))
        if i == 3 or i == 5:
            cds.sec_met = secmet.qualifiers.SecMetQualifier({"faked"}, [])
            cds.gene_functions.add(secmet.feature.GeneFunction.CORE, "testtool", "dummy")

    return seq_record


class TestGetPromoters(unittest.TestCase):
    """ This class tests each section of get_promoters in turn. Each section has an
        explicit test to ensure its coverage (hence the mocking of enumerate)."""
    def setUp(self):
        self.record = helpers.DummyRecord(seq=Seq("ACGT"*25))

    def tearDown(self):
        restore()

    def add_gene(self, name, start, end, strand=1):
        gene = secmet.feature.Gene(FeatureLocation(start, end, strand), locus_tag=name)
        self.record.add_gene(gene)
        return gene

    def get_promoters(self, upstream, downstream):
        return cassis.get_promoters(self.record, self.record.get_genes(), upstream, downstream)

    def check_single_promoter(self, promoter, name, start, end):
        print(promoter)
        assert isinstance(promoter, cassis.Promoter)
        assert not isinstance(promoter, cassis.CombinedPromoter)
        assert name == promoter.gene_name
        assert start == promoter.start
        assert end == promoter.end

    def check_combined_promoter(self, promoter, first_gene, second_gene, start, end):
        print(promoter)
        assert isinstance(promoter, cassis.CombinedPromoter)
        assert promoter.get_gene_names() == [first_gene, second_gene]
        assert promoter.get_id() == "+".join(promoter.get_gene_names())
        assert promoter.start == start
        assert promoter.end == end

    def test_single_gene_forward(self):
        self.add_gene("A", 10, 20, 1)
        assert len(self.record.get_genes()) == 1

        promoters = self.get_promoters(15, 5)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "A", 0, 15)

        promoters = self.get_promoters(15, 25)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "A", 0, 20)

        promoters = self.get_promoters(5, 5)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "A", 5, 15)

        promoters = self.get_promoters(5, 25)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "A", 5, 20)

    def test_single_gene_reverse(self):
        self.add_gene("B", 10, 80, -1)
        assert len(self.record.get_genes()) == 1

        promoters = self.get_promoters(5, 75)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "B", 10, 85)

        promoters = self.get_promoters(25, 75)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "B", 10, 99)

        promoters = self.get_promoters(5, 5)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "B", 75, 85)

        promoters = self.get_promoters(25, 5)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "B", 75, 99)

    def test_first_gene_forward(self):
        # ensure coverage only considers this gene of interest
        gene_of_interest = self.add_gene("A", 10, 20, 1)
        mock("enumerate", returns=[(0, gene_of_interest)])
        other_gene = self.add_gene("B", 30, 40, 1)

        for strand in [1, -1]:
            start, end = sorted([30, 40])[::strand]
            other_gene.location = FeatureLocation(start, end, strand)
            print(other_gene.location)

            promoters = self.get_promoters(5, 75)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "A", 5, 20)

            promoters = self.get_promoters(25, 75)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "A", 0, 20)

            promoters = self.get_promoters(5, 5)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "A", 5, 15)

            promoters = self.get_promoters(25, 5)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "A", 0, 15)

    def test_first_gene_reverse(self):
        gene_of_interest = self.add_gene("A", 20, 10, -1)
        mock("enumerate", returns=[(0, gene_of_interest)])
        other_gene = self.add_gene("B", 30, 40, 1)

        # counts as a shared promoter if strands are opposite and ranges are large
        # so a small test of the opposite strand
        promoters = self.get_promoters(2, 4)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "A", 16, 22)

        # then reverse the gene and do more thorough testing
        other_gene.location = FeatureLocation(40, 30, -1)
        promoters = self.get_promoters(5, 75)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "A", 10, 25)

        promoters = self.get_promoters(5, 5)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "A", 15, 25)

        promoters = self.get_promoters(25, 5)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "A", 15, 29)

        promoters = self.get_promoters(25, 75)
        assert len(promoters) == 1
        self.check_single_promoter(promoters[0], "A", 10, 29)

    def test_last_gene_forward(self):
        other_gene = self.add_gene("A", 10, 20, 1)
        # ensure coverage only considers this gene of interest
        gene_of_interest = self.add_gene("B", 30, 40, 1)
        mock("enumerate", returns=[(1, gene_of_interest)])

        for strand in [1, -1]:
            start, end = sorted([10, 20])[::strand]
            other_gene.location = FeatureLocation(start, end, strand)
            print(other_gene.location)

            promoters = self.get_promoters(5, 75)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 25, 40)

            promoters = self.get_promoters(25, 75)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 21, 40)

            promoters = self.get_promoters(5, 5)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 25, 35)

            promoters = self.get_promoters(25, 5)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 21, 35)

    def test_last_gene_reverse(self):
        other_gene = self.add_gene("A", 10, 20, 1)
        # ensure coverage only considers this gene of interest
        gene_of_interest = self.add_gene("B", 40, 30, -1)
        mock("enumerate", returns=[(1, gene_of_interest)])

        for strand in [1, -1]:
            start, end = sorted([10, 20])[::strand]
            other_gene.location = FeatureLocation(start, end, strand)
            print(other_gene.location)

            promoters = self.get_promoters(5, 75)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 30, 45)

            promoters = self.get_promoters(65, 75)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 30, 99)

            promoters = self.get_promoters(5, 5)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 35, 45)

            promoters = self.get_promoters(65, 5)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 35, 99)

    def test_special_case(self):
        first = self.add_gene("A", 20, 10, -1)
        second = self.add_gene("B", 30, 50, 1)

        promoters = self.get_promoters(5, 5)
        assert len(promoters) == 1
        assert second.location.end > second.location.start + 5
        assert first.location.start > first.location.end + 5
        self.check_combined_promoter(promoters[0], "A", "B", 15, 35)

        promoters = self.get_promoters(5, 15)
        assert len(promoters) == 1
        assert not first.location.start > first.location.end + 15
        assert second.location.end > second.location.start + 15
        self.check_combined_promoter(promoters[0], "A", "B", 10, 45)

        first.location = FeatureLocation(35, 10, -1)
        second.location = FeatureLocation(45, 60, 1)

        promoters = self.get_promoters(25, 20)
        assert len(promoters) == 1
        assert first.location.start > first.location.end + 20
        assert not second.location.end > second.location.start + 20
        self.check_combined_promoter(promoters[0], "A", "B", 15, 60)

        promoters = self.get_promoters(25, 30)
        assert not second.location.end > second.location.start + 30
        assert not first.location.start > first.location.end + 30
        assert len(promoters) == 1
        self.check_combined_promoter(promoters[0], "A", "B", 10, 60)

    def test_normal_case_forward(self):
        other = self.add_gene("A", 10, 20, 1)
        gene_of_interest = self.add_gene("B", 40, 60, 1)
        self.add_gene("C", 70, 80, 1)
        mock("enumerate", returns=[(1, gene_of_interest)])

        for strand in [-1, 1]:
            start, end = sorted([other.location.start, other.location.end])[::strand]
            other.location = FeatureLocation(start, end, strand)

            promoters = self.get_promoters(5, 5)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 35, 45)

            promoters = self.get_promoters(5, 25)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 35, 60)

            promoters = self.get_promoters(25, 5)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 21, 45)

            promoters = self.get_promoters(25, 25)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 21, 60)

    def test_normal_case_reverse(self):
        self.add_gene("A", 10, 20, 1)
        gene_of_interest = self.add_gene("B", 40, 60, -1)
        other = self.add_gene("C", 80, 70, -1)
        mock("enumerate", returns=[(1, gene_of_interest)])

        for strand in [-1]:
            start, end = sorted([other.location.start, other.location.end])[::strand]
            other.location = FeatureLocation(start, end, strand)

            promoters = self.get_promoters(5, 5)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 55, 65)

            promoters = self.get_promoters(5, 25)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 40, 65)

            promoters = self.get_promoters(25, 5)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 55, 69)

            promoters = self.get_promoters(25, 25)
            assert len(promoters) == 1
            self.check_single_promoter(promoters[0], "B", 40, 69)

    def test_bad_strand(self):
        self.add_gene("A", 10, 20, 0)
        with self.assertRaisesRegex(ValueError, "Gene A has unknown strand: 0"):
            self.get_promoters(5, 5)


class TestCassisMethods(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory(prefix="as_cassis")
        self.options = build_config(["--cpus", "2", "--output-dir", self.tempdir.name],
                                    isolated=True, modules=[cassis])

    def tearDown(self):
        destroy_config()
        self.tempdir.cleanup()
        for subdir in ["meme", "fimo"]:
            assert not os.path.exists(path.get_full_path(__file__, subdir))
        assert not os.path.isfile(path.get_full_path(__file__, "data", "test_promoter_positions.csv"))
        assert not os.path.isfile(path.get_full_path(__file__, "data", "test_promoter_sequences.fasta"))

    def test_plus_minus(self):
        self.assertEqual(len(cassis._plus_minus), 250)

    def test_get_anchor_genes(self):
        anchor_genes = ["gene4", "gene6"]
        seq_record = create_fake_record()
        self.assertEqual(cassis.get_anchor_genes(seq_record), anchor_genes)

    def test_ignore_overlapping(self):
        expected_not_ignored = ["gene1", "gene4", "gene5", "gene6", "gene7", "gene8", "gene9"]
        expected_ignored = ["gene2", "gene3"]
        seq_record = create_fake_record()
        not_ignored, ignored = cassis.ignore_overlapping(seq_record.get_genes())

        self.assertEqual([x.locus_tag for x in ignored], expected_ignored)
        self.assertEqual([x.locus_tag for x in not_ignored], expected_not_ignored)

    def test_get_promoters(self):
        upstream_tss = 1000
        downstream_tss = 50
        seq_record = create_fake_record()
        genes, ignored_genes = cassis.ignore_overlapping(seq_record.get_genes())  # ignore ignored_genes

        # see cassis/promoterregions.png for details
        # [[start_prom1, end_prom1], [start_prom2, end_prom2], ...]
        expected_promoters = [
            [0, 150],
            [301, 550],
            [1450, 1999],
            [2150, 3049],
            [4001, 4371],
            [8950, 9603],
        ]

        promoters = cassis.get_promoters(seq_record, genes, upstream_tss, downstream_tss)
        self.assertEqual(list(map(lambda x: [x.start, x.end], promoters)), expected_promoters)
        cassis.write_promoters_to_file(self.options.output_dir, seq_record.name, promoters)
        # read expected files and save to string variable
        expected_sequences_file = ""
        with open(path.get_full_path(__file__, "data", "expected_promoter_sequences.fasta")) as handle:
            expected_sequences_file = handle.read()
        expected_sequences_file = convert_newline(expected_sequences_file.rstrip())

        expected_positions_file = ""
        with open(path.get_full_path(__file__, "data", "expected_promoter_positions.csv")) as handle:
            expected_positions_file = handle.read()
        expected_positions_file = convert_newline(expected_positions_file.rstrip())

        # read test files and save to string variable
        sequences_file = ""
        with open(os.path.join(self.options.output_dir, seq_record.name + "_promoter_sequences.fasta")) as handle:
            sequences_file = handle.read()
        sequences_file = convert_newline(sequences_file.rstrip())

        positions_file = ""
        with open(os.path.join(self.options.output_dir, seq_record.name + "_promoter_positions.csv")) as handle:
            positions_file = handle.read()
        positions_file = convert_newline(positions_file.rstrip())

        self.assertEqual(sequences_file, expected_sequences_file)
        self.assertEqual(positions_file, expected_positions_file)

    def test_get_anchor_promoter(self):
        anchor = "gene3"
        promoters = [cassis.Promoter("gene1", 1, 1),
                     cassis.Promoter("gene2", 2, 2),
                     cassis.CombinedPromoter("gene3", "gene4", 3, 4),
                     cassis.Promoter("gene5", 5, 5)]
        self.assertEqual(cassis.get_anchor_promoter(anchor, promoters), 2)

    def test_get_promoter_sets(self):
        meme_dir = os.path.join(self.options.output_dir, "meme")
        anchor_promoter = 5
        promoters = [cassis.Promoter("gene1", 1, 1, seq=Seq("acgtacgtacgtacgt")),
                     cassis.Promoter("gene2", 2, 2, seq=Seq("acgtacgtacgtacgt")),
                     cassis.CombinedPromoter("gene3", "gene4", 3, 4, seq=Seq("acgtacgtacgtacgt")),
                     cassis.Promoter("gene5", 5, 5, seq=Seq("acgtacgtacgtacgt")),
                     cassis.Promoter("gene6", 6, 6, seq=Seq("acgtacgtacgtacgt")),
                     # promoter with index=5 --> anchor promoter
                     cassis.Promoter("gene7", 7, 7, seq=Seq("acgtacgtacgtacgt")),
                     cassis.Promoter("gene8", 8, 8, seq=Seq("acgtacgtacgtacgt")),
                     cassis.Promoter("gene9", 9, 9, seq=Seq("acgtacgtacgtacgt"))]

        expected_promoter_sets = [
            {"plus": 0, "minus": 3, "score": None},
            {"plus": 0, "minus": 4, "score": None},
            {"plus": 0, "minus": 5, "score": None},
            {"plus": 1, "minus": 2, "score": None},
            {"plus": 1, "minus": 3, "score": None},
            {"plus": 1, "minus": 4, "score": None},
            {"plus": 1, "minus": 5, "score": None},
            {"plus": 2, "minus": 1, "score": None},
            {"plus": 2, "minus": 2, "score": None},
            {"plus": 2, "minus": 3, "score": None},
            {"plus": 2, "minus": 4, "score": None},
            {"plus": 2, "minus": 5, "score": None},
        ]
        self.assertEqual(cassis.get_promoter_sets(meme_dir, anchor_promoter, promoters), expected_promoter_sets)

    def test_filter_meme_results(self):
        meme_dir = os.path.join(self.options.output_dir, "meme")
        anchor = "AFUA_6G09660"
        promoter_sets = [
            {"plus": 0, "minus": 3},
        ]
        expected_motifs = [{
            "plus": 0,
            "minus": 3,
            "score": "3.9e+003",
            "seqs": [
                "TTTCGACCCGTC",
                "TTTCAAACCGTC",
                "TTTTGATTCGTC",
                "TTTTGACCGGTC",
                "TTTTAGACGGTC",
                "TTTTACCTCGTC",
                "TCTCGATCCGTC",
                "TTTCTATCCGTT",
                "TTTTGGACCGCC",
                "ATTTGGCCTGTC",
                "TGTTGTCTCGTC",
                "TTTGAGGCCGTC",
                "TTGTATTCTGTC",
                "TTTCTTCCTGTT",
            ]
        }]

        # this is a "real" MEME output file, I was too lazy to create my own fake XML file
        source = path.get_full_path(__file__, "data", "real_meme.xml")
        target = os.path.join(meme_dir, "+00_-03")
        if not os.path.exists(target):
            os.makedirs(target)
        copy(source, os.path.join(target, "meme.xml"))  # overwrite meme.xml if exists

        self.assertEqual(list(cassis.filter_meme_results(meme_dir, promoter_sets, anchor)), expected_motifs)
        binding_sites, expected_binding_sites = read_generated_expected_file(
            os.path.join(meme_dir, "+00_-03", "binding_sites.fasta"), "expected_binding_sites.fasta")
        self.assertEqual(binding_sites, expected_binding_sites)

    def test_filter_fimo_results(self):
        fimo_dir = os.path.join(self.options.output_dir, "fimo")
        motifs = [{"plus": 0, "minus": 3}]
        # gene2 will be the anchor promoter
        anchor_promoter = 1
        promoters = []
        for i in range(1, 16):
            promoters.append(cassis.Promoter("gene%d" % i, i * 10, i * 10 + 4))
        # need certain amount of promoters, otherwise the proportion of
        # promoters with a motif (motif frequency) will be too high --> error
        expected_motifs = [{"plus": 0, "minus": 3, "hits": {"gene1": 1, "gene2": 2}}]

        # fake FIMO output file, corresponding to expected_motifs
        source = path.get_full_path(__file__, "data", "fake_short_fimo.txt")
        target = os.path.join(fimo_dir, "+00_-03")
        if not os.path.exists(target):
            os.makedirs(target)
        copy(source, os.path.join(target, "fimo.txt"))  # overwrite fimo.txt if exists

        found_motifs = list(cassis.filter_fimo_results(motifs, fimo_dir, promoters, anchor_promoter))
        assert found_motifs == expected_motifs
        bs_per_promoter, expected_bs_per_promoter = read_generated_expected_file(
            os.path.join(target, "bs_per_promoter.csv"), "expected_bs_per_promoter.csv")
        self.assertEqual(bs_per_promoter, expected_bs_per_promoter)

    def test_get_islands(self):
        motifs = [  # 2 different motifs
            {"plus": 0, "minus": 3, "hits": {"gene1": 1, "gene2": 2}},
            {"plus": 0, "minus": 4, "hits": {"gene2": 3, "gene4": 2, "gene5": 1}},
        ]
        # gene2 will be the anchor promoter
        anchor_promoter = 1
        promoters = []
        for i in range(1, 7):
            promoters.append(cassis.Promoter("gene%d" % i, i * 10, i * 10 + 4))
        expected_islands = [  # resulting in 2 different islands (this example)
            {
                # promoter (pos): 1 2 3 4 5 6
                # binding sites: 1 2 0 0 0 0
                # island: |---|
                "start": promoters[0],  # first promoter of island
                "end": promoters[1],  # last promoter of island
                "motif": {"hits": {"gene1": 1, "gene2": 2}, "plus": 0, "minus": 3},  # island is result of this motif
            },
            {
                # promoter (pos): 1 2 3 4 5 6
                # binding sites: 0 3 0 2 1 0
                # island: |-------|
                "start": promoters[1],  # first promoter of island
                "end": promoters[4],  # last promoter of island
                # island is result of this motif
                "motif": {"hits": {"gene2": 3, "gene4": 2, "gene5": 1}, "plus": 0, "minus": 4},
            },
        ]
        assert cassis.get_islands(anchor_promoter, motifs, promoters) == expected_islands

    def test_sort_by_abundance(self):
        islands = [
            {  # island 1: [gene1 -- gene2]
                "start": cassis.Promoter("gene1", 1, 1),
                "end": cassis.Promoter("gene2", 2, 2),
                "motif": {"hits": {"gene1": 1, "gene2": 1}, "plus": 0, "minus": 3, "score": 3},
            },
            {  # island 2: [gene2 -- gene5]
                "start": cassis.Promoter("gene2", 2, 2),
                "end": cassis.Promoter("gene5", 5, 5),
                "motif": {"hits": {"gene2": 1, "gene3": 1, "gene4": 1, "gene5": 1},
                          "plus": 3, "minus": 0, "score": 2},
            },
            {  # island 3: [gene1 -- gene5]
                "start": cassis.Promoter("gene1", 1, 1),
                "end": cassis.Promoter("gene5", 5, 5),
                "motif": {"hits": {"gene1": 1, "gene2": 1, "gene3": 1, "gene4": 1, "gene5": 1},
                          "plus": 3, "minus": 3, "score": 1},
            },
        ]
        # left border: 2x gene1, 1x gene2
        # right border: 2x gene5, 1x gene2

        expected_clusters = [
            {  # cluster 1: [gene1 -- gene5] --> abundance 2+2 (most abundant)
                "start": {"gene": "gene1", "abundance": 2, "score": 1, "plus": 3, "minus": 3},
                "end": {"gene": "gene5", "abundance": 2, "score": 1, "plus": 3, "minus": 3},
            },
            {  # cluster 3: [gene2 -- gene5] --> abundance 1+2, score 2+1 (better/lower)
                "start": {"gene": "gene2", "abundance": 1, "score": 2, "plus": 3, "minus": 0},
                "end": {"gene": "gene5", "abundance": 2, "score": 1, "plus": 3, "minus": 3},
            },
            {  # cluster 2: [gene1 -- gene2] --> abundance 2+1, score 1+3 (worse, higher)
                "start": {"gene": "gene1", "abundance": 2, "score": 1, "plus": 3, "minus": 3},
                "end": {"gene": "gene2", "abundance": 1, "score": 3, "plus": 0, "minus": 3},
            },
            {  # cluster 4: [gene2 -- gene2] --> abundance 1+1
                "start": {"gene": "gene2", "abundance": 1, "score": 2, "plus": 3, "minus": 0},
                "end": {"gene": "gene2", "abundance": 1, "score": 3, "plus": 0, "minus": 3},
            },
        ]
        # abundance: as high as possible
        # score: as low as possible

        self.assertEqual(cassis.sort_by_abundance(islands), expected_clusters)

    def test_check_cluster_predictions(self):
        seq_record = create_fake_record()
        promoters = [cassis.Promoter("gene1", 1, 5),
                     cassis.Promoter("gene2", 6, 10),
                     cassis.CombinedPromoter("gene3", "gene4", 11, 15)]
        ignored_genes = [  # see captured logging
            secmet.Gene(FeatureLocation(1, 5), locus_tag="gene5")
        ]
        clusters = [
            {  # only one cluster for testing
                "start": {"gene": "gene1", "abundance": 1, "score": 1, "plus": 3, "minus": 3},
                "end": {"gene": "gene4", "abundance": 1, "score": 1, "plus": 3, "minus": 3},
            },
        ]
        checked_clusters = [
            {
                "start": {"gene": "gene1", "promoter": "gene1", "abundance": 1, "score": 1, "plus": 3, "minus": 3},
                "end": {"gene": "gene4", "promoter": "gene3+gene4", "abundance": 1, "score": 1, "plus": 3, "minus": 3},
                "genes": 4,
                "promoters": 3,
            },
        ]

        assert cassis.check_cluster_predictions(clusters, seq_record, promoters, ignored_genes) == checked_clusters
        # -------------------- >> begin captured logging << --------------------
        # root: INFO: Best prediction (most abundant): 'gene1' -- 'gene4'
        # root: INFO: Upstream cluster border located at or next to sequence
        #               record border, prediction could have been truncated by record border
        # root: INFO: Downstream cluster border located at or next to sequence
        #               record border, prediction could have been truncated by record border
        # root: INFO: Gene 'gene2' is part of the predicted cluster, but it is
        #               overlapping with another gene and was ignored
        # root: INFO: Gene 'gene2' could have effected the cluster prediction
        # --------------------- >> end captured logging << ---------------------

    def test_cleanup_outdir(self):
        anchor_genes = ["gene1", "gene4"]
        cluster_predictions = {
            "gene1": [
                {  # only one anchor gene and cluster for testing
                    "start": {"gene": "gene1", "promoter": "gene1", "abundance": 1,
                              "score": 1, "plus": 3, "minus": 3},
                    "end": {"gene": "gene4", "promoter": "gene3+gene4", "abundance": 1,
                            "score": 1, "plus": 3, "minus": 3},
                    "genes": 4,
                    "promoters": 3,
                },
            ]
        }

        # create some empty test dirs, which should be deleted during the test
        # prediction! --> keep!
        os.makedirs(os.path.join(self.options.output_dir, "meme", "gene1", "+03_-03"))
        # prediction! --> keep!
        os.makedirs(os.path.join(self.options.output_dir, "fimo", "gene1", "+03_-03"))
        # no prediction --> delete
        os.makedirs(os.path.join(self.options.output_dir, "meme", "gene1", "+04_-04"))
        # no prediction --> delete
        os.makedirs(os.path.join(self.options.output_dir, "fimo", "gene1", "+04_-04"))
        # no prediction --> delete
        os.makedirs(os.path.join(self.options.output_dir, "meme", "gene4", "+03_-03"))
        # no prediction --> delete
        os.makedirs(os.path.join(self.options.output_dir, "fimo", "gene4", "+03_-03"))
        # prediction for this gene, but not from this motif --> delete
        os.makedirs(os.path.join(self.options.output_dir, "meme", "gene4", "+04_-04"))
        # prediction for this gene, but not from this motif --> delete
        os.makedirs(os.path.join(self.options.output_dir, "fimo", "gene4", "+04_-04"))

        cassis.cleanup_outdir(anchor_genes, cluster_predictions, self.options)

        # assert kept directories
        self.assertTrue("gene1" in os.listdir(os.path.join(self.options.output_dir, "meme")))
        self.assertTrue("gene1" in os.listdir(os.path.join(self.options.output_dir, "fimo")))
        self.assertTrue("+03_-03" in os.listdir(os.path.join(self.options.output_dir, "meme", "gene1")))
        self.assertTrue("+03_-03" in os.listdir(os.path.join(self.options.output_dir, "fimo", "gene1")))

        # assert deleted directories
        self.assertTrue("gene4" not in os.listdir(os.path.join(self.options.output_dir, "meme")))
        self.assertTrue("gene4" not in os.listdir(os.path.join(self.options.output_dir, "fimo")))
        self.assertTrue("+04_-04" not in os.listdir(os.path.join(self.options.output_dir, "meme", "gene1")))
        self.assertTrue("+04_-04" not in os.listdir(os.path.join(self.options.output_dir, "fimo", "gene1")))


class TestCassisHelperMethods(unittest.TestCase):
    def test_mprint(self):
        self.assertEqual(cassis.mprint(3, 3), "+03_-03")


class TestPromoters(unittest.TestCase):
    def test_promoter_id(self):
        assert cassis.Promoter("gene1", 1, 5).get_id() == "gene1"
        assert cassis.CombinedPromoter("gene1", "gene2", 1, 5).get_id() == "gene1+gene2"


class TestCassisStorageMethods(unittest.TestCase):
    def test_store_promoters(self):
        promoters = [cassis.Promoter("gene1", 10, 20, seq=Seq("cgtacgtacgt")),
                     cassis.Promoter("gene2", 30, 40, seq=Seq("cgtacgtacgt")),
                     cassis.CombinedPromoter("gene3", "gene4", 50, 60, seq=Seq("cgtacgtacgt"))]
        record_with_promoters = create_fake_record()
        cassis.store_promoters(promoters, record_with_promoters)  # add ("store") promoters to seq_record

        record_without_promoters = create_fake_record()  # just the same, without adding promoters

        # test if store_promoters changed any non-promoter feature (should not!)  # TODO

        # test promoter features
        expected_count = record_without_promoters.get_feature_count() + len(promoters)
        assert expected_count == record_with_promoters.get_feature_count()
        for i in range(len(promoters)):
            feature = record_with_promoters.get_generics()[i]
            assert feature.type == "promoter"
            assert feature.get_qualifier("seq") == ("cgtacgtacgt",)

        # especially test bidirectional promoter feature (third promoter, last feature)
        last_promoter = record_with_promoters.get_generics()[-1]
        assert last_promoter.get_qualifier("locus_tag") == ("gene3", "gene4")
        assert last_promoter.notes == ["bidirectional promoter"]

    def test_store_clusters(self):
        # this test is similar to test_store_promoters
        anchor = "gene3"
        clusters = [
            {  # best prediction
                "start": {"gene": "gene1", "promoter": "gene1", "abundance": 2, "score": 1, "plus": 3, "minus": 3},
                "end": {"gene": "gene4", "promoter": "gene3+gene4", "abundance": 1, "score": 1, "plus": 3, "minus": 3},
                "genes": 4,
                "promoters": 3,
            },
            {  # alternative prediction
                "start": {"gene": "gene1", "promoter": "gene1", "abundance": 1, "score": 1, "plus": 4, "minus": 4},
                "end": {"gene": "gene5", "promoter": "gene5", "abundance": 1, "score": 1, "plus": 4, "minus": 4},
                "genes": 4,
                "promoters": 3,
            },
        ]
        record_with_clusters = create_fake_record()
        record_without_clusters = create_fake_record()  # just the same, without adding clusters

        borders = cassis.create_cluster_borders(anchor, clusters, record_with_clusters)
        assert record_with_clusters.get_feature_count() == record_without_clusters.get_feature_count()

        for border in borders:
            record_with_clusters.add_cluster_border(border)

        # test if store_clusters changed any non-cluster feature (should not!)  # TODO

        # test cluster features
        assert record_without_clusters.get_feature_count() + len(clusters) == record_with_clusters.get_feature_count()
        for i, cluster in enumerate(clusters):
            cluster_border = record_with_clusters.get_cluster_borders()[i]
            self.assertEqual(cluster_border.type, "cluster_border")
            self.assertEqual(cluster_border.tool, "cassis")
            self.assertEqual(cluster_border.get_qualifier("anchor"), (anchor,))
            self.assertEqual(cluster_border.get_qualifier("genes"), (cluster["genes"],))
            self.assertEqual(cluster_border.get_qualifier("promoters"), (cluster["promoters"],))
            self.assertEqual(cluster_border.get_qualifier("gene_left"), (cluster["start"]["gene"],))
            self.assertEqual(cluster_border.get_qualifier("gene_right"), (cluster["end"]["gene"],))
            # don't test all feature qualifiers, only some


class TestCassisUtils(unittest.TestCase):
    def setUp(self):
        self.tempdir = TemporaryDirectory(prefix="as_cassis")
        self.options = build_config(["--cpus", "2", "--output-dir", self.tempdir.name],
                                    isolated=True, modules=[cassis])

    def tearDown(self):
        destroy_config()
        self.tempdir.cleanup()

    def test_run_fimo(self):
        seq_record = create_fake_record()
        meme_dir = os.path.join(self.options.output_dir, "meme")
        fimo_dir = os.path.join(self.options.output_dir, "fimo")
        fimo_subdirs = ["+00_-03", "+03_-00"]

        # fimo input (i)
        # --> sequences to search in
        copy(
            path.get_full_path(__file__, "data", "expected_promoter_sequences.fasta"),
            os.path.join(self.options.output_dir, seq_record.name + "_promoter_sequences.fasta")
        )
        # fimo input (ii)
        # --> meme output (meme.html; motifs to search for)
        # --> file derived from meme output (binding_sites.fasta;
        #      only additional information for users; still checked by fimo)
        for subdir in fimo_subdirs:
            if not os.path.exists(os.path.join(meme_dir, subdir)):
                os.makedirs(os.path.join(meme_dir, subdir))
            copy(path.get_full_path(__file__, "data", "fake_meme.html"),
                 os.path.join(meme_dir, subdir, "meme.html"))
            copy(path.get_full_path(__file__, "data", "fake_binding_sites.fasta"),
                 os.path.join(meme_dir, subdir, "binding_sites.fasta"))

        run_fimo(meme_dir, fimo_dir, seq_record, self.options, verbose=True)

        for subdir in fimo_subdirs:
            fimo_result, expected_fimo_result = read_generated_expected_file(
                                                    os.path.join(self.options.output_dir, "fimo", subdir, "fimo.txt"),
                                                    "fake_long_fimo.txt")

            self.assertEqual(fimo_result, expected_fimo_result)