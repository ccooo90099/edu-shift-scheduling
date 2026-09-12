#!/usr/bin/env python3
"""固定一份求解结果的时段，仅重分配教师，求实际转场次数下界。

python analysis/fixed_slot_transfer_experiment.py \
    --original data/排班对照材料/段次3_原排班.xlsx \
    --solved data/排班对照材料/solved3h.xlsx \
    --config data/排班对照材料/rules.example.yaml

这是机制实验，不改生产求解器。地理始终使用粗判以复现原附件的条件；
只最小化实际转场数，不宣称原加权目标整体更优。输出仅含汇总和输入哈希，
不保存或打印逐人分配。OPTIMAL只针对本次固定时段、候选池和模型成立。
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ortools
from ortools.sat.python import cp_model

from engine.data import load_config, load_schedule
from engine.health import run
from engine.inputs import derive_instructors, derive_rooms, derive_teams
from engine.solver import _GroupModel, weights_from
from engine.travel import Travel


def validate_inputs(original, solved):
    left = original.assign(团队ID=original['团队ID'].astype(str)).set_index('团队ID').sort_index()
    right = solved.assign(团队ID=solved['团队ID'].astype(str)).set_index('团队ID').sort_index()
    if not left.index.is_unique or not right.index.is_unique or not left.index.equals(right.index):
        raise ValueError('两份输入必须为同一批不重复的团队ID')
    for field in ('段次', '周', '区域', '中心', '校区', '程度', '产品', '团队类型'):
        if not left[field].equals(right[field]):
            raise ValueError('固定属性不同：' + field)
    if len(original.groupby(['段次', '周'])) != 1:
        raise ValueError('实验每次只处理一个（段次，周）子问题')
    if original.attrs.get('未排上行数', 0) or solved.attrs.get('未排上行数', 0):
        raise ValueError('输入含未排上团队，不能当成完整对照')


def actual_transfer_objective(model, instructors):
    changes = []
    for name in instructors:
        centers = sorted({c for n, c in model.uses if n == name})
        if len(centers) < 2:
            continue
        index = {c: i + 1 for i, c in enumerate(centers)}
        previous = model.m.NewConstant(0)
        for slot in model.slots:
            current = model.m.NewIntVar(0, len(centers), 'current')
            model.m.Add(current == sum(index[c] * model.at[(name, slot, c)] for c in centers))
            last = model.m.NewIntVar(0, len(centers), 'last')
            busy = model.busy[(name, slot)]
            model.m.Add(last == current).OnlyEnforceIf(busy)
            model.m.Add(last == previous).OnlyEnforceIf(busy.Not())
            had = model.m.NewBoolVar('had')
            different = model.m.NewBoolVar('different')
            changed = model.m.NewBoolVar('changed')
            model.m.Add(previous > 0).OnlyEnforceIf(had)
            model.m.Add(previous == 0).OnlyEnforceIf(had.Not())
            model.m.Add(current != previous).OnlyEnforceIf(different)
            model.m.Add(current == previous).OnlyEnforceIf(different.Not())
            model.m.AddMinEquality(changed, [busy, had, different])
            changes.append(changed)
            previous = last  # 空课保留上次所在中心，A→B→A计2次。
    return sum(changes)


def experiment(args):
    cfg = deepcopy(load_config(args.config))
    cfg['地理']['中心坐标表'] = ''
    cfg['地理']['通行时间表'] = ''
    cfg['地理'].pop('实测通行分钟', None)
    original = load_schedule(args.original, cfg, args.original_sheet)
    solved = load_schedule(args.solved, cfg, args.solved_sheet)
    validate_inputs(original, solved)
    teams = derive_teams(original)
    daily_cap = int(cfg.get('指导员', {}).get('单日最多节数', 4))
    instructors = derive_instructors(original, 可去中心='就近', 单日最多节数=daily_cap)
    rooms = derive_rooms(original)
    fixed = {str(r['团队ID']): (r['首次服务时间'], r['主指导员']) for _, r in solved.iterrows()}
    if not set(solved['首次服务时间']).issubset(cfg['时段']):
        raise ValueError('求解结果包含配置以外的时段')
    travel = Travel(cfg, {}, {}, {t.中心: t.校区 for t in teams}, {t.中心: t.区域 for t in teams})
    model = _GroupModel(teams, list(instructors.values()), rooms, cfg['时段'],
                        cfg, travel, weights_from(cfg), fixed)
    model.build()
    model.add_hint()
    for team in teams:
        model.m.Add(model.unassigned[team.团队ID] == 0)
        model.m.Add(model.team_slot[(team.团队ID, fixed[team.团队ID][0])] == 1)
    model.m.Minimize(actual_transfer_objective(model, instructors))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = args.time_limit
    solver.parameters.num_search_workers = args.workers
    solver.parameters.random_seed = 20260911
    status = solver.Solve(model.m)
    result = {
        'status': solver.StatusName(status), 'seconds': solver.WallTime(),
        'best_bound': solver.BestObjectiveBound(), 'teams': len(teams),
        'candidate_pool': '原表指导员，区域就近', 'geography': '粗判',
        'daily_lesson_cap': daily_cap, 'daily_center_cap': cfg.get('指导员', {}).get('单日最多中心数'),
        'time_limit': args.time_limit, 'workers': args.workers, 'random_seed': 20260911,
        'python': platform.python_version(), 'ortools': ortools.__version__,
        'input_sha256': {k: hashlib.sha256(Path(getattr(args, k)).read_bytes()).hexdigest()
                         for k in ('original', 'solved', 'config')},
    }
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True,
                          cwd=Path(__file__).resolve().parents[1])
    result['code_base_commit'] = head.stdout.strip() if head.returncode == 0 else None
    result['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if status in (cp_model.FEASIBLE, cp_model.OPTIMAL):
        assignments = {tid: name for (tid, slot, name), var in model.x.items() if solver.Value(var)}
        assert len(assignments) == len(solved)
        changed = solved.copy()
        changed['主指导员'] = changed['团队ID'].astype(str).map(assignments)
        old_report = run('', cfg, df=solved)
        new_report = run('', cfg, df=changed)
        assert new_report.老师撞车 == new_report.产品撞车对数 == new_report.教室撞车 == new_report.赶不及次数 == 0
        assert new_report.连堂 == old_report.连堂
        assert new_report.转场次数 == round(solver.ObjectiveValue())
        assert changed.groupby('主指导员').size().max() <= daily_cap
        result.update(
            transfers=new_report.转场次数, original_transfers=old_report.转场次数,
            single_center=new_report.单中心人次, original_single_center=old_report.单中心人次,
            active_teachers=new_report.当日人次, candidate_teachers=len(instructors),
            teacher_changes=int((changed['主指导员'] != solved['主指导员']).sum()),
            H2=new_report.产品撞车对数, adjacency_unchanged=True, independently_checked=True,
        )
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--original', required=True)
    ap.add_argument('--solved', required=True)
    ap.add_argument('--config', required=True)
    ap.add_argument('--original-sheet')
    ap.add_argument('--solved-sheet', default='排班明细')
    ap.add_argument('--time-limit', type=float, default=60)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--out', default='.local/fixed-slot-experiment.json')
    args = ap.parse_args()
    if args.time_limit <= 0 or args.workers <= 0:
        ap.error('time-limit和workers必须大于0')
    result = experiment(args)
    path = Path(args.out)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(result, ensure_ascii=False, indent=2)
    path.write_text(text + '\n', encoding='utf-8')
    print(text)
    return 0 if result.get('independently_checked') else 1


if __name__ == '__main__':
    sys.exit(main())
