#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare OS4.0.7 Nezha audio/haptic wiring in final merged DTBs.

Usage: verify-nezha-audio.py STOCK_DTBO_ENTRY_1 FINAL_DTB [FINAL_DTB ...]
Use --sg-merged with a matched factory base plus its stock SG/Whale overlay.
"""
import argparse
from collections import defaultdict
from pathlib import Path
import runpy


def check(stock, final):
    if any(p.startswith('/fragment@') for p in final):
        raise ValueError('expected final merged DTB')
    labels={k:v.rstrip(b'\0').decode() for k,v in final['/__symbols__'].items()}
    origins={}
    for number in list(range(220,260,2))+[261,274]:
        fragment=f'/fragment@{number}'; prefix=fragment+'/__overlay__'
        target=stock.refs[fragment,'target',0]
        for p in stock.nodes:
            if p==prefix or p.startswith(prefix+'/'):
                origins[p]=(target,p[len(prefix):])
    for label in ('pmih010x_haptics','pmk8850_sdam_46'):
        prefix=next(p for p,l in stock.labels.items() if l==label)
        for p in stock.nodes:
            if p==prefix or p.startswith(prefix+'/'):
                origins[p]=(label,p[len(prefix):])
    references=defaultdict(list)
    for (p,prop,offset),label in stock.refs.items():
        references[p,prop].append((offset,label))
    expected={}
    for p,(label,suffix) in origins.items():
        path=labels[label]+suffix
        for prop,value in stock.nodes[p].items():
            if prop=='phandle':continue
            value=bytearray(value)
            for offset,ref in references[p,prop]:
                value[offset:offset+4]=final[labels[ref]]['phandle']
            expected[path,prop]=bytes(value)
    for (path,prop),value in expected.items():
        if final.get(path,{}).get(prop)!=value:
            raise ValueError(f'mismatch: {path}:{prop}')
    return len(expected)


def sg_properties(nodes):
    handles = {v['phandle']: path for path, v in nodes.items() if 'phandle' in v}
    haptic, = [p for p in nodes if p.endswith('/qcom,hv-haptics@f000')]
    sound = '/soc/spf_core_platform/sound'
    if sound not in nodes:
        raise ValueError('missing sound card')
    result = {}
    for p, props in nodes.items():
        if not any(p == n or p.startswith(n + '/') for n in (haptic, sound)):
            continue
        for k, value in props.items():
            if k in ('phandle', 'linux,phandle'):
                continue
            if k in ('clocks', 'nvmem'):
                value = (handles[value[:4]], value[4:])
            result[p, k] = value
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sg-merged', action='store_true', help='compare against a matching merged factory SG/Whale DTB')
    p.add_argument('stock',type=Path);p.add_argument('final',nargs='+',type=Path)
    args=p.parse_args()
    helper=runpy.run_path(str(Path(__file__).with_name('prepare-nezha-display.py')))
    if args.sg_merged:
        ref = helper['read_nodes'](args.stock.read_bytes())
        expected = sg_properties(ref)
        for path in args.final:
            tree = helper['read_nodes'](path.read_bytes())
            if ref['/']['qcom,msm-id'] != tree['/']['qcom,msm-id']:
                raise ValueError(f'{path}: factory SoC ID mismatch')
            actual = sg_properties(tree)
            for key in actual.keys() | expected.keys():
                if expected.get(key) != actual.get(key):
                    raise ValueError(f'{path}: SG audio/haptic mismatch at {key}')
            print(f'PASS {path.name}: {len(actual)} SG audio/haptic properties and references')
        return
    stock=helper['BoardOverlay'](args.stock.read_bytes())
    for path in args.final:
        count=check(stock,helper['read_nodes'](path.read_bytes()))
        print(f'PASS: {path.name}: {count} audio/haptic properties and references')


if __name__=='__main__':main()
