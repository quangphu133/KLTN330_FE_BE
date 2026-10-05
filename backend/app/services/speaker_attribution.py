import re
import unicodedata
from typing import Any, Dict, Iterable, List, Optional


def configured_agent_channel(value: Any) -> int:
    try:
        channel = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("DEFAULT_AGENT_CHANNEL must be 0 or 1") from exc
    if channel not in (0, 1):
        raise ValueError("DEFAULT_AGENT_CHANNEL must be 0 or 1")
    return channel


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text).casefold()).strip()


def _opening_texts(segments: Iterable[Dict[str, Any]], channel: int) -> List[str]:
    texts = [
        str(segment.get("text") or "").strip()
        for segment in segments
        if segment.get("channel") == channel and str(segment.get("text") or "").strip()
    ]
    if not texts:
        return []
    joined = " ".join(texts)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", joined) if part.strip()]
    return sentences[:2] if len(sentences) > 1 or re.search(r"[.!?]", joined) else texts[:2]


def _is_employee_opening(text: str, organizations: Iterable[str]) -> bool:
    normalized = _normalize(text)
    if not normalized or normalized.startswith(('"', "'", "“", "‘", "«")):
        return False
    if re.match(r"^(?:khách|hệ thống|tự động|ivr|ghi âm|bản ghi|nghe lại)\b", normalized):
        return False
    if re.search(r"\b(?:khách nói|khách hỏi|nhắc lại|trích dẫn|theo lời|hệ thống phát|tự động phát)\b", normalized):
        return False
    punctuation = r"(?:\b|[,!.?])"
    patterns = [
        r"^(?:dạ\s+)?tổng đài(?:\s+[\w.-]+){1,5}\s+xin\s+(?:chào|nghe)" + punctuation,
        r"^(?:dạ\s+)?em\s+có\s+thể\s+hỗ\s+trợ\s+gì" + punctuation,
    ]
    for organization in organizations:
        name = re.escape(_normalize(organization))
        if name:
            patterns.append(
                r"^(?:dạ\s+)?" + name + r"(?:\s+[\w.-]+){0,4}\s+(?:xin\s+nghe|nghe)" + punctuation
            )
    return any(re.search(pattern, normalized) for pattern in patterns)


def build_stereo_attribution(
    segments: List[Dict[str, Any]],
    audio_metadata: Optional[Dict[str, Any]],
    channel_quality: Optional[Dict[str, Any]],
    default_channel: Any,
    auto_confirm: bool,
    organizations: Iterable[str],
) -> Dict[str, Any]:
    default_channel = configured_agent_channel(default_channel)
    metadata = audio_metadata or {}
    quality = channel_quality or {}
    eligible = (
        metadata.get("num_channels") == 2
        and quality.get("auto_role_eligible") is True
        and not quality.get("reasons")
    )
    channel_texts = {channel: _opening_texts(segments, channel) for channel in (0, 1)}
    eligible = eligible and all(channel_texts.values())
    hits = [
        channel
        for channel, texts in channel_texts.items()
        if any(_is_employee_opening(text, organizations) for text in texts)
    ] if eligible else []

    suggested_channel = hits[0] if len(hits) == 1 else default_channel
    source = "regex" if len(hits) == 1 else "default_config"
    confirmed = len(hits) == 1 and auto_confirm
    assignments = {
        f"CHANNEL_{channel}": "agent" if confirmed and channel == suggested_channel else
        "customer" if confirmed else "unknown"
        for channel in (0, 1)
    }
    return {
        "status": "confirmed" if confirmed else "pending",
        "source": source,
        "actor": "system",
        "agent_speaker_id": f"CHANNEL_{suggested_channel}" if confirmed else None,
        "suggested_agent_speaker_id": f"CHANNEL_{suggested_channel}",
        "agent_channel": suggested_channel if confirmed else None,
        "default_agent_channel": default_channel,
        "reason": "unique_employee_opening" if len(hits) == 1 else
        "no_unique_employee_opening" if eligible else "stereo_quality_ineligible",
        "evidence": {
            "channel": hits[0] if len(hits) == 1 else None,
            "sentence": next(
                (text for text in channel_texts[hits[0]] if _is_employee_opening(text, organizations)),
                None,
            ) if len(hits) == 1 else None,
        },
        "assignments": assignments,
    }
