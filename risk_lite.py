#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""risk-lite: 简化版 Risk（大战略）桌游。

规则简化：
- 12 块领地（3x4 地图），2 名玩家，无卡片/任务牌。
- 每轮：增援 -> 进攻 -> 调动。
- 增援数 = max(3, 领地数 // 3)。
- 进攻：相邻敌方领地，攻击方掷 min(3, 兵力-1) 骰，防守方掷 min(2, 兵力) 骰；
  点数从大到小配对比较，平局算防守方胜，每对输家减 1 兵。
- 占领全部领地者获胜；500 回合未分胜负则领地多者胜（相同判和）。

纯标准库：argparse / copy / random / sys。
"""

import argparse
import copy
import random
import sys

# 3x4 地图：索引 = 行*4 + 列
NAMES = ["北原", "雪原", "冰原", "冻原",
         "草原", "平原", "丘陵", "高原",
         "沙漠", "戈壁", "绿洲", "海岸"]

ADJ = {}
for r in range(3):
    for c in range(4):
        i = r * 4 + c
        nb = []
        if r > 0:
            nb.append((r - 1) * 4 + c)
        if r < 2:
            nb.append((r + 1) * 4 + c)
        if c > 0:
            nb.append(r * 4 + c - 1)
        if c < 3:
            nb.append(r * 4 + c + 1)
        ADJ[i] = nb

N_TERR = 12
MAX_TURNS = 500  # 防无限对局上限


class IllegalMove(Exception):
    """非法走法。"""


def roll_dice(rng, n):
    return sorted((rng.randint(1, 6) for _ in range(n)), reverse=True)


def resolve_combat(att_troops, def_troops, att_dice=None, def_dice=None):
    """按 Risk 骰子规则结算一次交战。

    att_dice/def_dice 为可选的固定骰面（供测试用）；None 时按规则数量随机掷。
    返回 (攻击方损失, 防守方损失)。
    """
    an = min(3, att_troops - 1)
    dn = min(2, def_troops)
    if an < 1 or dn < 1:
        raise IllegalMove("兵力不足以交战")
    ad = sorted(att_dice, reverse=True)[:an] if att_dice else None
    dd = sorted(def_dice, reverse=True)[:dn] if def_dice else None
    # 测试传入固定骰面时也做数量校验
    if att_dice is not None and len(att_dice) != an:
        raise IllegalMove("攻击骰数不符")
    if def_dice is not None and len(def_dice) != dn:
        raise IllegalMove("防守骰数不符")
    att_lost = def_lost = 0
    for a, d in zip(ad, dd):
        if a > d:
            def_lost += 1
        else:  # 平局算防守方胜
            att_lost += 1
    return att_lost, def_lost


class Risk:
    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.owner = [0] * N_TERR
        self.troops = [0] * N_TERR
        self.turn = 0
        self._setup()

    def _setup(self):
        order = list(range(N_TERR))
        self.rng.shuffle(order)
        for k, t in enumerate(order):
            self.owner[t] = k % 2
            self.troops[t] = 2

    # ---------- 规则 ----------
    def territories(self, player):
        return [t for t in range(N_TERR) if self.owner[t] == player]

    def reinforcement_count(self, player):
        return max(3, len(self.territories(player)) // 3)

    def place(self, player, terr, n):
        if not (0 <= terr < N_TERR):
            raise IllegalMove("领地编号越界")
        if self.owner[terr] != player:
            raise IllegalMove("只能在自己的领地增援")
        if n < 1:
            raise IllegalMove("增援数至少为 1")
        self.troops[terr] += n

    def legal_attacks(self, player):
        out = []
        for f in self.territories(player):
            if self.troops[f] < 2:
                continue
            for t in ADJ[f]:
                if self.owner[t] != player:
                    out.append((f, t))
        return out

    def attack(self, player, frm, to, att_dice=None, def_dice=None, rng=None):
        if not (0 <= frm < N_TERR and 0 <= to < N_TERR):
            raise IllegalMove("领地编号越界")
        if self.owner[frm] != player:
            raise IllegalMove("只能从自己的领地进攻")
        if self.owner[to] == player:
            raise IllegalMove("不能进攻自己的领地")
        if to not in ADJ[frm]:
            raise IllegalMove("只能进攻相邻领地")
        if self.troops[frm] < 2:
            raise IllegalMove("进攻方至少需要 2 兵")
        r = rng or self.rng
        an = min(3, self.troops[frm] - 1)
        dn = min(2, self.troops[to])
        ad = sorted(att_dice, reverse=True)[:an] if att_dice is not None \
            else roll_dice(r, an)
        dd = sorted(def_dice, reverse=True)[:dn] if def_dice is not None \
            else roll_dice(r, dn)
        att_lost, def_lost = resolve_combat(self.troops[frm], self.troops[to], ad, dd)
        self.troops[frm] -= att_lost
        self.troops[to] -= def_lost
        conquered = False
        if self.troops[to] <= 0:
            # 占领：至少移入进攻所用骰数，至多留 1 兵守家
            move = min(an, self.troops[frm] - 1)
            self.owner[to] = player
            self.troops[to] = move
            self.troops[frm] -= move
            conquered = True
        return {"att_dice": ad, "def_dice": dd, "att_lost": att_lost,
                "def_lost": def_lost, "conquered": conquered}

    def fortify(self, player, frm, to, n):
        if not (0 <= frm < N_TERR and 0 <= to < N_TERR):
            raise IllegalMove("领地编号越界")
        if self.owner[frm] != player or self.owner[to] != player:
            raise IllegalMove("调动只能在自己的领地之间")
        if to not in ADJ[frm]:
            raise IllegalMove("只能调动到相邻领地")
        if n < 1 or n > self.troops[frm] - 1:
            raise IllegalMove("调动数非法（至少留 1 兵）")
        self.troops[frm] -= n
        self.troops[to] += n

    def winner(self):
        for p in (0, 1):
            if all(o == p for o in self.owner):
                return p
        return None

    def total_troops(self, player):
        return sum(self.troops[t] for t in self.territories(player))


# ---------- AI ----------
def border_of(game, player):
    """己方与敌方相邻的领地。"""
    return [t for t in game.territories(player)
            if any(game.owner[n] != player for n in ADJ[t])]


def ai_reinforce(game, player):
    n = game.reinforcement_count(player)
    b = border_of(game, player)
    if not b:
        b = game.territories(player)
    # 贪心：敌方相邻兵力最多的前线领地
    def danger(t):
        return sum(game.troops[x] for x in ADJ[t] if game.owner[x] != player)
    tgt = max(b, key=lambda t: (danger(t), game.troops[t]))
    game.place(player, tgt, n)
    return tgt, n


def ai_attack(game, player):
    """贪心进攻：反复打兵力优势最大的战斗，直到无优势战斗或 50 次上限。"""
    log = []
    for _ in range(50):
        best = None
        best_score = 0
        for f, t in game.legal_attacks(player):
            if game.troops[f] < 4:
                continue
            score = game.troops[f] - game.troops[t]
            if score > best_score and game.troops[f] > game.troops[t]:
                best_score = score
                best = (f, t)
        if best is None:
            break
        f, t = best
        r = game.attack(player, f, t)
        log.append((f, t, r["att_lost"], r["def_lost"], r["conquered"]))
        if game.winner() is not None:
            break
    return log


def ai_fortify(game, player):
    """把内陆多余兵力调往最危险的前线。"""
    b = border_of(game, player)
    if not b:
        return None
    def danger(t):
        return sum(game.troops[x] for x in ADJ[t] if game.owner[x] != player)
    tgt = max(b, key=danger)
    for f in game.territories(player):
        if f == tgt:
            continue
        if any(game.owner[n] != player for n in ADJ[f]):
            continue  # 本身就是前线，不动
        if f in ADJ[tgt] and game.troops[f] > 1:
            n = game.troops[f] - 1
            game.fortify(player, f, tgt, n)
            return (f, tgt, n)
    return None


def ai_turn(game, player):
    ai_reinforce(game, player)
    ai_attack(game, player)
    ai_fortify(game, player)


def play_game(seed=None, max_turns=MAX_TURNS):
    game = Risk(seed=seed)
    for turn in range(1, max_turns + 1):
        game.turn = turn
        for p in (0, 1):
            ai_turn(game, p)
            w = game.winner()
            if w is not None:
                return w, turn, game
    # 上限：领地多者胜
    c0 = len(game.territories(0))
    c1 = len(game.territories(1))
    if c0 == c1:
        return -1, max_turns, game
    return (0 if c0 > c1 else 1), max_turns, game


# ---------- 文本界面 ----------
def render(game):
    lines = []
    for r in range(3):
        cells = []
        for c in range(4):
            t = r * 4 + c
            mark = "甲" if game.owner[t] == 0 else "乙"
            cells.append(f"{NAMES[t]}{mark}{game.troops[t]:>2}")
        lines.append(" | ".join(cells))
    return "\n".join(lines)


def parse_terr(s):
    s = s.strip()
    if s in NAMES:
        return NAMES.index(s)
    i = int(s)
    if not (0 <= i < N_TERR):
        raise IllegalMove("领地编号越界")
    return i


def play_interactive():
    if not sys.stdin.isatty():
        print("交互模式需要终端运行；自动演示请用 --auto。", file=sys.stderr)
        sys.exit(2)
    game = Risk()
    print("risk-lite：你是甲（先手），AI 是乙。领地可用编号 0-11 或中文名。")
    print("命令：布 <领地> <数量> / 攻 <从> <到> / 移 <从> <到> <数量> / 过 / 盘 / q")
    for turn in range(1, MAX_TURNS + 1):
        for p, name in ((0, "甲(你)"), (1, "乙(AI)")):
            if p == 0:
                print(f"\n—— 第 {turn} 轮，{name} ——")
                print(render(game))
                left = game.reinforcement_count(0)
                print(f"增援 {left} 兵，例如：布 北原 3")
                while left > 0:
                    cmd = input(f"[增援剩{left}] > ").strip().split()
                    if not cmd:
                        continue
                    if cmd[0] == "q":
                        return
                    if cmd[0] == "盘":
                        print(render(game))
                        continue
                    try:
                        if cmd[0] != "布" or len(cmd) != 3:
                            raise IllegalMove("格式：布 <领地> <数量>")
                        t = parse_terr(cmd[1])
                        n = int(cmd[2])
                        if n < 1 or n > left:
                            raise IllegalMove("数量非法")
                        game.place(0, t, n)
                        left -= n
                    except (IllegalMove, ValueError) as e:
                        print(f"非法：{e}")
                print("进攻阶段（输入 过 结束）：")
                while True:
                    cmd = input("[进攻] > ").strip().split()
                    if not cmd:
                        continue
                    if cmd[0] == "q":
                        return
                    if cmd[0] == "过":
                        break
                    if cmd[0] == "盘":
                        print(render(game))
                        continue
                    try:
                        if cmd[0] != "攻" or len(cmd) != 3:
                            raise IllegalMove("格式：攻 <从> <到>")
                        f, t = parse_terr(cmd[1]), parse_terr(cmd[2])
                        r = game.attack(0, f, t)
                        print(f"骰 {r['att_dice']} vs {r['def_dice']}，"
                              f"我损 {r['att_lost']} 敌损 {r['def_lost']}"
                              + ("，占领！" if r["conquered"] else ""))
                    except (IllegalMove, ValueError) as e:
                        print(f"非法：{e}")
                    w = game.winner()
                    if w is not None:
                        print(render(game))
                        print("你赢了！统一了全部领地。" if w == 0 else "AI 获胜。")
                        return
                cmd = input("[调动一次，格式：移 <从> <到> <数量>，跳过输 过] > ").strip().split()
                if cmd and cmd[0] == "移" and len(cmd) == 4:
                    try:
                        game.fortify(0, parse_terr(cmd[1]), parse_terr(cmd[2]), int(cmd[3]))
                    except (IllegalMove, ValueError) as e:
                        print(f"非法：{e}（跳过调动）")
            else:
                ai_turn(game, 1)
            w = game.winner()
            if w is not None:
                print(render(game))
                print("你赢了！统一了全部领地。" if w == 0 else "AI 获胜。")
                return
    print("达到回合上限，按领地数判定。")
    c0, c1 = len(game.territories(0)), len(game.territories(1))
    print(f"甲 {c0} 块，乙 {c1} 块。" + ("和棋。" if c0 == c1 else ("你赢了。" if c0 > c1 else "AI 获胜。")))


def auto_demo(games, seed):
    wins = {0: 0, 1: 0, -1: 0}
    total_turns = 0
    for i in range(games):
        w, turns, _ = play_game(seed=None if seed is None else seed + i)
        wins[w] += 1
        total_turns += turns
        label = "甲胜" if w == 0 else ("乙胜" if w == 1 else "和棋")
        print(f"第 {i + 1}/{games} 局：{label}（{turns} 回合）")
    print(f"总计：甲胜 {wins[0]}，乙胜 {wins[1]}，和棋 {wins[-1]}，"
          f"平均 {total_turns / games:.1f} 回合/局")


def main(argv=None):
    ap = argparse.ArgumentParser(description="risk-lite：简化版 Risk，纯标准库")
    ap.add_argument("--auto", action="store_true", help="AI 对战自动演示")
    ap.add_argument("--games", type=int, default=10, help="自动演示局数")
    ap.add_argument("--seed", type=int, default=None, help="随机种子")
    args = ap.parse_args(argv)
    if args.auto:
        auto_demo(args.games, args.seed)
    else:
        play_interactive()


if __name__ == "__main__":
    main()
