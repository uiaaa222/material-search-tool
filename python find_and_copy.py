# -*- coding: utf-8 -*-
"""
文件名查找 + 复制工具
=============================================================
流程：复制多个文件名（一般是 MP4）→ 按名字在目录里找到地址 → 复制到指定文件夹
使用步骤：
    1. 改好下方 CONFIG（搜索目录、自动补全的扩展名、匹配方式）
    2. 运行脚本，选择文件名输入方式（txt / 手动粘贴 / 剪贴板）
    3. 输入目标文件夹路径
    4. 确认后自动：逐个按名字搜索地址 → 复制到目标文件夹
依赖：无第三方依赖（剪贴板读取需要 pywin32，可 pip install pywin32，不用时可不管）
=============================================================
"""
import os
import shutil
import sys
import time

# ============================================================
# CONFIG —— 只改这里
# ============================================================
# 在哪个目录里按名字搜索（支持 UNC 网络路径，注意 r"" 不要丢）
SEARCH_ROOT = r"\\172.16.0.88\全球g1\视频\投放素材"

# 是否递归搜索子文件夹
RECURSIVE = True

# 复制的文件名不带扩展名时，自动按顺序尝试补全再精确匹配（一般写 .mp4 即可）
TRY_EXTENSIONS = [".mp4"]

# 精确匹配失败后的模糊匹配方式：
#   CONTAINS = 名称里包含关键词；PREFIX = 名称以关键词开头；EXACT = 完全相同
MATCH_MODE = "CONTAINS"

# 是否忽略大小写
IGNORE_CASE = True

# 忽略这些扩展名的文件（临时文件、快捷方式等即使匹配也不算命中）
IGNORE_EXT = {".lnk", ".crdownload", ".part", ".et"}

# 单个文件名最多返回多少条匹配
MAX_RESULTS = 50
# ============================================================
# 以下不用改
# ============================================================

def _norm(s):
    return s.lower() if IGNORE_CASE else s


def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}")


def print_status(icon, text):
    print(f"  {icon} {text}")


def progress_bar(current, total, bar_length=40):
    if total <= 0:
        return
    percent = current / total
    filled = int(bar_length * percent)
    bar = '█' * filled + '░' * (bar_length - filled)
    sys.stdout.write(f"\r  [{bar}] {percent*100:.1f}% ({current}/{total})")
    sys.stdout.flush()


# ============================================================
#  目录遍历（借鉴 clip_search）
# ============================================================
def iter_candidates(root):
    stack = [root]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                entries = list(it)
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir(follow_symlinks=False):
                    yield e.path, e.name, True
                    if RECURSIVE:
                        stack.append(e.path)
                else:
                    ext = os.path.splitext(e.name)[1].lower()
                    if ext in IGNORE_EXT:
                        continue
                    yield e.path, e.name, False
            except OSError:
                continue


def build_index(root):
    """遍历一次目录，建立「名称 -> 路径列表」索引，供批量查询复用"""
    index = {}                # 规范化名称 -> [(显示名, 完整路径, 是否文件夹)]
    all_entries = []          # 全部条目，用于模糊匹配扫描
    for full_path, name, is_dir in iter_candidates(root):
        key = _norm(name)
        index.setdefault(key, []).append((name, full_path, is_dir))
        all_entries.append((name, full_path, is_dir))
    return index, all_entries


def find_matches(index, all_entries, keyword):
    """按名称查找，返回 [(显示名, 完整路径, 是否文件夹), ...]
    查找顺序：精确匹配 → 自动补扩展名精确匹配 → 模糊匹配
    返回 None 表示目录不可用；返回 [] 表示未找到。
    """
    kw = keyword.strip().strip('"').strip("'")
    if not kw:
        return []
    k = _norm(kw)

    # 1) 精确匹配（原样名称）
    exact = index.get(k)
    if exact:
        return exact

    # 2) 精确匹配：自动补扩展名（如关键词 "abc" 尝试 "abc.mp4"）
    for ext in TRY_EXTENSIONS:
        got = index.get(k + _norm(ext))
        if got:
            return got

    # 3) 模糊匹配
    func = {
        "CONTAINS": lambda name, q: q in name,
        "PREFIX":   lambda name, q: name.startswith(q),
        "EXACT":    lambda name, q: name == q,
    }.get(MATCH_MODE, lambda name, q: q in name)

    out = []
    for name, path, is_dir in all_entries:
        if func(_norm(name), k):
            out.append((name, path, is_dir))
            if len(out) >= MAX_RESULTS:
                break
    return out


# ============================================================
#  复制逻辑（借鉴 copy_script）
# ============================================================
def copy_files_to_folder(items, dest_folder):
    """items: [(名称, 源路径, 是否文件夹), ...]"""
    os.makedirs(dest_folder, exist_ok=True)
    dest_folder = os.path.abspath(dest_folder)

    total = len(items)
    if total == 0:
        print("\n  ❌ 没有可复制的项目")
        return

    print_header(f"📁 开始复制 | 共 {total} 个项目 | 目标: {dest_folder}")
    print()

    file_count = 0
    folder_count = 0
    fail_count = 0
    rename_count = 0
    failed_items = []
    start_time = time.time()

    for i, (name, src, is_dir) in enumerate(items, 1):
        progress_bar(i, total)

        if not os.path.exists(src):
            print_status("❌", f"源路径不存在: {src}")
            fail_count += 1
            failed_items.append((src, "源路径不存在"))
            continue

        dest_path = os.path.join(dest_folder, name)

        # 同名冲突处理（加序号）
        if os.path.exists(dest_path):
            if is_dir:
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(dest_folder, f"{name}({counter})")
                    counter += 1
            else:
                stem, ext = os.path.splitext(name)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(dest_folder, f"{stem}({counter}){ext}")
                    counter += 1
            rename_count += 1

        try:
            if is_dir:
                shutil.copytree(src, dest_path)
                folder_count += 1
            else:
                shutil.copy2(src, dest_path)
                file_count += 1
        except Exception as e:
            print_status("❌", f"复制失败: {name} -> {e}")
            fail_count += 1
            failed_items.append((src, str(e)))

    progress_bar(total, total)
    elapsed = time.time() - start_time

    print_header("📊 复制完成")
    print(f"  📄 文件: {file_count}")
    print(f"  📂 文件夹: {folder_count}")
    print(f"  ❌ 失败: {fail_count}")
    if rename_count > 0:
        print(f"  ⚠️  重命名: {rename_count}（同名自动加了序号）")
    print(f"  ⏱️  耗时: {elapsed:.1f} 秒")
    print(f"  📂 目标文件夹: {dest_folder}")

    if failed_items:
        print(f"\n  —— 失败详情 ——")
        for path, reason in failed_items:
            print(f"  • {path}")
            print(f"    原因: {reason}")
    print()


