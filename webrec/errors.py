"""webrec 전역 예외 정의."""


class WebrecError(Exception):
    """webrec 에서 발생하는 모든 오류의 기반 클래스."""


class ConfigError(WebrecError):
    """설정 파일이 잘못되었을 때."""


class ToolMissingError(WebrecError):
    """ffmpeg/ffprobe/yt-dlp 등 외부 도구를 찾지 못했을 때."""


class CaptureError(WebrecError):
    """실제 녹화(캡처) 과정에서 실패했을 때."""


class VerificationError(WebrecError):
    """녹화 결과물 검증에 실패했을 때."""


class PreflightError(WebrecError):
    """시작 전 샘플링(사전 점검)에 실패했을 때."""


class NotifyError(WebrecError):
    """메일 발송에 실패했을 때."""
