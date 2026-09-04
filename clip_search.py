# -*- coding: utf-8 -*-
"""
剪贴板自动搜索（Windows）
--------------------------------------------------
单行复制：自动监听剪贴板，复制立刻搜索
多行复制：复制多行单元格，托盘右键点【批量多行搜索】，逐行搜索，全部输出到txt
--------------------------------------------------
依赖安装（只需一次，命令行里执行）：
    pip install pywin32 pillow pystray
运行：
    双击同目录下的「启动搜索.bat」（用 pythonw 启动，不弹黑窗口，只在右下角托盘待命）
    想停止：右键托盘图标 → 退出
改完配置保存后，重新运行一次即生效。
"""
import os
import time
import threading
import subprocess
import win32clipboard
import win32con
import win32gui
import win32api
from pystray import Icon, MenuItem as Item
from PIL import Image, ImageDraw
# ============================================================
# CONFIG —— 只改这里
# ============================================================
# 要搜索的文件夹（支持 UNC 网络路径，注意前面的 r"" 不要丢）
SEARCH_ROOT = r"地址"
# 是否递归搜索子文件夹
RECURSIVE = True
# 匹配方式：CONTAINS = 名称里包含复制的文字即可；PREFIX = 名称以它开头；EXACT = 完全相同
MATCH_MODE = "CONTAINS"
# True  = 搜到第一个就停（并自动打开所在文件夹）；False = 全部搜完汇总
STOP_AT_FIRST = False
# 忽略这些扩展名（临时文件、快捷方式等即使匹配也不算命中）
IGNORE_EXT = {".lnk", ".crdownload", ".part", ".et"}
# 是否忽略大小写
IGNORE_CASE = True
# 单次关键词最多返回多少条匹配
MAX_RESULTS = 2000
# 复制内容少于几个字符不触发
MIN_QUERY_LEN = 2
MAX_QUERY_LEN = 100
# 批量搜索最大行数，防止复制成千上万行卡死
BATCH_MAX_LINES = 300
# 普通搜索日志
RESULT_LOG = os.path.join(os.path.expanduser("~"), "Documents", "剪贴板搜索结果.log")
LAST_RESULT_TXT = os.path.join(os.path.expanduser("~"), "Documents", "最近一次搜索结果.txt")
# 批量多行搜索输出文件
BATCH_RESULT_TXT = os.path.join(os.path.expanduser("~"), "Documents", "批量搜索输出.txt")

POLL_INTERVAL = 0.35
# ============================================================
# 以下不需要改
# ============================================================
_running = True
_icon = None
_last_text = None
_search_thread = None
_lock = threading.Lock()

MATCH_FUNCS = {
    "CONTAINS": lambda name, q: q in name,
    "PREFIX":   lambda name, q: name.startswith(q),
    "EXACT":    lambda name, q: name == q,
}

