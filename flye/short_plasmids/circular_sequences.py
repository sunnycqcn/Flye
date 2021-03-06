#(c) 2016-2018 by Authors
#This file is a part of Flye program.
#Released under the BSD license (see LICENSE file)


import flye.short_plasmids.utils as utils
import flye.short_plasmids.unmapped_reads as unmapped
import flye.utils.fasta_parser as fp
from flye.polishing.alignment import read_paf, PafHit
import logging

logger = logging.getLogger()

def is_circular_read(hit, max_overhang=150):
    if hit.query != hit.target:
        return False

    if not hit.query_start < hit.query_end < hit.target_start < hit.target_end:
        return False

    if not hit.query_left_overhang() < max_overhang:
        return False

    if not hit.target_right_overhang() < max_overhang:
        return False

    return True


def extract_circular_reads(unmapped_reads_mapping, max_overhang=150):
    circular_reads = dict()

    with open(unmapped_reads_mapping) as f:
        for raw_hit in f:
            current_hit = PafHit(raw_hit)
            if is_circular_read(current_hit, max_overhang):
                hit = circular_reads.get(current_hit.query)
                if hit is None or current_hit.query_mapping_length() > \
                   hit.query_mapping_length():
                    circular_reads[current_hit.query] = current_hit

    return circular_reads


def trim_circular_reads(circular_reads, unmapped_reads):
    trimmed_circular_reads = dict()

    i = 0
    for read, hit in circular_reads.items():
        sequence = unmapped_reads[read][:hit.target_start].upper()
        trimmed_circular_reads["circular_read" + str(i)] = sequence
        i += 1

    return trimmed_circular_reads


def mapping_segments_without_intersection(circular_pair):
    if not circular_pair[1].query_start < circular_pair[1].query_end < \
           circular_pair[0].query_start < circular_pair[0].query_end:
        return False

    if not circular_pair[0].target_start < circular_pair[0].target_end < \
           circular_pair[1].target_start < circular_pair[1].target_end:
        return False

    return True


def extract_circular_pairs(unmapped_reads_mapping, max_overhang=300):
    hits = read_paf(unmapped_reads_mapping)
    hits.sort(key=lambda hit: (hit.query, hit.target))

    circular_pairs = []
    circular_pair = [None, None]
    previous_hit = None
    has_overlap = False
    is_circular = False

    used_reads = set()

    for hit in hits:
        if hit.query == hit.target:
            continue

        if hit.query in used_reads or hit.target in used_reads:
            continue

        if previous_hit is None or \
           hit.query != previous_hit.query or \
           hit.target != previous_hit.target:
            if previous_hit is not None and has_overlap and is_circular:
                if mapping_segments_without_intersection(circular_pair):
                    circular_pairs.append(circular_pair)
                    used_reads.add(circular_pair[0].target)
                    used_reads.add(circular_pair[0].query)

            circular_pair = [None, None]
            has_overlap = False
            is_circular = False
            previous_hit = hit

        if not has_overlap:
            if hit.query_right_overhang() < max_overhang and \
               hit.target_left_overhang() < max_overhang:
                has_overlap = True
                circular_pair[0] = hit
                continue

        if not is_circular:
            if hit.query_left_overhang() < max_overhang and \
               hit.target_right_overhang() < max_overhang:
                is_circular = True
                circular_pair[1] = hit

    return circular_pairs


def trim_circular_pairs(circular_pairs, unmapped_reads):
    trimmed_circular_pairs = dict()

    for i, pair in enumerate(circular_pairs):
        lhs = unmapped_reads[pair[0].query]
        rhs = unmapped_reads[pair[0].target]
        trimmed_seq = lhs[pair[1].query_end:pair[0].query_end]
        trimmed_seq += rhs[pair[0].target_end:]
        trimmed_circular_pairs["circular_pair" + str(i)] = trimmed_seq.upper()

    return trimmed_circular_pairs


def extract_unique_plasmids(trimmed_reads_mapping, trimmed_reads_path,
                            mapping_rate_threshold=0.8,
                            max_length_difference=500,
                            min_sequence_length=1000):
    hits = read_paf(trimmed_reads_mapping)
    trimmed_reads = set()

    for hit in hits:
        trimmed_reads.add(hit.query)
        trimmed_reads.add(hit.target)

    trimmed_reads = list(trimmed_reads)
    n_trimmed_reads = len(trimmed_reads)
    read2int = dict()
    int2read = dict()

    for i in xrange(n_trimmed_reads):
        read2int[trimmed_reads[i]] = i
        int2read[i] = trimmed_reads[i]

    similarity_graph = [[] for _ in xrange(n_trimmed_reads)]
    hits.sort(key=lambda hit: (hit.query, hit.target))

    current_hit = None
    query_mapping_segments = []
    target_mapping_segments = []
    seq_lengths = {}

    for hit in hits:
        seq_lengths[hit.query] = hit.query_length
        seq_lengths[hit.target] = hit.target_length

        if hit.query == hit.target:
            continue

        if (current_hit is None or
                hit.query != current_hit.query or
                hit.target != current_hit.target):
            if current_hit is not None:
                query_length = current_hit.query_length
                target_length = current_hit.target_length
                query_mapping_rate = \
                    unmapped.calc_mapping_rate(query_length,
                                               query_mapping_segments)
                target_mapping_rate = \
                    unmapped.calc_mapping_rate(target_length,
                                               target_mapping_segments)

                if (query_mapping_rate > mapping_rate_threshold or
                        target_mapping_rate > mapping_rate_threshold):
                    #abs(query_length - target_length) < max_length_difference:
                    vertex1 = read2int[current_hit.query]
                    vertex2 = read2int[current_hit.target]
                    similarity_graph[vertex1].append(vertex2)
                    similarity_graph[vertex2].append(vertex1)

            query_mapping_segments = []
            target_mapping_segments = []
            current_hit = hit

        query_mapping_segments.append(
            unmapped.MappingSegment(hit.query_start, hit.query_end))
        target_mapping_segments.append(
            unmapped.MappingSegment(hit.target_start, hit.target_end))

    connected_components, n_components = \
        utils.find_connected_components(similarity_graph)

    groups = [[] for _ in xrange(n_components)]
    for i in xrange(len(connected_components)):
        groups[connected_components[i]].append(int2read[i])

    #for g in groups:
    #    logger.debug("Group {0}".format(len(g)))
    #    for s in g:
    #        logger.debug("\t{0}".format(seq_lengths[s]))


    groups = [group for group in groups if len(group) > 1]
    trimmed_reads_dict = fp.read_sequence_dict(trimmed_reads_path)
    unique_plasmids = dict()

    for group in groups:
        sequence = trimmed_reads_dict[group[0]]
        if len(sequence) >= min_sequence_length:
            unique_plasmids[group[0]] = sequence

    return unique_plasmids
