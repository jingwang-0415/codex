#!/usr/bin/env python3
"""Collect immutable Git evidence; deliberately make no completeness verdict."""
import argparse
import json
from pathlib import Path
import subprocess
import sys


def git(repo, *args, allowed=(0,)):
    result = subprocess.run(
        ['git', '-C', str(repo), *args], stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, check=False,
    )
    if result.returncode not in allowed:
        raise RuntimeError(result.stderr.decode('utf-8', 'replace').strip()
                           or f'git {args[0]} failed ({result.returncode})')
    return result.stdout


def decode(raw):
    return raw.decode('utf-8', 'surrogateescape')


def changes(raw):
    fields = decode(raw).split('\0')
    result = []
    i = 0
    while i < len(fields) and fields[i]:
        status = fields[i]
        count = 2 if status.startswith(('R', 'C')) else 1
        result.append({'status': status, 'paths': fields[i + 1:i + count + 1]})
        i += count + 1
    return result


def collect(repo, old_ref, new_ref, out):
    repo = Path(decode(git(repo, 'rev-parse', '--show-toplevel')).strip()).resolve()
    out = Path(out).resolve()
    if out == repo or repo in out.parents:
        raise ValueError('--out must be outside the inspected checkout')
    old = decode(git(repo, 'rev-parse', '--verify', '--end-of-options', old_ref + '^{commit}')).strip()
    new = decode(git(repo, 'rev-parse', '--verify', '--end-of-options', new_ref + '^{commit}')).strip()
    bases = decode(git(repo, 'merge-base', '--all', old, new, allowed=(0, 1))).splitlines()
    unique = []
    for sha in decode(git(repo, 'rev-list', '--reverse', f'{new}..{old}')).splitlines():
        parts = decode(git(repo, 'show', '-s', '--format=%H%x00%P%x00%s', sha)).rstrip('\n').split('\0', 2)
        unique.append({'sha': parts[0], 'parents': parts[1].split(), 'subject': parts[2]})
    diff_args = ('diff', '--no-ext-diff', '--no-textconv', '--find-renames')
    raw_changes = git(repo, *diff_args, '--name-status', '-z', old, new, '--')
    summary = {
        'repository': str(repo), 'old_ref': old_ref, 'old_sha': old,
        'new_ref': new_ref, 'new_sha': new, 'merge_bases': bases,
        'shallow': decode(git(repo, 'rev-parse', '--is-shallow-repository')).strip() == 'true',
        'dirty_worktree': bool(git(repo, 'status', '--porcelain=v1', '-z')),
        'old_is_ancestor': not bool(decode(git(repo, 'rev-list', '-1', f'{new}..{old}')).strip()),
        'old_only_commits': unique,
        'tip_changes': changes(raw_changes),
        'assessment': 'review_required',
        'notes': ['Local refs only; no fetch performed.',
                  'Patch equivalence and ancestry do not prove behavior preservation.',
                  'Review merges, tip differences, submodule/LFS contents and behavior manually.'],
    }
    out.mkdir(parents=True, exist_ok=False)
    # Only write summary after every evidence command succeeds; a failed run is incomplete.
    (out / 'cherry.txt').write_bytes(git(repo, 'cherry', '-v', new, old))
    (out / 'old-to-new.patch').write_bytes(git(repo, *diff_args, '--binary', old, new, '--'))
    (out / 'old-to-new.name-status.z').write_bytes(raw_changes)
    for index, base in enumerate(bases):
        for label, tip in [('old', old), ('new', new)]:
            (out / f'base-{index}-to-{label}.patch').write_bytes(
                git(repo, *diff_args, '--binary', base, tip, '--'))
    for label, tip in [('old', old), ('new', new)]:
        (out / f'{label}-tree.z').write_bytes(git(repo, 'ls-tree', '-r', '-z', tip))
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=True, indent=2) + '\n')
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--old', required=True)
    parser.add_argument('--new', required=True)
    parser.add_argument('--out', required=True, help='New evidence directory outside checkout')
    args = parser.parse_args()
    try:
        summary = collect(args.repo, args.old, args.new, args.out)
    except (OSError, RuntimeError, ValueError) as exc:
        print(f'Collection failed: {exc}', file=sys.stderr)
        return 1
    print(json.dumps({'evidence': str(Path(args.out).resolve()),
                      'old_only_commits': len(summary['old_only_commits']),
                      'changed_paths': len(summary['tip_changes']),
                      'assessment': summary['assessment']}))
    return 0


if __name__ == '__main__':
    sys.exit(main())
