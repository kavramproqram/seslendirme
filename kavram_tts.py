# Kavram - Piper tabanlı çevrimdışı Türkçe seslendirme motoru
# Editör arayüzünden bağımsız tutulur.

import os
import shutil
import subprocess
import tempfile

from PyQt5.QtCore import QThread, pyqtSignal


def default_model_path():
    """Kullanılacak Türkçe Piper ONNX modelinin konumunu döndürür."""
    configured = os.environ.get("KAVRAM_PIPER_MODEL")
    if configured:
        return os.path.abspath(os.path.expanduser(configured))
    return os.path.expanduser(
        "~/.local/share/kavram/voices/tr_TR-fahrettin-medium.onnx"
    )


def find_piper():
    """PATH veya çalışan Python sanal ortamının bin dizininde Piper ara."""
    found = shutil.which("piper")
    if found:
        return found
    candidate = os.path.join(os.path.dirname(os.path.abspath(os.sys.executable)), "piper")
    if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    return None


class PiperSynthesisWorker(QThread):
    finished_audio = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, text, model_path, parent=None):
        super().__init__(parent)
        self.text = text
        self.model_path = model_path
        self.output_path = None

    def run(self):
        piper = find_piper()
        if not piper:
            self.failed.emit(
                "Piper komutu bulunamadı. Aktif sanal ortamda 'pip install piper-tts' kur."
            )
            return

        if not os.path.isfile(self.model_path):
            self.failed.emit(f"Türkçe Piper modeli bulunamadı:\n{self.model_path}")
            return

        config_path = self.model_path + ".json"
        if not os.path.isfile(config_path):
            self.failed.emit(f"Piper model yapılandırması bulunamadı:\n{config_path}")
            return

        fd, self.output_path = tempfile.mkstemp(prefix="kavram_tts_", suffix=".wav")
        os.close(fd)
        try:
            # Popen kullanımı, kullanıcı Alt+X ile sentez sürerken de durdurabilsin diye.
            with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as error_log:
                process = subprocess.Popen(
                    [piper, "--model", self.model_path, "--output_file", self.output_path],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=error_log,
                    text=True,
                )
                try:
                    process.stdin.write(self.text)
                    process.stdin.close()
                except Exception:
                    pass

                while process.poll() is None:
                    if self.isInterruptionRequested():
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        self._cleanup()
                        return
                    self.msleep(100)

                error_log.seek(0)
                error_text = error_log.read().strip()

            if self.isInterruptionRequested():
                self._cleanup()
                return
            if process.returncode != 0 or not os.path.isfile(self.output_path):
                detail = error_text or "Bilinmeyen Piper hatası"
                self._cleanup()
                self.failed.emit(detail[-2500:])
                return
            self.finished_audio.emit(self.output_path)
        except Exception as exc:
            self._cleanup()
            self.failed.emit(str(exc))

    def _cleanup(self):
        if self.output_path and os.path.isfile(self.output_path):
            try:
                os.remove(self.output_path)
            except OSError:
                pass
