import re
from typing import List, Dict, Any, Optional
from app.schemas.ai_schema import AISpeechSegment

# 1. Kính ngữ / Luật bắt buộc (Mandatory Rules)
# Nhân viên telesales bắt buộc phải có các từ chào hỏi và cảm ơn/chào tạm biệt trong kịch bản cuộc gọi.
MANDATORY_RULES = {
    "greeting": {
        "pattern": r"(chào\s+(anh|chị|em|quý\s+khách|bác|cô|chú|ông|bà))|(dạ\s+(em|cháu)\s+chào)|(kính\s+chào)",
        "description": "Lời chào hỏi lịch sự ở đầu cuộc gọi",
        "severity": "high",
        "deduction": 15.0
    },
    "closing": {
        "pattern": r"(cảm\s+ơn)|(chào\s+tạm\s+biệt)|(hẹn\s+gặp\s+lại)|(chúc\s+(anh|chị|em|quý\s+khách|bác|cô|chú|ông|bà))",
        "description": "Lời cảm ơn hoặc chào tạm biệt khi kết thúc cuộc gọi",
        "severity": "medium",
        "deduction": 10.0
    }
}

# 2. Từ khóa cấm / Tiêu cực / Không chuẩn mực (Forbidden Rules)
# Phát hiện các vi phạm về hành vi, ép buộc, xưng hô hoặc ngôn từ phản cảm.
FORBIDDEN_RULES = [
    {
        "pattern": r"(lừa\s+đảo|lừa\s+gạt|bịp|dụ\s+dỗ|dối\s+trá|nói\s+dối)",
        "description": "Từ ngữ nhạy cảm liên quan đến gian lận, lừa dối",
        "severity": "high",
        "type": "sensitive_keyword",
        "deduction": 20.0
    },
    {
        "pattern": r"(ép\s+buộc|bắt\s+buộc|phải\s+mua|đe\s+dọa|không\s+mua\s+thì\s+thôi)",
        "description": "Thái độ ép buộc, đe dọa hoặc thúc ép khách hàng",
        "severity": "high",
        "type": "forced_selling",
        "deduction": 20.0
    },
    {
        "pattern": r"(đéo|vcl|đm|vãi|mày|tao|ngu|ngốc|hâm|dở|vớ\s+vẩn|luyên\s+thuyên|lảm\s+nhảm)",
        "description": "Từ ngữ thiếu tôn trọng, xưng hô thiếu chuẩn mực hoặc thô tục",
        "severity": "high",
        "type": "abusive_language",
        "deduction": 25.0
    },
    {
        "pattern": r"(không\s+biết|chịu|tự\s+đi\s+mà\s+làm|tôi\s+không\s+quan\s+tâm|kệ|mặc\s+kệ)",
        "description": "Thái độ thờ ơ, thiếu trách nhiệm hoặc từ chối hỗ trợ khách hàng",
        "severity": "medium",
        "type": "negative_attitude",
        "deduction": 10.0
    }
]


def _has_explicit_speakers(segments: List[AISpeechSegment]) -> bool:
    return any(
        (segment.speaker or "").strip().lower() in {"agent", "customer"}
        for segment in segments
    )


def _segments_for_agent_rules(
    segments: Optional[List[AISpeechSegment]],
) -> Optional[List[AISpeechSegment]]:
    """Use agent speech when diarization exists; otherwise keep all ASR segments."""
    if not segments:
        return None
    if not _has_explicit_speakers(segments):
        return segments
    return [
        segment
        for segment in segments
        if (segment.speaker or "").strip().lower() == "agent"
    ]

def analyze_transcript(
    transcript: str, 
    segments: Optional[List[AISpeechSegment]] = None
) -> Dict[str, Any]:
    """
    Phân tích nội dung bóc băng sử dụng Regex Rules.
    Nếu có danh sách segments từ mô hình AI, hệ thống sẽ xác định chính xác timestamp theo từng câu nói của agent.
    """
    violations = []
    compliance_score = 100.0
    text_lower = transcript.lower()
    agent_segments = _segments_for_agent_rules(segments)
    if segments and _has_explicit_speakers(segments):
        rules_text = " ".join(segment.text for segment in agent_segments or [])
    else:
        rules_text = transcript
    rules_text_lower = rules_text.lower()

    # 1. Kiểm tra các luật bắt buộc (Nếu thiếu sẽ bị trừ điểm)
    for rule_name, rule_info in MANDATORY_RULES.items():
        pattern = rule_info["pattern"]
        if not re.search(pattern, rules_text_lower):
            compliance_score -= rule_info["deduction"]
            violations.append({
                "violation_type": f"missing_{rule_name}",
                "keyword_detected": None,
                "snippet": f"Thiếu: {rule_info['description']}",
                "timestamp": 0.0,
                "severity": rule_info["severity"],
                "deduction": rule_info["deduction"],
            })

    # 2. Kiểm tra từ cấm
    if segments:
        # Nếu có segments chi tiết từ AI -> Phân tích theo từng câu
        for seg in agent_segments or []:
            seg_text_lower = seg.text.lower()
            for rule in FORBIDDEN_RULES:
                matches = re.finditer(rule["pattern"], seg_text_lower)
                for match in matches:
                    keyword = match.group()
                    compliance_score -= rule["deduction"]
                    violations.append({
                        "violation_type": rule["type"],
                        "keyword_detected": keyword,
                        "snippet": f"[{seg.speaker.upper() if seg.speaker else 'SPEAKER'}]: {seg.text}",
                        "timestamp": round(seg.start_time, 2),
                        "severity": rule["severity"],
                        "deduction": rule["deduction"],
                    })
    else:
        # Nếu chỉ có chuỗi văn bản thô
        for rule in FORBIDDEN_RULES:
            matches = re.finditer(rule["pattern"], text_lower)
            for match in matches:
                keyword = match.group()
                start_idx = match.start()
                start_snippet = max(0, start_idx - 30)
                end_snippet = min(len(transcript), start_idx + len(keyword) + 30)
                snippet = transcript[start_snippet:end_snippet].strip()
                
                compliance_score -= rule["deduction"]
                violations.append({
                    "violation_type": rule["type"],
                    "keyword_detected": keyword,
                    "snippet": f"...{snippet}...",
                    "timestamp": round(start_idx / 15.0, 2),
                    "severity": rule["severity"],
                    "deduction": rule["deduction"],
                })

    # Điểm tuân thủ tối thiểu là 0.0
    compliance_score = max(0.0, round(compliance_score, 2))

    return {
        "compliance_score": compliance_score,
        "violations": violations
    }
