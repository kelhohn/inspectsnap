"""Защита от несовместимого torchcodec на Windows.

f5-tts тянет свежий torchcodec, а он не совместим с PyTorch 2.8 (WinError 127,
«точка входа torch_list_push_back не найдена»). Нам он не нужен: прячем модуль, и
transformers/torchaudio считают, что его нет. Импортировать ДО torch/transformers.
"""

import sys

sys.modules.setdefault("torchcodec", None)  # type: ignore[arg-type]
