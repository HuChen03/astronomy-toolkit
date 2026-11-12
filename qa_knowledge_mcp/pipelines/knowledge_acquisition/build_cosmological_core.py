from __future__ import annotations

import json
import argparse
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SOURCE_ROOT = PROJECT_ROOT / 'data/knowledge_acquisition/processed_papers'
OUTPUT = PROJECT_ROOT / 'data/knowledge_acquisition/cosmological_simulation_core'
QUOTAS = {
    '综述与数值可靠性': 8,
    '旗舰模拟与项目': 20,
    '数据资源与Mock': 8,
    '经典代码与数值方法': 18,
    '快速模拟与模拟器': 16,
    '代表性科学应用': 20,
}

RULES = {
    '综述与数值可靠性': [
        (5, r'modeling cosmic reionization'), (5, r'accuracy of weak lensing simulations'),
        (5, r'on the effects of resolution in dissipationless cosmological simulations'),
        (5, r'two-body relaxation in cosmological simulations'), (5, r'two-body relaxation in cold dark matter simulations'),
        (4, r'model for cosmological simulations of galaxy formation physics'),
        (3, r'comparison.*cosmological'), (2, r'precision cosmology'),
    ],
    '旗舰模拟与项目': [
        (6, r'introducing the illustris project'), (6, r'\bsimba:'), (6, r'introducing the thesan project'),
        (6, r'abacussummit:'), (6, r'resolving cosmic structure formation with the millennium-ii'),
        (6, r'the multidark database'), (6, r'dark matter halos.*bolshoi simulation'),
        (6, r'millenniumtng project.*high-precision'), (6, r'flamingo: calibrating'),
        (5, r'bahamas project'), (5, r'bacco simulation project'), (5, r'auriga project'),
        (5, r'sphinx cosmological simulations'), (5, r'aurora radiation-hydrodynamical'),
        (5, r'the codecs project'), (5, r'aemulus project'), (5, r'coyote universe'),
        (5, r'three hundred project'), (4, r'horizon-agn'), (4, r'massiveblack-ii'),
        (4, r'renaissance simulations'), (4, r'thesan-hr'), (4, r'flamingo project'),
        (4, r'millennium-xxl'), (4, r'multidark'),
    ],
    '数据资源与Mock': [
        (7, r'public data release.*cosmological simulations'), (7, r'thesan project: public data release'),
        (7, r'illustris simulation: public data release'), (7, r'multidark-galaxies: data release'),
        (6, r'lightcone catalogue from the millennium-xxl'), (6, r'synthetic light-cone catalogues.*abacussummit'),
        (6, r'1000 multi-tracer mock catalogues'), (6, r'mock galaxy catalogues for the boss final data release'),
        (5, r'terapixel imaging of cosmological simulations'), (5, r'multidark database'),
        (4, r'virtual observatory'), (4, r'mock galaxy surveys'),
    ],
    '经典代码与数值方法': [
        (7, r'transients from initial conditions'), (7, r'multi-scale initial conditions'),
        (7, r'cosmological n-body simulations with suppressed variance'),
        (7, r'cosmological hydrodynamics with adaptive mesh refinement'), (7, r'ramses-rt:'),
        (7, r'21cmfast:'), (7, r'ice-cola:'), (7, r'ray-ramses:'),
        (6, r'emma: an adaptive mesh refinement'), (6, r'implementation of radiative transfer.*gadget'),
        (6, r'moving mesh cosmology: numerical techniques'), (6, r'moving mesh cosmology: the hydrodynamics'),
        (6, r'initial conditions for cosmological n-body simulations'),
        (5, r'fast particle-mesh simulation'), (5, r'phase-space element method'),
        (5, r'corner modes in the initial conditions'), (5, r'non-gaussian initial conditions'),
        (5, r'shock finding on a moving mesh'), (5, r'cube2:'),
        (4, r'halo finders'), (4, r'symfind:'), (4, r'ramses-ch:'),
    ],
    '快速模拟与模拟器': [
        (7, r'coyote universe.*emulation'), (7, r'aemulus project.*emulating'),
        (7, r'high-accuracy emulators for observables'), (7, r'mira.titan universe.*emulation'),
        (7, r'bacco simulation project: a baryonification emulator'), (7, r'enabling matter power spectrum emulation.*cola'),
        (7, r'emulating simulations of cosmic dawn'), (7, r'cosmic emulation: fast predictions'),
        (6, r'pkann'), (6, r'cosmicnet'), (6, r'super-resolution emulator'),
        (6, r'be-happy:'), (6, r'fast and accurate predictions of the non-linear matter power spectrum'),
        (6, r'emulator for the lyman'), (6, r'emulating the lyman-alpha forest'),
        (5, r'intelligent design: on the emulation'), (5, r'mglens:'),
        (5, r'ten-parameter simulation suite for cosmological emulation'),
        (4, r'emulator-based halo model'), (4, r'gaussian processes and neural networks.*cosmological'),
    ],
    '代表性科学应用': [
        (6, r'halo mass function from the dark ages'), (6, r'revising the halofit model'),
        (6, r'testing cosmological structure formation using redshift-space distortions'),
        (6, r'ray-tracing through the millennium simulation'),
        (6, r'impact of baryons on the matter power spectrum.*horizon-agn'),
        (6, r'intrinsic alignments of galaxies in the horizon-agn'),
        (6, r'intrinsic alignments in illustristng'), (6, r'cosmology with massive neutrinos iii'),
        (6, r'effects of baryons on the halo mass function'), (6, r'simulations and analytic calculations of bubble growth'),
        (5, r's8 tension'), (5, r'matter power spectrum'), (5, r'halo mass function'),
        (5, r'weak lensing'), (5, r'redshift-space distortions'), (5, r'reionization'),
        (5, r'21-cm'), (5, r'21 cm'), (5, r'lyman-alpha forest'), (5, r'intrinsic alignment'),
        (4, r'massive neutrinos'), (4, r'halo statistics'),
    ],
}

