"""Grabación automática de reuniones: detectarlas, grabarlas y guardarlas."""
from neonwhisper.meetings.detector import Meeting as DetectedMeeting, MeetingDetector
from neonwhisper.meetings.recorder import (
    MeetingRecorder, Source, device_label, find_loopback_device, read_wav, wav_duration,
)
from neonwhisper.meetings.store import Meeting, MeetingStore

__all__ = [
    "DetectedMeeting", "Meeting", "MeetingDetector", "MeetingRecorder", "MeetingStore", "Source",
    "device_label", "find_loopback_device", "read_wav", "wav_duration",
]
