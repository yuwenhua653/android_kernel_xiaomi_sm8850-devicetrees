#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-only
"""Compare OS4.0.7 Canoe audio/haptic wiring in final merged DTBs.

Usage: verify-nezha-audio.py STOCK_DTBO_ENTRY_1 FINAL_DTB [FINAL_DTB ...]
Checks properties and resolved references, not driver binding or sound output.
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


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stock',type=Path);p.add_argument('final',nargs='+',type=Path)
    args=p.parse_args()
    helper=runpy.run_path(str(Path(__file__).with_name('prepare-nezha-display.py')))
    stock=helper['BoardOverlay'](args.stock.read_bytes())
    for path in args.final:
        count=check(stock,helper['read_nodes'](path.read_bytes()))
        print(f'PASS: {path.name}: {count} audio/haptic properties and references')


if __name__=='__main__':main()
