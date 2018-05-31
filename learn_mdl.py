#!/usr/bin/python
# -*- coding: utf-8 -*-
# Author: Hao WANG

"""
FMDL Segmenter:
High-accuracy Unsupervised Subword Segmentation Using Minimum Description Length
Learn a finite vocabulary for encoding/segmentation.
"""
import os
import sys
import math
import warnings
import argparse
from collections import Counter
from modules.DataSet import EOS
from modules.DataSet import DataSet
from modules.CodeBook import CodeBook
try:
    from tqdm import tqdm
except ImportError:
    warnings.warn("tqdm is not installed.")
    sys.exit()

import logging
logging.basicConfig(
    format='%(asctime)s : %(message)s', 
    datefmt='%Y-%m-%d %H:%M:%S', 
    level=logging.INFO)
logger = logging.getLogger("FMDL")



class FMDL(object):
    def __init__(self, dataset, min_count, vocab_size):
        super(FMDL, self).__init__()

        self.min_count = min_count
        self.vocab_size = vocab_size
        self.log_base = 0 
        self.data_len = 0
        self.dataset = dataset

    def collect_candidates(self, pair_stats, threshold=0.8):
        candidates = []
        common_pair = filter(lambda x: x[1] >= self.min_count,
                             pair_stats.most_common(self.vocab_size // 2))
        for pair, total in common_pair:
            w1, w2 = pair
            cost = self.compute_cost(w1, w2, total)
            if sum(cost) < 0:
                candidates.append((pair, total, cost))
        ceil = math.ceil(len(candidates) * threshold)
        sorted_candidates = sorted(candidates, key=lambda x: sum(x[-1]))[:ceil]
        return sorted_candidates

    def compute_cost(self, w1, w2, total):
        c1, c2 = self.codebook[w1], self.codebook[w2]

        
        code_cost = self.compute_code_cost(w1, w2, c1, c2, total) * self.log_base
        data_cost = self.compute_data_cost(
            float(total), float(c1), float(c2), self.data_len)
        return code_cost, data_cost

    def compute_data_cost(self, c1w2, c1, c2, n):
        data_cost = 0.0
        data_cost += c1 * math.log(c1 / n)
        data_cost -= (c1 - c1w2) * \
            math.log((c1 - c1w2) / n) if c1 > c1w2 else 0

        data_cost += c2 * math.log(c2 / n)
        data_cost -= (c2 - c1w2) * \
            math.log((c2 - c1w2) / n) if c2 > c1w2 else 0

        data_cost -= c1w2 * math.log(c1w2 / n)
        data_cost += (n - c1 - c2) * math.log((n - c1w2) / n)
        return data_cost

    def compute_code_cost(self, w1, w2, c1, c2, total):
        code_cost = 0.0
        if total > 0:
            code_cost += len(w1 + w2)
        if total == c1:
            code_cost -= len(w1)
        if total == c2:
            code_cost -= len(w2)
        return -code_cost

    def check_valid(self, pair, total):
        indices = self.dataset.search_indices(pair)
        for (pw, w1, w2, nw) in indices:
            if pw + w1 in self.codebook:
                total -= 1
            elif w2 + nw in self.codebook:
                total -= 1
        return total

    def commit_and_success(self, pair, total, cost):
        w1, w2 = pair
        word = w1 + w2
        total = self.check_valid(pair, total)
        if total < self.min_count:
            return False
        self.data_len -= total
        if sum(self.compute_cost(w1, w2, total)) > 0:
            return False
        self.codebook[word] += total
        self.codebook[w1] -= total
        self.codebook[w2] -= total

        if self.codebook[w1] < 1:
            del self.codebook[w1]
        if self.codebook[w2] < 1:
            del self.codebook[w2]
        return True

    def update_codebook(self, candidates):
        updated = 0
        init_vocab_size = len(self.codebook)
        for candidate in tqdm(candidates, ncols=0, 
                 desc="Commit to codebook", total=len(candidates)):
            if len(self.codebook) > self.vocab_size:
                logger.info("")
                logger.info("Vocabulary size: {} -> {}".\
                    format(init_vocab_size, len(self.codebook)))
                return False
            pair, total, cost = candidate
            if self.commit_and_success(pair, total, cost):
                updated += 1
        logger.info("Vocabulary size: {} -> {}".\
            format(init_vocab_size, len(self.codebook)))
        return True

    def train(self, iterations, verbose):
        self.dataset.build_vocab()
        self.log_base = -math.log(len(self.dataset.vocab))
        for epoch in range(iterations):
            logger.info("-"* 30 + " Epoch: [{}] ".format(epoch) + "-"* 30)
            
            if verbose:
                self.dataset.show_samples()
            self.codebook = CodeBook(self.dataset.vocab, self.dataset.stopwords)
            self.data_len = self.dataset.data_len
            # pair_statistics
            pair_stats = self.dataset.build_pair_stats()
            # collecting candidates
            candidates = self.collect_candidates(pair_stats)
            # iterative procedure
            if not self.update_codebook(candidates):
                break
            # apply codebook to encode data
            self.dataset.apply_codebook(self.codebook)
        return self.codebook


def main(args):
    dataset = DataSet(args.train)
    mdl = FMDL(dataset, args.min_count,  args.vocab_size)
    trainer = mdl.train
    codebook = trainer(args.iterations, args.verbose)
    if args.verbose:
        dataset.show_samples()
    codebook.save(args.codebook)


def create_parser():
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="learning FMDL-based word segmentation")
    parser.add_argument(
        '--train', '-t', type=str, required=True,
        metavar='PATH',
        help="Input unsegmented text for training (default: standard input).")
    parser.add_argument(
        '--output', '-o', type=argparse.FileType('w'), default=None,
        metavar='PATH',
        help="Output segmented (default: standard output)")
    parser.add_argument(
        '--codebook', '-c', type=argparse.FileType('w'), default="codebook",
        metavar='FILE',
        help="Output file for codebook")
    parser.add_argument(
        '--iterations', '-i', type=int, default=5,
        help="# of iterations for FMDL learning (default: %(default)s).")
    parser.add_argument(
        '--min_count', type=int, default=5,
        help="ignore the new words with a frequency lower than this. (default: %(default)s).")
    parser.add_argument(
        '--vocab_size', type=int, default=20000,
        help="vocabulary size of codebook. (default: %(default)s).")
    parser.add_argument(
        '--verbose', '-v', action="store_true",
        help="verbose mode, print the details.")

    return parser


if __name__ == '__main__':
    parser = create_parser()
    args = parser.parse_args()
    main(args)
