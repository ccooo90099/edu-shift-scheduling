#!/usr/bin/env python3
"""H2硬约束与两个固定系数软代理的单因素诊断，不修改生产模型。

用相同原排班、既有求解结果（hint）及规则运行三组30秒单线程实验。
默认只输出去标识汇总JSON。所用代理是按产品出现标记计算的并发项，
不代表真实报读组合或受影响学生数；各组目标定义不同，总目标不可直接比较。
保留旧H3，包括空教室字段可能导致0间并跳过容量约束的缺陷。

python analysis/h2_soft_proxy_experiment.py --original 原排班.xlsx \
    --solved solved3h.xlsx --config rules.example.yaml

运行时应使用协作消息中SHA-256匹配的106团队输入；该实验不能证明普遍收敛速度，
也不能证明物理教室可行或新业务S8已实现。未知物理数据明确保留，不能当成0问题。
"""
import sys,json,hashlib,platform,time,argparse,subprocess
from pathlib import Path
from copy import deepcopy
from collections import defaultdict,Counter
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import ortools
from ortools.sat.python import cp_model
from engine.data import load_config,load_schedule,TIME_COL
from engine.inputs import derive_teams,derive_instructors,derive_rooms
from engine.solver import _GroupModel,weights_from
from engine.travel import Travel
from engine.health import run
from engine.slots import parse_slot

class SoftH2(_GroupModel):
    penalty=100
    def _one_product_per_slot(self):
        groups=defaultdict(lambda:defaultdict(list))
        for t in self.teams:groups[t.冲突组][t.产品].append(t)
        self.used={};pairs=[]
        for cg,products in groups.items():
            if len(products)<2:continue
            for s in self.slots:
                for p,members in products.items():
                    u=self.m.NewBoolVar('product_used')
                    self.m.AddMaxEquality(u,[self.team_slot[t.团队ID,s] for t in members])
                    self.used[cg,s,p]=u
                ps=sorted(products)
                for i,p in enumerate(ps):
                    for q in ps[i+1:]:
                        both=self.m.NewBoolVar('proxy_same_slot')
                        self.m.AddMinEquality(both,[self.used[cg,s,p],self.used[cg,s,q]])
                        pairs.append(both)
            for a,b in self._overlapping_pairs():
                for p in products:
                    for q in products:
                        if p==q:continue
                        both=self.m.NewBoolVar('proxy_overlap_slot')
                        self.m.AddMinEquality(both,[self.used[cg,a,p],self.used[cg,b,q]])
                        pairs.append(both)
        self.proxy=sum(pairs)
        self.terms.append(('H2_proxy',self.proxy,self.penalty))

class Observe(cp_model.CpSolverSolutionCallback):
    def __init__(self):super().__init__();self.first=None;self.solutions=0
    def on_solution_callback(self):
        if self.first is None:self.first=self.WallTime()
        self.solutions+=1

