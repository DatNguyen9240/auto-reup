import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import sys
import asyncio
import typer
from pathlib import Path

# Add project root to sys.path to allow imports when executed from other working directories
project_root = str(Path(__file__).resolve().parents[1])
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from app.core.pipeline import PipelineRunner
from app.utils.logger import configure_logging, get_logger
from app.config import settings

app = typer.Typer(help="AutoTool Backend - Automated Video Translation & Voiceover Engine.")
logger = get_logger("CLI")

@app.command()
def process(
    input_video: Path = typer.Option(..., "--input", "-i", help="Path to raw input video file"),
    tone: str = typer.Option("review_phim", "--tone", "-t", help="Translation style or tone (e.g. review_phim, funny)"),
    voice: str = typer.Option(settings.default_voice, "--voice", "-v", help="Edge-TTS voice identifier"),
    rate: str = typer.Option(settings.default_rate, "--rate", help="Speaking rate offset (e.g., +0%, +15%)"),
    pitch: str = typer.Option(settings.default_pitch, "--pitch", help="Speaking pitch offset (e.g., +0Hz)"),
    bgm: str = typer.Option(None, "--bgm", help="BGM filename (e.g. 'funny') or absolute path to audio"),
    logo: Path = typer.Option(None, "--logo", help="Path to brand watermark logo PNG image"),
    mask: bool = typer.Option(True, "--mask/--no-mask", help="Mask original hardsub subtitles at the bottom center of the frame")
):
    """Processes horizontal video input: translates, synthesizes voiceovers, loops BGM, applies sidechain ducking, and crops to 9:16 vertical."""
    configure_logging()
    
    if not input_video.exists():
        typer.echo(f"Error: Input video file not found at: {input_video}", err=True)
        raise typer.Exit(code=1)
        
    if not os.environ.get("GEMINI_API_KEY") and not settings.gemini_api_key:
        typer.echo("Warning: GEMINI_API_KEY environment variable is missing. LLM steps will fail unless translation fallback is enabled.", err=True)
        
    # Generate unique job ID based on the input filename
    job_id = f"job_{input_video.stem}"
    projects_dir = Path("./projects")
    
    runner = PipelineRunner(projects_dir)
    
    # Resumption check
    job = runner.store.load_job(job_id)
    if job:
        typer.echo(f"Resuming existing job: {job_id} (last step: {job.current_step}, status: {job.status})")
    else:
        typer.echo(f"Creating new job: {job_id} for input video...")
        job = runner.create_job(input_video, job_id)
        
    try:
        asyncio.run(runner.run(
            job_id=job_id,
            tone=tone,
            voice=voice,
            rate=rate,
            pitch=pitch,
            bgm_name=bgm,
            logo_path=logo,
            mask_subtitle=mask
        ))
        typer.echo(f"\n[SUCCESS] Final portrait 9:16 video rendered to: {job.output_path}")
        typer.echo(f"[SUCCESS] AI-generated TikTok/Reels caption saved to: {Path(job.output_path).parent / 'caption.txt'}")
    except Exception as e:
        typer.echo(f"\n[ERROR] Pipeline run failed: {e}", err=True)
        typer.echo("[INFO] You can run the exact same command to resume from the last successful checkpoint.", err=True)
        raise typer.Exit(code=1)

if __name__ == "__main__":
    app()