EXCLUDE = re.compile(
    r'climate|volcanic|last millennium|correction to|language guide|pulsar|planetary|xenon|tianqin|fossil group|'
    r'sdss data release|desi legacy imaging|galmer|review essay|photometric-redshift space|supernova survey|'
    r'megaz-lrg|dark energy survey year 1 results: constraints on intrinsic alignments', re.I
)


def title_of(path: Path) -> str:
    head = path.read_text(encoding='utf-8', errors='ignore')[:16000]
    headings = re.findall(r'^#\s+(.+)$', head, re.MULTILINE)
    return headings[0].strip() if headings else ''


def normalize(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', ' ', value.lower()).strip()


def category_scores(title: str) -> dict[str, int]:
    low = title.lower()
    return {category: sum(weight for weight, pattern in rules if re.search(pattern, low)) for category, rules in RULES.items()}


def family(title: str) -> str:
    low = title.lower()
    for name in ['thesan', 'flamingo', 'illustris', 'millennium', 'multidark', 'bolshoi', 'horizon-agn', 'aemulus', 'coyote', 'bacco', 'auriga', 'sphinx', 'ramses']:
        if name in low:
            return name
    return normalize(title)[:45]


def main() -> None:
    parser = argparse.ArgumentParser(description='Build the curated cosmological simulation paper manifest.')
    parser.add_argument('--source-root', type=Path, default=os.environ.get('QA_PROCESSED_PAPERS_ROOT') or SOURCE_ROOT)
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    source_root = args.source_root if args.source_root.is_absolute() else PROJECT_ROOT / args.source_root
    output = args.output if args.output.is_absolute() else PROJECT_ROOT / args.output
    if not source_root.is_dir():
        parser.error('provide a processed-paper directory with --source-root or QA_PROCESSED_PAPERS_ROOT')
    candidates = []
    seen_titles = set()
    for path in sorted(source_root.rglob('*.md')):
        if path.parent.name.endswith('_pdf'):
            continue
        title = title_of(path)
        norm = normalize(title)
        if not title or norm in seen_titles or EXCLUDE.search(title):
            continue
        scores = category_scores(title)
        if max(scores.values()) <= 0:
            continue
        seen_titles.add(norm)
        candidates.append({
            'key': path.parent.name if path.parent != source_root else path.stem,
            'title': title,
            'source': str(path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path),
            'chars': path.stat().st_size,
            'scores': scores,
            'family': family(title),
        })

    selected = []
    selected_keys = set()
    family_counts = defaultdict(int)
    for category, quota in QUOTAS.items():
        ranked = sorted(
            candidates,
            key=lambda item: (
                -item['scores'][category],
                -max(item['scores'].values()),
                family_counts[item['family']],
                -item['chars'],
                item['title'],
            ),
        )
        count = 0
        for item in ranked:
            if count >= quota:
                break
            if item['key'] in selected_keys or item['scores'][category] <= 0:
                continue
            cap = 3 if category in {'旗舰模拟与项目', '代表性科学应用'} else 2
            if family_counts[item['family']] >= cap and item['family'] in {'thesan', 'flamingo', 'illustris', 'millennium', 'multidark', 'horizon-agn'}:
                continue
            record = {k: item[k] for k in ('key', 'title', 'source', 'chars')}
            record['category'] = category
            record['score'] = item['scores'][category]
            record['reason'] = f"按“{category}”规则入选；标题匹配得分 {record['score']}，全文 {record['chars']} 字节。"
            selected.append(record)
            selected_keys.add(item['key'])
            family_counts[item['family']] += 1
            count += 1

    selected.sort(key=lambda item: (list(QUOTAS).index(item['category']), -item['score'], item['title']))
    for rank, item in enumerate(selected, 1):
        item['rank'] = rank

    output.mkdir(parents=True, exist_ok=True)
    (output / 'core_papers.json').write_text(json.dumps(selected, ensure_ascii=False, indent=2), encoding='utf-8')
    lines = ['# 宇宙学数值模拟核心文献清单', '', f'- 总数：{len(selected)}', '']
    current = None
    for item in selected:
        if item['category'] != current:
            current = item['category']
            lines.extend([f'## {current}', ''])
        lines.append(f"- {item['rank']}. **{item['title']}**  `{item['key']}`")
    (output / 'core_papers.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print('selected', len(selected))
    print(Counter(item['category'] for item in selected))
    for item in selected:
        print(f"{item['rank']:03d}\t{item['category']}\t{item['key']}\t{item['title']}")


if __name__ == '__main__':
    main()
