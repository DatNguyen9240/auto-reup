class AutoToolError(Exception):
    """Base exception for all AutoTool errors."""
    pass

class MediaAnalyzerError(AutoToolError):
    """Raised when media metadata probing fails."""
    pass

class AudioExtractionError(AutoToolError):
    """Raised when FFmpeg audio extraction fails."""
    pass

class TranslationError(AutoToolError):
    """Raised when translation provider errors out."""
    pass

class TTSError(AutoToolError):
    """Raised when Text-to-Speech voice generation fails."""
    pass

class AudioMixingError(AutoToolError):
    """Raised when audio mixing fails."""
    pass

class RenderError(AutoToolError):
    """Raised when FFmpeg video rendering fails."""
    pass