def main():
    ap=argparse.ArgumentParser(description='诊断H2约束的影响；并发代理不是真实S8，保留旧H3缺陷，不验证物理教室可行性。')
    ap.add_argument('--original', required=True)
    ap.add_argument('--solved', required=True)
    ap.add_argument('--config', required=True)
    ap.add_argument('--out', default='.local/h2-soft-proxy-results.json')
    ap.add_argument('--time-limit', type=float, default=30)
    ap.add_argument('--seed', type=int, default=20260912)
    ap.add_argument('--incumbent-bound', action='store_true', help='先验证已有解，三组都加同一可行目标上界')
    args=ap.parse_args()
    if args.time_limit<=0:ap.error('time-limit must be positive')
    # 此脚本的研究问题要求固定旧H3；修复容量后不得仍输出“旧模型”诊断。
    baseline='bb7aafddb47139098597cff6c960aec1b1800eeb'
    check=subprocess.run(['git','diff','--quiet',baseline,'--','engine'],
                         cwd=Path(__file__).resolve().parents[1],capture_output=True)
    if check.returncode:
        ap.error('此历史诊断要求engine与bb7aafd一致；请在对应历史工作区运行，不要混用已修复的模型')
    paths={k:Path(getattr(args,k)) for k in ('original','solved','config')}
    cfg=load_config(paths['config']); cfg['地理']['中心坐标表']='';cfg['地理']['通行时间表']=''
    df=load_schedule(paths['original'],cfg)
    hintdf=load_schedule(paths['solved'],cfg,'排班明细')
    teams=derive_teams(df);instructors=derive_instructors(df);rooms=derive_rooms(df)
    hint={str(r['团队ID']):(r[TIME_COL],r['主指导员']) for _,r in hintdf.iterrows()}
    assert len(teams)==len(hint)==106, '该控制实验固定段次3的106团队；不要换人群后混用结论'
    assert len(df.groupby(['段次','周']))==1
    assert set(df['团队ID'].astype(str))==set(hintdf['团队ID'].astype(str))
    travel=Travel(cfg,{}, {},{t.中心:t.校区 for t in teams},{t.中心:t.区域 for t in teams})
    incumbent_bound=None
    if args.incumbent_bound:
        ref=_GroupModel(teams,list(instructors.values()),rooms,cfg['时段'],cfg,travel,weights_from(cfg))
        ref.build()
        for t in teams:
            s,n=hint[t.团队ID]
            ref.m.Add(ref.x[(t.团队ID,s,n)]==1)
        ref_solver=cp_model.CpSolver();ref_solver.parameters.max_time_in_seconds=10;ref_solver.parameters.num_search_workers=1
        assert ref_solver.Solve(ref.m)==cp_model.OPTIMAL, '固定起点未验证，不得据此添加上界'
        assert run('',cfg,df=hintdf).产品撞车对数==0
        incumbent_bound=round(ref_solver.ObjectiveValue())
    report={'engine_baseline':'bb7aafddb47139098597cff6c960aec1b1800eeb','scope':'旧六时段、旧H3、全部106团队必须排上；H2软项为产品并发代理，不是真实报读人数；其余生产目标不变',
            'sha256':{k:hashlib.sha256(p.read_bytes()).hexdigest() for k,p in paths.items()},
            'python':platform.python_version(),'ortools':ortools.__version__,'time_limit':args.time_limit,'workers':1,'seed':args.seed,
            'incumbent_bound':incumbent_bound,
            'room_counts':{'centers':len(rooms),'zero_count_unconstrained_centers':sum(not x for x in rooms.values())},'cases':[]}
    out=Path(args.out)
    out.parent.mkdir(parents=True,exist_ok=True)
    for mode,penalty in [('hard',None),('soft_proxy_100',100),('soft_proxy_1000',1000)]:
        cls=_GroupModel if penalty is None else SoftH2
        if penalty is not None:SoftH2.penalty=penalty
        build_started=time.monotonic()
        model=cls(teams,list(instructors.values()),rooms,cfg['时段'],cfg,travel,weights_from(cfg),hint)
        model.build();model.add_hint()
        for t in teams:model.m.Add(model.unassigned[t.团队ID]==0)
        if incumbent_bound is not None:
            model.m.Add(sum(expr*w for _,expr,w in model.terms)<=incumbent_bound)
        solver=cp_model.CpSolver();solver.parameters.max_time_in_seconds=args.time_limit;solver.parameters.num_search_workers=1;solver.parameters.random_seed=args.seed
        build_seconds=time.monotonic()-build_started
        observe=Observe();status=solver.Solve(model.m,observe)
        r={'mode':mode,'proxy_penalty':penalty,'status':solver.StatusName(status),'build_seconds':build_seconds,'solve_seconds':solver.WallTime(),'first_solution_seconds':observe.first,'solution_count':observe.solutions,'bound':solver.BestObjectiveBound()}
        if status in (cp_model.OPTIMAL,cp_model.FEASIBLE):
            assignments={tid:(s,n) for (tid,s,n),v in model.x.items() if solver.Value(v)}
            assert len(assignments)==106
            changed=df.copy();ids=changed['团队ID'].astype(str)
            changed[TIME_COL]=ids.map(lambda x:assignments[x][0]);changed['主指导员']=ids.map(lambda x:assignments[x][1])
            changed['_start']=changed[TIME_COL].map(lambda x:parse_slot(x)[0]);changed['_end']=changed[TIME_COL].map(lambda x:parse_slot(x)[1])
            source_rooms_report=run('',cfg,df=changed)
            r['copied_source_room_clashes']=source_rooms_report.教室撞车
            # 与生产output.write_detail一致：旧模型没有重新分配教室，不能沿用源表旧教室号。
            changed['指导室']=''
            checked=run('',cfg,df=changed)
            r['checks']={'teacher':checked.老师撞车,'travel':checked.赶不及次数,'explicit_room_assignment':False}
            counts=changed.groupby(['中心',TIME_COL]).size()
            # 旧生产代码if not limit: continue；零值意味着旧H3未约束，不能伪称有容量验证。
            assert all(n<=rooms[center] for (center,slot),n in counts.items() if rooms[center])
            assert checked.老师撞车==checked.赶不及次数==0,r['checks']
            if penalty is None:assert checked.产品撞车对数==0
            parts={}
            for label,expr,w in model.terms:parts[label]=parts.get(label,0)+solver.Value(expr)*w
            r.update(objective=solver.ObjectiveValue(),common_objective=solver.ObjectiveValue()-parts.get('H2_proxy',0),parts=parts,
                     teams=106,transfers=checked.转场次数,single_center=checked.单中心人次,active_teachers=checked.当日人次,
                     legacy_H2_team_pairs=checked.产品撞车对数,H2_proxy_product_pairs=solver.Value(model.proxy) if penalty is not None else 0,
                     legacy_adjacency=checked.连堂,checked_legacy_constraints=True,room_identity_verified=False)
        report['cases'].append(r)
        out.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(r,ensure_ascii=False),flush=True)


if __name__ == "__main__":
    main()
