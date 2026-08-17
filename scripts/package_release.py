"""创建可安全交付的项目 ZIP。

归档会主动排除密钥、虚拟环境、审计日志、导出文件和 Git 元数据；
不会读取或写入 SQL Server。
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
from pathlib import Path
import zipfile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT.parent / "outputs"
PROJECT_NAME = "project2SQLServer导入excel系统"
EXCLUDED_PARTS = {".git", ".venv", ".pytest_cache", "__pycache__", "exports", "logs"}
EXCLUDED_FILENAMES = {"audit.db", "secrets.toml"}


def should_include(path: Path) -> bool:
    relative = path.relative_to(PROJECT_ROOT)
    if any(part in EXCLUDED_PARTS for part in relative.parts):
        return False
    if path.name in EXCLUDED_FILENAMES or path.suffix in {".pyc", ".db"}:
        return False
    return path.is_file()


def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_path = OUTPUT_DIR / f"{PROJECT_NAME}_V2_{stamp}.zip"
    manifest: list[str] = []

    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(PROJECT_ROOT.rglob("*")):
            if not should_include(path):
                continue
            relative = path.relative_to(PROJECT_ROOT)
            archive_name = f"{PROJECT_NAME}/{relative.as_posix()}"
            archive.write(path, archive_name)
            manifest.append(f"{sha256(path.read_bytes()).hexdigest()}  {relative.as_posix()}")
        archive.writestr(f"{PROJECT_NAME}/MANIFEST.sha256", "\n".join(manifest) + "\n")

    print(f"已生成安全交付包：{archive_path}")
    print(f"包含 {len(manifest)} 个文件；未包含密钥、审计日志、导出文件或虚拟环境。")


if __name__ == "__main__":
    main()
