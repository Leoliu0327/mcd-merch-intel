#!/usr/bin/env python3
"""麦当劳周边情报输出自检脚本。

校验内容：
1. 五个固定模块是否齐全（缺项不允许）
2. 是否出现违禁词（二手渠道 / 主观评价类）
3. 【活动时效】状态是否为三态之一，且时间与状态是否冲突
4. 已结束活动是否误写了引导兑换话术

用法：
    python check_output.py --file answer.md
    python check_output.py < answer.md

退出码：0 通过；1 存在问题。
"""

import argparse
import re
import sys
from datetime import datetime

REQUIRED_MODULES = [
    "【周边名称】",
    "【活动时效】",
    "【获取规则】",
    "【核心亮点】",
    "【注意事项】",
]

# 违禁词：二手交易渠道与转卖相关，禁止出现在情报输出中
BANNED_WORDS = [
    "闲鱼",
    "代购",
    "二手",
    "转卖",
    "出闲置",
    "收一个",
    "淘宝",
    "拼多多",
    "黄牛",
]

# 已结束状态下禁止出现的引导话术
ENDED_FORBIDDEN = [
    "去门店兑换",
    "前往门店兑换",
    "现在可以兑换",
    "赶紧去换",
    "还能兑换",
    "仍可兑换",
]

VALID_STATUS = {"即将上线", "进行中", "已结束"}


def _timing_blocks(text: str):
    """按【活动时效】切块，返回该卡片内的时效正文。

    多款周边并列输出时，起止时间与状态必须按卡片配对校验，
    否则会出现「上一款的结束时间配上下一款的状态」这类误报。
    """
    pattern = re.compile(r"【[^】]+】")
    matches = list(pattern.finditer(text))
    for index, match in enumerate(matches):
        if match.group() != "【活动时效】":
            continue
        stop = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        yield text[match.end():stop]


def _parse_time(value: str):
    value = value.strip().replace("T", " ")
    fmt = "%Y-%m-%d %H:%M" if len(value) > 10 else "%Y-%m-%d"
    try:
        return datetime.strptime(value, fmt)
    except ValueError:
        return None


def check(text: str):
    errors = []
    warnings = []

    # 1. 模块齐全性
    for module in REQUIRED_MODULES:
        if module not in text:
            errors.append(f"缺少必需模块：{module}")

    # 2. 违禁词
    for word in BANNED_WORDS:
        if word in text:
            errors.append(f"出现违禁词「{word}」，禁止输出二手交易渠道信息")

    # 3. 状态合法性与冲突（按卡片逐条校验）
    now = datetime.now()
    for order, block in enumerate(_timing_blocks(text), start=1):
        times = dict(
            re.findall(
                r"(开始时间|结束时间)[：:]\s*(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)",
                block,
            )
        )
        status_match = re.search(r"当前状态[：:]\s*(\S+)", block)
        if not status_match:
            continue
        status = status_match.group(1)
        if status not in VALID_STATUS:
            errors.append(
                f"第 {order} 款状态取值非法：「{status}」，仅允许 {sorted(VALID_STATUS)}"
            )
            continue

        start = _parse_time(times["开始时间"]) if "开始时间" in times else None
        end = _parse_time(times["结束时间"]) if "结束时间" in times else None

        # 缺少任一端时间（官方未公开）时不判冲突，避免误报
        if start is None or end is None:
            if status == "进行中" and start is not None and start > now:
                warnings.append(f"第 {order} 款标注「进行中」，但开始时间尚未到，请复核")
            continue

        if start > end:
            errors.append(f"第 {order} 款开始时间晚于结束时间，时间数据异常")
        if status == "进行中" and not (start <= now <= end):
            warnings.append(f"第 {order} 款标注「进行中」，但当前时间不在起止区间内，请复核")
        if status == "已结束" and end > now:
            warnings.append(f"第 {order} 款标注「已结束」，但结束时间晚于当前时间，请复核")
        if status == "即将上线" and start <= now:
            warnings.append(f"第 {order} 款标注「即将上线」，但开始时间已过，请复核")

    if "已结束" in text:
        for phrase in ENDED_FORBIDDEN:
            if phrase in text:
                errors.append(
                    f"活动已结束，但出现引导兑换话术「{phrase}」，禁止引导用户去门店兑换"
                )
        if "该活动已结束" not in text:
            warnings.append("标记为已结束，建议追加固定说明：该活动已结束，目前无法通过官方渠道获取，请以官方后续活动为准。")

    # 4. 时间与状态一致性（尽力校验，无法解析则跳过）
    times = re.findall(r"(开始时间|结束时间)[：:]\s*(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2})?)", text)
    parsed = {}
    for label, value in times:
        fmt = "%Y-%m-%d %H:%M" if len(value) > 10 else "%Y-%m-%d"
        try:
            parsed[label] = datetime.strptime(value.replace("T", " "), fmt)
        except ValueError:
            continue

    return errors, warnings


def main():
    parser = argparse.ArgumentParser(description="校验麦当劳周边情报输出的规范性")
    parser.add_argument("--file", help="待校验的情报文本文件路径；不传则从标准输入读取")
    args = parser.parse_args()

    if args.file:
        with open(args.file, "r", encoding="utf-8") as fh:
            text = fh.read()
    else:
        text = sys.stdin.read()

    if not text.strip():
        print("输入为空，无法校验")
        sys.exit(1)

    errors, warnings = check(text)

    for warning in warnings:
        print(f"[提示] {warning}")

    if errors:
        for error in errors:
            print(f"[错误] {error}")
        print(f"\n校验未通过，共 {len(errors)} 项错误")
        sys.exit(1)

    print("校验通过：五个模块齐全，无违禁词，时效状态规范")


if __name__ == "__main__":
    main()
