"""Grabación automática de reuniones: detectarlas, grabarlas y guardarlas."""
from neonwhisper.meetings.detector import Meeting as DetectedMeeting, MeetingDetector
from neonwhisper.meetings.recorder import (
    MeetingRecorder, Source, device_label, find_loopback_device, open_system_audio, read_wav, wav_duration,
)
from neonwhisper.meetings.system_audio import default_speaker_name, list_speakers, open_system_source
from neonwhisper.meetings.store import Meeting, MeetingStore

__all__ = [
    "DetectedMeeting", "Meeting", "MeetingDetector", "MeetingRecorder", "MeetingStore", "Source",
    "default_speaker_name", "device_label", "find_loopback_device", "list_speakers",
    "open_system_audio", "open_system_source", "read_wav", "wav_duration",
]
