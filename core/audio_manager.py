"""Audio Manager - plays sound alerts."""
import os
import threading
from core.logger import get_logger

log = get_logger()

try:
    import winsound
    HAS_WINSOUND = True
except ImportError:
    HAS_WINSOUND = False


class AudioManager:
    """Play WAV sound alerts for scan events."""

    SOUNDS = {
        "start": "scan_start.wav",
        "end": "scan_end.wav",
        "cancel": "scan_cancel.wav",
        "duplicate": "scan_duplicate.wav",
        "error": "error.wav",
    }

    def __init__(self, audio_dir: str, enabled: bool = True, volume: int = 80):
        self.audio_dir = audio_dir
        self.enabled = enabled
        self.volume = volume
        os.makedirs(audio_dir, exist_ok=True)
        self._create_default_sounds()

    def _create_default_sounds(self):
        """Create simple beep WAV files if they don't exist."""
        import struct, wave
        for name, filename in self.SOUNDS.items():
            filepath = os.path.join(self.audio_dir, filename)
            if os.path.exists(filepath):
                continue
            try:
                self._generate_beep(filepath, name)
            except Exception:
                pass

    def _generate_beep(self, filepath: str, sound_type: str):
        """Generate a simple beep WAV file."""
        import struct, wave, math
        sample_rate = 22050
        duration = 0.3
        freq_map = {"start": 880, "end": 660, "cancel": 440, "duplicate": 330, "error": 220}
        freq = freq_map.get(sound_type, 440)
        n_samples = int(sample_rate * duration)
        samples = []
        for i in range(n_samples):
            t = i / sample_rate
            fade = min(1.0, (n_samples - i) / (sample_rate * 0.05))
            value = int(16000 * math.sin(2 * math.pi * freq * t) * fade)
            samples.append(struct.pack('<h', max(-32768, min(32767, value))))

        with wave.open(filepath, 'w') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            wf.writeframes(b''.join(samples))

    def play(self, sound_name: str):
        if not self.enabled:
            return
        filename = self.SOUNDS.get(sound_name, f"{sound_name}.wav")
        filepath = os.path.join(self.audio_dir, filename)
        if not os.path.exists(filepath):
            # Fallback to system beep
            if HAS_WINSOUND:
                freq_map = {"start": 880, "end": 660, "cancel": 440, "duplicate": 330, "error": 220}
                threading.Thread(
                    target=lambda: winsound.Beep(freq_map.get(sound_name, 440), 200),
                    daemon=True
                ).start()
            return
        self._play_file(filepath)

    def _play_file(self, filepath: str):
        try:
            if HAS_WINSOUND:
                winsound.PlaySound(filepath, winsound.SND_FILENAME | winsound.SND_NODEFAULT | winsound.SND_ASYNC)
        except Exception as e:
            log.error(f"[Audio] Play error: {e}")
