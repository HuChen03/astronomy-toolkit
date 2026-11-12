#!/usr/bin/env python3
"""Export HBT-G4 tracks and sink events as an explicit directed merger graph.

Continuity edges advance one snapshot. Sink edges connect records in the same
snapshot; a sunk track has no later continuity edge. Retained orphan records
after sinking stay in the node table with Active=0 for auditability.
"""
import argparse
import json
from collections import defaultdict, deque
from pathlib import Path

import h5py
import numpy as np

NODE_DTYPE = np.dtype([('NodeId', '<i8'), ('Snapshot', '<i4'), ('ScaleFactor', '<f8'),
                       ('TrackId', '<i8'), ('Nbound', '<i8'), ('Mbound', '<f8'),
                       ('HostHaloId', '<i8'), ('Birth', '<i4'), ('Death', '<i4'),
                       ('SinkSnapshot', '<i4'), ('SinkTrackId', '<i8'), ('Active', '?')])
EDGE_DTYPE = np.dtype([('Source', '<i8'), ('Target', '<i8'), ('Kind', 'u1')])
FIELDS = ['TrackId', 'Nbound', 'Mbound', 'HostHaloId', 'SnapshotIndexOfBirth',
          'SnapshotIndexOfDeath', 'SnapshotIndexOfSink', 'SinkTrackId']


def validate_graph(nodes, edges):
    outgoing, indegree = defaultdict(list), np.zeros(len(nodes), dtype=np.int64)
    for edge in edges:
        src, dst, kind = map(int, edge)
        if not 0 <= src < len(nodes) or not 0 <= dst < len(nodes) or src == dst:
            raise ValueError('invalid node reference')
        a, b = nodes[src], nodes[dst]
        if not a['Active'] or not b['Active']:
            raise ValueError('edge refers to a record retained after sinking')
        if kind == 0:
            if int(b['Snapshot']) != int(a['Snapshot']) + 1 or a['TrackId'] != b['TrackId']:
                raise ValueError('invalid continuity edge')
        elif kind == 1:
            if a['Snapshot'] != b['Snapshot'] or a['SinkTrackId'] != b['TrackId'] or a['SinkSnapshot'] != a['Snapshot']:
                raise ValueError('invalid sink event')
        else:
            raise ValueError('unknown edge kind')
        outgoing[src].append(dst)
        indegree[dst] += 1
        if len(outgoing[src]) > 1:
            raise ValueError('more than one descendant for a node')
    queue = deque(np.flatnonzero(indegree == 0).tolist())
    visited = 0
    while queue:
        src = queue.popleft()
        visited += 1
        for dst in outgoing[src]:
            indegree[dst] -= 1
            if indegree[dst] == 0:
                queue.append(dst)
    if visited != len(nodes):
        raise ValueError('cycle in merger graph')


def export(root, count, destination):
    nodes, lookup = [], {}
    previous_ids = set()
    for snap in range(count):
        folder = root / f'{snap:03d}'
        files = sorted(folder.glob(f'SubSnap_{snap:03d}.*.hdf5'))
        if not files:
            raise FileNotFoundError(f'missing snapshot {snap}')
        arrays = []
        expected_total = None
        scale = None
        for path in files:
            with h5py.File(path) as h:
                if int(h['NumberOfFiles'][0]) != len(files):
                    raise ValueError(f'snapshot {snap}: missing shards')
                total = int(h['NumberOfSubhalosInAllFiles'][0])
                if expected_total is not None and total != expected_total:
                    raise ValueError('inconsistent shard counts')
                expected_total = total
                a = float(np.asarray(h['Cosmology/ScaleFactor']).reshape(-1)[0])
                if scale is not None and a != scale:
                    raise ValueError('inconsistent shard times')
                scale = a
                arrays.append(h['Subhalos'].fields(FIELDS)[()])
        records = np.concatenate(arrays)
        ids = set(map(int, records['TrackId']))
        if len(records) != expected_total or len(ids) != len(records) or any(i < 0 for i in ids):
            raise ValueError(f'snapshot {snap}: invalid total or TrackId')
        if not previous_ids <= ids:
            raise ValueError(f'snapshot {snap}: a previously recorded track disappeared')
        for r in np.sort(records, order='TrackId'):
            tid, sink_snap = int(r['TrackId']), int(r['SnapshotIndexOfSink'])
            if not 0 <= r['SnapshotIndexOfBirth'] <= snap:
                raise ValueError('invalid birth time')
            if tid not in previous_ids and r['SnapshotIndexOfBirth'] != snap:
                raise ValueError('new track is missing its birth snapshot')
            if (int(r['SinkTrackId']) < 0) != (sink_snap < 0) or sink_snap > snap:
                raise ValueError('inconsistent sink metadata')
            lookup[snap, tid] = len(nodes)
            nodes.append((len(nodes), snap, scale, tid, int(r['Nbound']), float(r['Mbound']),
                          int(r['HostHaloId']), int(r['SnapshotIndexOfBirth']),
                          int(r['SnapshotIndexOfDeath']), sink_snap, int(r['SinkTrackId']),
                          sink_snap < 0 or sink_snap == snap))
        previous_ids = ids
    nodes = np.array(nodes, dtype=NODE_DTYPE)
    edges = []
    for node in nodes:
        if not node['Active']:
            continue
        snap, tid, source = int(node['Snapshot']), int(node['TrackId']), int(node['NodeId'])
        if node['SinkSnapshot'] == snap:
            target = lookup.get((snap, int(node['SinkTrackId'])))
            if target is None:
                raise ValueError('sink target missing')
            edges.append((source, target, 1))
        elif snap + 1 < count:
            target = lookup.get((snap + 1, tid))
            if target is None:
                raise ValueError('next snapshot missing track')
            edges.append((source, target, 0))
    edges = np.array(edges, dtype=EDGE_DTYPE)
    validate_graph(nodes, edges)
    if not len(nodes):
        raise ValueError('no resolved tracks; cannot accept an empty tree product')
    destination.parent.mkdir(parents=True, exist_ok=True)
    summary = {'snapshots': count, 'nodes': len(nodes), 'continuity_edges': int((edges['Kind'] == 0).sum()),
               'merger_events': int((edges['Kind'] == 1).sum()), 'tracks': len(previous_ids),
               'validation': 'passed', 'source': str(root.resolve()),
               'semantics': 'Kind 0: next-snapshot same-track edge; Kind 1: same-snapshot HBT sink event. Post-sink retained records have Active=0.'}
    with h5py.File(destination, 'x') as h:
        h['Nodes'] = nodes
        h['Edges'] = edges
        h.attrs['schema_version'] = 1
        h.attrs['summary'] = json.dumps(summary)
    destination.with_suffix('.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))
    return nodes, edges


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    parser.add_argument('count', type=int)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    export(args.root, args.count, args.output)
