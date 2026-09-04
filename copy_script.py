import shutil
import os
import sys
import time

# ============================================================
#  进度条
# ============================================================
def progress_bar(current, total, bar_length=40):
    percent = current / total
    filled = int(bar_length * percent)
    bar = '█' * filled + '░' * (bar_length - filled)
    sys.stdout.write(f"\r  [{bar}] {percent*100:.1f}% ({current}/{total})")
    sys.stdout.flush()


def print_header(text):
    print(f"\n{'='*55}")
    print(f"  {text}")
    print(f"{'='*55}")


def print_status(icon, text):
    print(f"\n  {icon} {text}")


# ============================================================
#  核心复制逻辑（文件 + 文件夹都支持）
# ============================================================
def copy_files_to_folder(paths, dest_folder):
    os.makedirs(dest_folder, exist_ok=True)
    dest_folder = os.path.abspath(dest_folder)

    # 过滤空行
    paths = [p.strip().strip('"').strip("'") for p in paths if p.strip()]
    total = len(paths)

    if total == 0:
        print("\n  ❌ 没有有效的路径")
        return

    print_header(f"📁 开始复制 | 共 {total} 个项目 | 目标: {dest_folder}")
    print()

    file_count = 0      # 复制的文件数
    folder_count = 0    # 复制的文件夹数
    fail_count = 0
    rename_count = 0
    failed_items = []

    start_time = time.time()

    for i, path in enumerate(paths, 1):
        progress_bar(i, total)

        # ---- 判断是文件还是文件夹 ----
        is_file = os.path.isfile(path)
        is_folder = os.path.isdir(path)

        if not is_file and not is_folder:
            print_status("❌", f"路径不存在: {path}")
            fail_count += 1
            failed_items.append((path, "路径不存在"))
            continue

        # 获取名称（去掉末尾可能的斜杠）
        name = os.path.basename(path.rstrip(os.sep))

        # 目标路径
        dest_path = os.path.join(dest_folder, name)

        # ---- 同名冲突处理（加序号） ----
        if os.path.exists(dest_path):
            if is_file:
                stem, ext = os.path.splitext(name)
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(dest_folder, f"{stem}({counter}){ext}")
                    counter += 1
            else:
                counter = 1
                while os.path.exists(dest_path):
                    dest_path = os.path.join(dest_folder, f"{name}({counter})")
                    counter += 1
            rename_count += 1

        # ---- 执行复制 ----
        try:
            if is_file:
                shutil.copy2(path, dest_path)
                file_count += 1
            else:
                shutil.copytree(path, dest_path)
                folder_count += 1
        except Exception as e:
            print_status("❌", f"复制失败: {name} -> {e}")
            fail_count += 1
            failed_items.append((path, str(e)))

    # 进度条完成
    progress_bar(total, total)

    # ============================================================
    #  汇总
    # ============================================================
    elapsed = time.time() - start_time

    print_header("📊 复制完成")
    print(f"\n  📄 文件: {file_count}")
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
#  主程序
# ============================================================
if __name__ == "__main__":
    print_header("📁 批量复制工具 v3（文件+文件夹都能复制）")

    print("\n  请选择输入方式：")
    print("    1. 从 txt 文件读取路径列表")
    print("    2. 手动粘贴路径（每行一个，空行结束）")

    choice = input("\n  请输入 1 / 2：").strip()

    paths = []

    if choice == "1":
        list_file = input("  请输入 txt 文件路径：").strip().strip('"').strip("'")
        if not os.path.isfile(list_file):
            print(f"\n  ❌ 找不到文件：{list_file}")
            input("  按回车退出...")
            sys.exit(1)
        with open(list_file, "r", encoding="utf-8") as f:
            paths = [line.strip() for line in f if line.strip()]
    else:
        print("\n  请逐行粘贴路径（文件或文件夹均可），空行结束：")
        while True:
            line = input().strip().strip('"').strip("'")
            if not line:
                break
            paths.append(line)

    if not paths:
        print("\n  ❌ 没有输入任何路径")
        input("  按回车退出...")
        sys.exit(1)

    dest_folder = input("\n  请输入目标文件夹路径：").strip().strip('"').strip("'")

    print(f"\n  📋 共 {len(paths)} 个项目 → {dest_folder}")
    confirm = input("  确认执行？(Y/n)：").strip().lower()
    if confirm == "n":
        print("  已取消。")
        sys.exit(0)

    print()
    time.sleep(0.3)
    copy_files_to_folder(paths, dest_folder)
    input("  按回车退出...")

