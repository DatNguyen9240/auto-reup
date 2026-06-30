import os
import math
from pathlib import Path
from typing import List
from pydub import AudioSegment
from app.models.segment import Segment
from app.core.errors import AudioMixingError
from app.utils.logger import get_logger

logger = get_logger("AudioMixer")

class AudioMixer:
    def mix(
        self,
        original_audio_path: Path,
        segments: List[Segment],
        output_mixed_path: Path,
        bgm_path: Path = None,
        original_volume: float = 0.25,
        tts_volume: float = 1.0,
        bgm_volume: float = 0.08,
        ducking_attenuation_db: float = -12.0,
        video_duration_ms: int = None
    ) -> Path:
        """Mixes original video audio, looped background music (BGM), and TTS voiceover tracks.
        Applies a ducking envelope to reduce background volume (original audio + BGM) during speech segments.
        """
        logger.info("Mixing audio tracks with pydub...")
        try:
            # 1. Load original audio
            original = None
            if original_audio_path and os.path.exists(original_audio_path) and os.path.getsize(original_audio_path) > 0:
                try:
                    original = AudioSegment.from_wav(str(original_audio_path))
                except Exception as e:
                    logger.warning(f"Failed to load original audio from {original_audio_path}: {e}")

            # Calculate base duration
            duration_ms = len(original) if original else 0
            if video_duration_ms and video_duration_ms > duration_ms:
                duration_ms = video_duration_ms

            # Also check if any TTS segment goes beyond duration_ms
            max_tts_ms = 0
            for s in segments:
                if s.tts_path and os.path.exists(s.tts_path) and os.path.getsize(s.tts_path) > 0:
                    try:
                        speech_seg = AudioSegment.from_wav(s.tts_path)
                        end_pos = s.start_ms + len(speech_seg)
                        if end_pos > max_tts_ms:
                            max_tts_ms = end_pos
                    except Exception as e:
                        logger.warning(f"Failed to check duration of TTS segment {s.id}: {e}")
            
            if max_tts_ms > duration_ms:
                duration_ms = max_tts_ms + 1000  # add 1s padding

            # Initialize original silent track if none existed or is shorter
            if not original:
                original = AudioSegment.silent(duration=duration_ms)
                original_volume = 0.0
            elif len(original) < duration_ms:
                silence_needed = duration_ms - len(original)
                original = original + AudioSegment.silent(duration=silence_needed)
                
            # Apply volume scaling to original audio
            if original_volume > 0:
                original_db = 20 * math.log10(original_volume)
                original = original + original_db
            else:
                original = AudioSegment.silent(duration=len(original))
            tts_track = AudioSegment.silent(duration=duration_ms)
            has_speech = False
            speech_intervals = []
            
            # 2. Overlay TTS segments and track active speaking intervals
            for s in segments:
                if s.tts_path and os.path.exists(s.tts_path) and os.path.getsize(s.tts_path) > 0:
                    try:
                        speech_seg = AudioSegment.from_wav(s.tts_path)
                        # Apply volume scaling to TTS voiceover
                        if tts_volume != 1.0 and tts_volume > 0:
                            tts_db = 20 * math.log10(tts_volume)
                            speech_seg = speech_seg + tts_db
                        
                        tts_track = tts_track.overlay(speech_seg, position=s.start_ms)
                        has_speech = True
                        
                        # Track start/end boundaries
                        speech_intervals.append((s.start_ms, s.start_ms + len(speech_seg)))
                    except Exception as e:
                        logger.warning(f"Failed to load TTS segment {s.id} from {s.tts_path}: {e}")

            # 3. Load and loop Background Music (BGM)
            bgm = None
            if bgm_path and os.path.exists(bgm_path) and os.path.getsize(bgm_path) > 0:
                try:
                    # from_file supports mp3/wav/etc.
                    bgm = AudioSegment.from_file(str(bgm_path))
                    # Loop BGM to cover the entire duration of the original video
                    if len(bgm) < duration_ms:
                        loop_count = (duration_ms // len(bgm)) + 1
                        bgm = bgm * loop_count
                    bgm = bgm[:duration_ms]
                    
                    # Apply volume scaling to BGM
                    if bgm_volume > 0:
                        bgm_db = 20 * math.log10(bgm_volume)
                        bgm = bgm + bgm_db
                    else:
                        bgm = AudioSegment.silent(duration=duration_ms)
                except Exception as e:
                    logger.warning(f"Could not load BGM file {bgm_path}: {e}. Proceeding without BGM.")

            # 4. Stitch background audio with sidechain ducking during speaking intervals
            if has_speech and ducking_attenuation_db != 0:
                # Merge original track and BGM to build the basic background track
                bg_track = original
                if bgm:
                    bg_track = bg_track.overlay(bgm)
                
                # Create a ducked copy of the background track
                ducked_bg_track = bg_track + ducking_attenuation_db
                
                # Consolidate overlapping or closely spaced speech intervals (merge gaps under 2.5 seconds)
                speech_intervals.sort()
                merged_intervals = []
                merge_threshold_ms = 2500  # 2.5 seconds threshold to prevent rapid BGM ducking fluctuations
                for start, end in speech_intervals:
                    if not merged_intervals:
                        merged_intervals.append([start, end])
                    else:
                        prev_start, prev_end = merged_intervals[-1]
                        if start <= prev_end + merge_threshold_ms:
                            merged_intervals[-1][1] = max(prev_end, end)
                        else:
                            merged_intervals.append([start, end])
                
                # Stitch ducked and unducked audio chunks together with smooth crossfades
                # Initial segment (before first speech)
                first_start = merged_intervals[0][0]
                final_bg = bg_track[0:first_start] if first_start > 0 else AudioSegment.silent(duration=0)
                
                for idx, (start, end) in enumerate(merged_intervals):
                    start = max(0, min(start, duration_ms))
                    end = max(0, min(end, duration_ms))
                    
                    # Ducked background segment
                    ducked_chunk = ducked_bg_track[start:end]
                    
                    # Crossfade into ducked segment (300ms transition)
                    if len(final_bg) > 0 and len(ducked_chunk) > 300:
                        final_bg = final_bg.append(ducked_chunk, crossfade=300)
                    else:
                        final_bg += ducked_chunk
                        
                    # Find start of next speech segment or end of video
                    next_start = merged_intervals[idx+1][0] if idx < len(merged_intervals) - 1 else duration_ms
                    next_start = max(0, min(next_start, duration_ms))
                    
                    if next_start > end:
                        unducked_chunk = bg_track[end:next_start]
                        # Crossfade back to normal volume (500ms transition)
                        if len(final_bg) > 0 and len(unducked_chunk) > 500:
                            final_bg = final_bg.append(unducked_chunk, crossfade=500)
                        else:
                            final_bg += unducked_chunk
                
                # Overlay voiceover track
                final_audio = final_bg.overlay(tts_track)
            else:
                # No speech or ducking is set to 0. Simply overlay all tracks
                final_audio = original
                if bgm:
                    final_audio = final_audio.overlay(bgm)
                final_audio = final_audio.overlay(tts_track)

            # Export output to WAV
            output_mixed_path.parent.mkdir(parents=True, exist_ok=True)
            final_audio.export(str(output_mixed_path), format="wav")
            logger.info(f"Mixed audio saved to: {output_mixed_path}")
            return output_mixed_path
            
        except Exception as e:
            logger.error(f"Failed to mix audio tracks: {e}")
            raise AudioMixingError(f"Audio mixing failed: {e}")
