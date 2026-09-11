"""排班的三份输入：待排团队、人员池、场地。

都可以从一份现有排班明细里推出来（`derive_*`），这是最省事的起步方式：
把明细表的「首次服务时间」和「主指导员」当成待定，其余照搬。
"""
from dataclasses import dataclass, field

from .data import TIME_COL


@dataclass
class Team:
    """一个待排的团队。时段和主指导员是待定的，其余是给定条件。"""
    团队ID: str
    段次: str
    周: str
    区域: str
    中心: str
    校区: str
    程度: str
    产品: str
    团队类型: str
    团队名称: str = ""
    是否促销: str = ""
    原时段: str = ""          # 修复模式下用来算"改动了多少"
    原主指导员: str = ""

    @property
    def 学生群(self):
        """同一撮学生 —— 连堂规则按这个粒度判断。"""
        return (self.校区, self.程度, self.团队类型)

    @property
    def 冲突组(self):
        """同校区同年级 —— 同一时段里只能有一个产品。"""
        return (self.校区, self.程度)


@dataclass
class Instructor:
    姓名: str
    可教产品: set = field(default_factory=set)
    可去中心: set = field(default_factory=set)     # 空 = 不限
    不可用时段: set = field(default_factory=set)
    单日最多节数: int = 4

    def 能教(self, team):
        if team.产品 not in self.可教产品:
            return False
        return not self.可去中心 or team.中心 in self.可去中心


def derive_teams(df):
    """把一份排班明细当成待排清单（时段和主指导员作废，留作对照）。"""
    teams = []
    for _, row in df.iterrows():
        teams.append(Team(
            团队ID=str(row["团队ID"]), 段次=row["段次"], 周=row["周"],
            区域=row.get("区域", ""), 中心=row["中心"], 校区=row["校区"], 程度=row["程度"],
            产品=row["产品"], 团队类型=row["团队类型"],
            团队名称=row.get("团队名称", ""), 是否促销=row.get("是否促销", ""),
            原时段=row[TIME_COL], 原主指导员=row["主指导员"]))
    return teams


def derive_instructors(df, 可去中心="就近", 单日最多节数=4):
    """从现有排班推人员池。

    可去中心决定每个团队有多少候选老师 —— 这个数既影响排班质量，也直接决定
    求解器能不能算完。实测（段次3，106 团队）：

        不限   全市所有合格老师，每团队中位数 31 个候选。
               140 秒收敛不了，只能返回"还行"的解，调权重也没用。
        历史   只去他在这份数据里去过的中心。2.3 秒跑到最优，但 15 个团队排不下。
        就近   他去过的中心，加上那些中心所在区域里的其他中心（默认）。
               比"历史"松，比"不限"紧，贴合"老师有固定活动片区"的现实。
    """
    if 可去中心 == "就近" and "区域" in df.columns:
        区域内中心 = df.groupby("区域")["中心"].apply(set).to_dict()
    else:
        区域内中心 = {}

    out = {}
    for name, sub in df.groupby("主指导员"):
        去过 = set(sub["中心"].unique())
        if 可去中心 == "历史":
            范围 = 去过
        elif 可去中心 == "就近":
            范围 = set(去过)
            for 区域 in sub["区域"].unique() if "区域" in sub else ():
                范围 |= 区域内中心.get(区域, set())
        else:
            范围 = set()                    # 空 = 不限
        out[name] = Instructor(
            姓名=name, 可教产品=set(sub["产品"].unique()),
            可去中心=范围, 单日最多节数=单日最多节数)
    return out


def derive_rooms(df):
    """每个中心有几间教室。

    有指导室字段的按实际间数；没有的按该中心历史上的最大并发团队数兜底——
    宁可保守一点，也不要排出一个塞不下的班。
    """
    rooms = {}
    named = df[df.get("指导室", "").astype(str).str.strip() != ""] if "指导室" in df else df.iloc[0:0]
    for center, sub in named.groupby("中心"):
        rooms[center] = sub["指导室"].nunique()

    concurrent = df.groupby(["中心", "段次", "周", TIME_COL]).size().groupby("中心").max()
    for center, peak in concurrent.items():
        rooms.setdefault(center, int(peak))
    return rooms


def qualified_for(team, instructors):
    return [i for i in instructors.values() if i.能教(team)]
