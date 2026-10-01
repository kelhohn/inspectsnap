"""Защита от несовместимого torchcodec на Windows.

f5-tts тянет свежий torchcodec, а он не совместим с PyTorch 2.8 (WinError 127,
«точка входа torch_list_push_back не найдена»). Нам он не нужен: прячем модуль, и
transformers/torchaudio считают, что его нет. Импортировать ДО torch/transformers.

Дочерние процессы (Demucs и т.п.) этот импорт не делают, поэтому в окружение .venv
кладётся .pth-файл: Python выполняет его при каждом запуске интерпретатора из .venv.
"""

import sys
import sysconfig
from pathlib import Path

PTH_NAME = "zz_voicebot_no_torchcodec.pth"
PTH_LINE = "import sys; sys.modules.setdefault('torchcodec', None)\n"

sys.modules.setdefault("torchcodec", None)  # type: ignore[arg-type]


def install_pth() -> None:
    if sys.prefix == sys.base_prefix:  # не трогаем системный Python — только .venv
        return
    try:
        path = Path(sysconfig.get_paths()["purelib"]) / PTH_NAME
        if not path.exists() or path.read_text(encoding="utf-8") != PTH_LINE:
            path.write_text(PTH_LINE, encoding="utf-8")
    except OSError:
        pass


install_pth()
