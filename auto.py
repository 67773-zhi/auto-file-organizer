from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path

CATEGORY_EXTS: dict[str, set[str]] = {
    "图片": {"jpg", "png", "jpeg", "gif", "bmp", "webp"},
    "文档": {"txt", "pdf", "docx", "doc", "xlsx", "xls", "ppt", "pptx"},
    "视频": {"mp4", "avi", "mov", "mkv", "flv"},
    "安装包": {"exe", "msi", "zip", "rar", "7z"},
}
ALL_CATEGORIES = ["图片", "文档", "视频", "安装包", "其他"]
LOG_NAME = "._auto_organizer_lastlog.json"


def pick_category(path: Path) -> str:
    ext = path.suffix.lower().lstrip(".")
    for cat, exts in CATEGORY_EXTS.items():
        if ext in exts:
            return cat
    return "其他"


def ensure_dirs(target_dir: Path) -> dict[str, Path]:
    out: dict[str, Path] = {}
    for name in ALL_CATEGORIES:
        p = target_dir / name
        p.mkdir(parents=True, exist_ok=True)
        out[name] = p
    return out


def unique_dest(dest_dir: Path, filename: str) -> Path:
    src = Path(filename)
    stem, suffix = src.stem, src.suffix
    cand = dest_dir / filename
    if not cand.exists():
        return cand
    i = 1
    while True:
        cand = dest_dir / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
        i += 1


def build_plan(target_dir: Path, self_path: Path) -> list[tuple[Path, Path]]:
    cat_dirs = ensure_dirs(target_dir)
    plan: list[tuple[Path, Path]] = []

    for entry in target_dir.iterdir():
        # 不移动文件夹；只处理当前目录这一层文件
        if not entry.is_file():
            continue

        # 不移动脚本本身（如果脚本就在被整理目录内）
        try:
            if entry.resolve() == self_path:
                continue
        except OSError:
            if entry.name == self_path.name and entry.parent == self_path.parent:
                continue

        # 不整理撤回日志文件本身
        if entry.name == LOG_NAME:
            continue

        cat = pick_category(entry)
        dst_dir = cat_dirs[cat]
        dst = unique_dest(dst_dir, entry.name)
        plan.append((entry, dst))

    return plan


def choose_target_dir() -> Path | None:
    """优先弹出选择文件夹窗口；若环境无 tkinter，则回退为手动输入路径。"""
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        selected = filedialog.askdirectory(title="选择要整理的文件夹")
        root.destroy()

        if not selected:
            return None
        return Path(selected)
    except Exception:
        raw = input("请输入要整理的文件夹路径（回车取消）：").strip().strip('"')
        if not raw:
            return None
        return Path(raw).expanduser()


def load_last_log(target_dir: Path) -> list[dict[str, str]] | None:
    log_path = target_dir / LOG_NAME
    if not log_path.exists():
        return None
    try:
        data = json.loads(log_path.read_text(encoding="utf-8"))
        moves = data.get("moves")
        if isinstance(moves, list):
            return moves
    except Exception:
        return None
    return None


def save_last_log(target_dir: Path, moves: list[tuple[Path, Path]]) -> None:
    log_path = target_dir / LOG_NAME
    payload = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "moves": [{"src": str(src), "dst": str(dst)} for src, dst in moves],
    }
    log_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def undo_last(target_dir: Path) -> None:
    moves = load_last_log(target_dir)
    if not moves:
        print("未找到可撤回的记录。")
        return

    print(f"\n目标文件夹：{target_dir}")
    print(f"将尝试撤回上一次整理（读取 {LOG_NAME}）。\n")

    # 预览撤回
    preview: list[tuple[Path, Path]] = []
    for m in moves:
        if not isinstance(m, dict):
            continue
        src = Path(m.get("src", ""))
        dst = Path(m.get("dst", ""))
        if not src or not dst:
            continue
        # 整理时是 src->dst；撤回时是 dst->src
        preview.append((dst, src))

    if not preview:
        print("撤回记录无效或为空。")
        return

    for src_now, back_to in preview:
        print(f"- {src_now.name}  ->  {back_to.parent}{os.sep}{back_to.name}")

    confirm = input("\n确认无误请按回车开始撤回（输入任意内容取消）：")
    if confirm.strip():
        print("已取消，不会移动任何文件。")
        return

    ok = 0
    for src_now, back_to in preview:
        try:
            if not src_now.exists():
                print(f"跳过：找不到 {src_now}")
                continue
            back_dir = back_to.parent
            back_dir.mkdir(parents=True, exist_ok=True)
            dest = unique_dest(back_dir, back_to.name)
            shutil.move(str(src_now), str(dest))
            ok += 1
        except Exception as e:
            print(f"撤回失败：{src_now} -> {back_to}，原因：{e}")

    print(f"\n撤回完成：成功撤回 {ok}/{len(preview)} 个文件。")


def main() -> None:
    self_path = Path(__file__).resolve()

    target_dir = choose_target_dir()
    if target_dir is None:
        print("已取消，不会移动任何文件。")
        return

    if not target_dir.exists() or not target_dir.is_dir():
        print("路径不存在或不是文件夹，请检查后重试。")
        return

    try:
        target_dir = target_dir.resolve()
    except OSError:
        pass

    # 如果存在撤回记录，让用户选择是否撤回
    if (target_dir / LOG_NAME).exists():
        choice = input("检测到上次整理记录。输入 U 回车撤回；直接回车继续整理：").strip().lower()
        if choice == "u":
            undo_last(target_dir)
            return

    plan = build_plan(target_dir, self_path)

    print(f"\n目标文件夹：{target_dir}")
    print("将创建/确保存在：图片、文档、视频、安装包、其他")

    if not plan:
        print("\n未发现需要整理的文件（只整理当前层文件，文件夹不会动）。")
        return

    print(f"\n预览：共 {len(plan)} 个文件将被移动：\n")
    for src, dst in plan:
        print(f"- {src.name}  ->  {dst.parent.name}{os.sep}{dst.name}")

    confirm = input("\n确认无误请按回车开始移动（输入任意内容取消）：")
    if confirm.strip():
        print("已取消，不会移动任何文件。")
        return

    # 保存撤回清单（在实际移动之前写入，避免移动后崩溃无法撤回）
    save_last_log(target_dir, plan)

    moved = 0
    for src, dst in plan:
        try:
            shutil.move(str(src), str(dst))
            moved += 1
        except Exception as e:
            print(f"移动失败：{src.name} -> {dst}，原因：{e}")

    print(f"\n完成：成功移动 {moved}/{len(plan)} 个文件。")
    print(f"如需撤回：下次再运行脚本，输入 U 即可。")


if __name__ == "__main__":
    main()