def log(msg):
    try:
        os.makedirs(os.path.dirname(RESULT_LOG), exist_ok=True)
        with open(RESULT_LOG, "a", encoding="utf-8") as f:
            f.write("[%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), msg))
    except Exception:
        pass

def beep(kind="ok"):
    sound = {"found": win32con.MB_ICONASTERISK,
             "notfound": win32con.MB_ICONEXCLAMATION}.get(kind, win32con.MB_OK)
    try:
        win32api.MessageBeep(sound)
    except Exception:
        pass

def get_clipboard_text():
    try:
        win32clipboard.OpenClipboard()
    except Exception:
        return None
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        return None
    except Exception:
        return None
    finally:
        try:
            win32clipboard.CloseClipboard()
        except Exception:
            pass

def clean_query(raw):
    """单行模式清理，用于自动监听（取第一行）"""
    if not raw:
        return None
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = text.split("\n")[0].split("\t")[0]
    text = " ".join(text.split())
    if len(text) < MIN_QUERY_LEN or len(text) > MAX_QUERY_LEN:
        return None
    return text

def split_batch_lines(raw_text):
    """批量模式：把剪贴板多行拆成每行关键词，清洗过滤"""
    if not raw_text:
        return []
    lines = raw_text.replace("\r\n","\n").replace("\r","\n").split("\n")
    out = []
    for line in lines:
        s = line.split("\t")[0].strip()
        s = " ".join(s.split())
        if MIN_QUERY_LEN <= len(s) <= MAX_QUERY_LEN:
            out.append(s)
    return list(dict.fromkeys(out))[:BATCH_MAX_LINES]

def matches(name, query):
    func = MATCH_FUNCS.get(MATCH_MODE, MATCH_FUNCS["CONTAINS"])
    if IGNORE_CASE:
        return func(name.lower(), query.lower())
    return func(name, query)

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

def reveal_in_explorer(path):
    try:
        subprocess.Popen('explorer /select,"%s"' % os.path.normpath(path))
    except Exception:
        pass

def show_result(text, title="剪贴板搜索结果"):
    try:
        win32gui.MessageBox(0, text, title, win32con.MB_OK | win32con.MB_TOPMOST)
    except Exception:
        print(text)

def _single_search_core(query):
    """内部：单个关键词搜索，返回匹配列表，不弹窗"""
    if not os.path.isdir(SEARCH_ROOT):
        return None, []
    matched = []
    for full_path, name, is_dir in iter_candidates(SEARCH_ROOT):
        if matches(name, query):
            matched.append((name, full_path, is_dir))
            if len(matched)>=MAX_RESULTS:
                break
    return True, matched

def do_search(query):
    """原单关键词弹窗搜索（自动监听调用）"""
    if not os.path.isdir(SEARCH_ROOT):
        log("ERROR 目录不可用 | query=%s" % query)
        beep("notfound")
        show_result(
            "找不到搜索目录，请检查路径或网络盘连接：\n\n%s" % SEARCH_ROOT,
            "目录不可用",
        )
        return
    matched = []
    stopped_early = False
    for full_path, name, is_dir in iter_candidates(SEARCH_ROOT):
        if matches(name, query):
            label = name + ("\\" if is_dir else "")
            matched.append((label, full_path, is_dir))
            log("HIT    %s" % full_path)
            if STOP_AT_FIRST:
                stopped_early = True
                break
            if len(matched) >= MAX_RESULTS:
                break

    if not matched:
        beep("notfound")
        show_result(f"没有匹配到任何文件或文件夹。\n关键词：{query}","未找到")
        return
    beep("found")
    if stopped_early:
        label, path, is_dir = matched[0]
        reveal_in_explorer(path)
        show_result(f"已为你打开所在位置：\n\n{label}\n{path}","找到 1 项（搜到即停）")
        return

    names = [m[0] for m in matched]
    paths = [m[1] for m in matched]
    summary = "\n".join(names)
    try:
        with open(LAST_RESULT_TXT, "w", encoding="utf-8-sig") as f:
            f.write(f"关键词：{query}\n匹配 {len(matched)} 项\n\n===名称===\n")
            f.write("\n".join(names)+"\n===完整路径===\n"+"\n".join(paths))
    except Exception:
        pass
    show_result(f"关键词：{query}\n匹配 {len(matched)} 项\n\n{summary}\n完整清单保存在【文档】→最近一次搜索结果.txt","匹配结果")

def do_batch_search():
    """托盘菜单：批量多行搜索"""
    raw = get_clipboard_text()
    lines = split_batch_lines(raw)
    if len(lines) == 0:
        show_result("剪贴板没有读到有效多行关键词！\n复制WPS多行单元格后再点本功能","批量搜索")
        return
    if not os.path.isdir(SEARCH_ROOT):
        show_result("共享目录不可用！","错误")
        return

    out_lines = []
    out_lines.append(f"=====批量搜索 {time.strftime('%Y-%m-%d %H:%M:%S')} =====")
    out_lines.append(f"搜索目录：{SEARCH_ROOT}")
    out_lines.append(f"待搜索总条数：{len(lines)}")
    out_lines.append("")

    hit_count = 0
    miss_count = 0
    for keyword in lines:
        ok, matched = _single_search_core(keyword)
        if not ok:
            out_lines.append(f"【{keyword}】→目录访问失败")
            continue
        if len(matched) == 0:
            out_lines.append(f"【{keyword}】→❌未找到")
            miss_count +=1
        else:
            hit_count +=1
            out_lines.append(f"【{keyword}】✅找到{len(matched)}个结果")
            for name,path,isdir in matched:
                out_lines.append(f"    {name} | {path}")
        out_lines.append("")

    total = hit_count + miss_count
    out_lines.append(f"\n====统计：命中{hit_count}条 / 未找到{miss_count}条 / 共{total}个关键词====")
    try:
        with open(BATCH_RESULT_TXT,"w",encoding="utf-8-sig") as f:
            f.write("\n".join(out_lines))
    except Exception as e:
        show_result(f"写入批量结果失败：{e}")
        return
    beep("found")
    show_result(f"批量搜索完成！\n总关键词：{len(lines)}\n命中:{hit_count} 未找到:{miss_count}\n结果文件保存在文档文件夹：批量搜索输出.txt","批量搜索完成")
    try:
        os.startfile(BATCH_RESULT_TXT)
    except Exception:
        pass

def search_worker(query):
    global _search_thread
    try:
        do_search(query)
    except Exception as e:
        log("EXCEPT %r" % e)
        beep("notfound")
        show_result("搜索出错了：\n%r" % e, "出错了")
    finally:
        with _lock:
            _search_thread = None

def trigger_search(query):
    global _search_thread
    if not query:
        return
    with _lock:
        if _search_thread is not None and _search_thread.is_alive():
            return
        _search_thread = threading.Thread(target=search_worker, args=(query,), daemon=True)
        _search_thread.start()

def watcher_loop():
    global _last_text
    _last_text = clean_query(get_clipboard_text())
    while _running:
        time.sleep(POLL_INTERVAL)
        text = clean_query(get_clipboard_text())
        if not text or text == _last_text:
            continue
        _last_text = text
        log("QUERY  %s" % text)
        trigger_search(text)

def make_image(color=(80, 170, 255)):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((8, 6, 40, 38), outline=color, width=6)
    d.line((37, 35, 56, 56), fill=color, width=8)
    return img

def on_quit(icon, item=None):
    global _running
    _running = False
    try:
        icon.stop()
    except Exception:
        pass

def on_test(icon, item=None):
    trigger_search(clean_query(get_clipboard_text()))

def on_open_log(icon, item=None):
    try:
        os.startfile(RESULT_LOG)
    except Exception:
        pass

def on_open_result(icon, item=None):
    try:
        os.startfile(LAST_RESULT_TXT)
    except Exception:
        pass

def on_open_batch_result(icon, item=None):
    try:
        os.startfile(BATCH_RESULT_TXT)
    except Exception:
        pass

def on_open_folder(icon, item=None):
    try:
        os.startfile(SEARCH_ROOT)
    except Exception:
        pass

def main():
    global _icon
    print("剪贴板自动搜索已启动")
    print(f"  搜索目录：{SEARCH_ROOT}")
    items = [
        Item("目录：%s" % SEARCH_ROOT, None, enabled=False),
        Item("模式：%s" % ("搜到即停" if STOP_AT_FIRST else "全部汇总"), None, enabled=False),
        Item("打开搜索目录", on_open_folder),
        Item("测试一次（搜当前剪贴板单行）", on_test),
        Item("✅批量多行搜索（复制多行后点这里）", do_batch_search),
        Item("打开单条结果清单 txt", on_open_result),
        Item("打开批量搜索输出 txt", on_open_batch_result),
        Item("打开结果日志", on_open_log),
        Item("退出", on_quit),
    ]
    _icon = Icon("clipsearch", make_image(), "剪贴板自动搜索待命中", items)
    threading.Thread(target=_icon.run, daemon=True).start()
    watcher_loop()
    print("已退出。")

if __name__ == "__main__":
    main()