# ============================================================
#  文件名输入
# ============================================================
def read_names_from_txt(path):
    with open(path, "r", encoding="utf-8") as f:
        return [line.strip().strip('"').strip("'") for line in f if line.strip()]


def read_names_from_clipboard():
    try:
        import win32clipboard
        import win32con
    except ImportError:
        print("\n  ⚠️ 未安装 pywin32，无法读取剪贴板。可执行：pip install pywin32")
        return []
    try:
        win32clipboard.OpenClipboard()
        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                raw = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
            else:
                raw = ""
        finally:
            win32clipboard.CloseClipboard()
    except Exception as e:
        print(f"\n  ⚠️ 读取剪贴板失败: {e}")
        return []
    return [line.strip().strip('"').strip("'")
            for line in raw.replace("\r\n", "\n").split("\n") if line.strip()]


# ============================================================
#  主程序
# ============================================================
def main():
    print_header("🎬 文件名查找 + 复制工具 v1")
    print(f"  搜索目录: {SEARCH_ROOT}")
    print(f"  自动补全扩展名: {TRY_EXTENSIONS}")

    if not os.path.isdir(SEARCH_ROOT):
        print(f"\n  ❌ 搜索目录不可用，请先修改 CONFIG 里的 SEARCH_ROOT：\n  {SEARCH_ROOT}")
        input("  按回车退出...")
        sys.exit(1)

    print("\n  请选择文件名输入方式：")
    print("    1. 从 txt 文件读取（每行一个文件名）")
    print("    2. 手动粘贴（每行一个，空行结束）")
    print("    3. 读取剪贴板（Windows，需 pywin32）")
    choice = input("\n  请输入 1 / 2 / 3：").strip()

    names = []
    if choice == "1":
        list_file = input("  请输入 txt 文件路径：").strip().strip('"').strip("'")
        if not os.path.isfile(list_file):
            print(f"\n  ❌ 找不到文件：{list_file}")
            input("  按回车退出...")
            sys.exit(1)
        names = read_names_from_txt(list_file)
    elif choice == "3":
        names = read_names_from_clipboard()
        if not names:
            print("\n  ❌ 剪贴板没有读到文件名（或未安装 pywin32）")
            input("  按回车退出...")
            sys.exit(1)
    else:
        print("\n  请逐行粘贴文件名，空行结束：")
        while True:
            line = input().strip().strip('"').strip("'")
            if not line:
                break
            names.append(line)

    if not names:
        print("\n  ❌ 没有输入任何文件名")
        input("  按回车退出...")
        sys.exit(1)

    # 去重
    seen, unique = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    names = unique

    dest_folder = input("\n  请输入目标文件夹路径：").strip().strip('"').strip("'")
    if not dest_folder:
        print("\n  ❌ 目标文件夹不能为空")
        input("  按回车退出...")
        sys.exit(1)

    print_header("🔍 按名字查找地址")
    print(f"  共 {len(names)} 个文件名，正在搜索...\n")
    index, all_entries = build_index(SEARCH_ROOT)

    plan = []          # [(显示名, 源路径, 是否文件夹)]
    not_found = []     # 未找到的关键词
    multi_hint = []    # 命中多个的关键词

    for i, kw in enumerate(names, 1):
        progress_bar(i, len(names))
        matched = find_matches(index, all_entries, kw)
        if not matched:
            not_found.append(kw)
            continue
        if len(matched) > 1:
            multi_hint.append((kw, len(matched)))
        name, path, is_dir = matched[0]
        plan.append((name, path, is_dir))

    progress_bar(len(names), len(names))
    print("\n")

    print_header("📋 待复制清单")
    print(f"\n  将复制 {len(plan)} 个文件 → {os.path.abspath(dest_folder)}")
    for name, path, is_dir in plan:
        kind = "📂 文件夹" if is_dir else "📄 文件"
        print(f"  {kind} {name}")
        print(f"        ← {path}")
    if multi_hint:
        print(f"\n  ⚠️ {len(multi_hint)} 个名称命中多个文件，默认复制第 1 个：")
        for kw, cnt in multi_hint:
            print(f"     • {kw}（命中 {cnt} 个）")
    if not_found:
        print(f"\n  ❌ 未找到 {len(not_found)} 个：")
        for kw in not_found:
            print(f"     • {kw}")

    confirm = input("\n  确认复制？(Y/n)：").strip().lower()
    if confirm == "n":
        print("  已取消。")
        sys.exit(0)

    print()
    time.sleep(0.3)
    copy_files_to_folder(plan, dest_folder)
    input("  按回车退出...")


if __name__ == "__main__":
    main()
