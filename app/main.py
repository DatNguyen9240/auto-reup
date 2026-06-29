import os
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

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
    input_video: str = typer.Option(..., "--input", "-i", help="Path to raw input video file or Douyin/TikTok URL"),
    tone: str = typer.Option("review_phim", "--tone", "-t", help="Translation style or tone (e.g. review_phim, funny)"),
    voice: str = typer.Option(settings.default_voice, "--voice", "-v", help="Edge-TTS voice identifier"),
    rate: str = typer.Option(settings.default_rate, "--rate", help="Speaking rate offset (e.g., +0%, +15%)"),
    pitch: str = typer.Option(settings.default_pitch, "--pitch", help="Speaking pitch offset (e.g., +0Hz)"),
    bgm: str = typer.Option(None, "--bgm", help="BGM filename (e.g. 'funny') or absolute path to audio"),
    logo: Path = typer.Option(None, "--logo", help="Path to brand watermark logo PNG image"),
    mask: bool = typer.Option(True, "--mask/--no-mask", help="Mask original hardsub subtitles at the bottom center of the frame")
):
    """Processes horizontal video input or URL: translates, synthesizes voiceovers, loops BGM, applies sidechain ducking, and crops to 9:16 vertical."""
    configure_logging()
    
    is_url = input_video.startswith("http://") or input_video.startswith("https://")
    
    if not is_url:
        input_path = Path(input_video)
        if not input_path.exists():
            typer.echo(f"Error: Input video file not found at: {input_video}", err=True)
            raise typer.Exit(code=1)
        job_id = f"job_{input_path.stem}"
    else:
        import hashlib
        url_hash = hashlib.md5(input_video.encode('utf-8')).hexdigest()[:8]
        job_id = f"job_url_{url_hash}"
        
    if not os.environ.get("GEMINI_API_KEY") and not settings.gemini_api_key:
        typer.echo("Warning: GEMINI_API_KEY environment variable is missing. LLM steps will fail unless translation fallback is enabled.", err=True)
        
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

@app.command(name="get-cookies")
def get_cookies(
    output: Path = typer.Option(Path("./cookies.txt"), "--output", "-o", help="Path to save cookies.txt file")
):
    """Automatically generate Douyin cookies via Playwright."""
    configure_logging()
    logger.info("Generating Douyin cookies automatically...")
    from app.services.downloader import auto_generate_douyin_cookies
    
    output_path = Path(output).resolve()
    success = auto_generate_douyin_cookies(output_path)
    if success:
        typer.echo(f"\n[SUCCESS] Cookies generated successfully and saved to: {output_path}")
    else:
        typer.echo("\n[ERROR] Failed to generate cookies automatically.", err=True)
        raise typer.Exit(code=1)

@app.command(name="export-cookies")
def export_cookies(
    output: Path = typer.Option(Path("./cookies.txt"), "--output", "-o", help="Path to save cookies.txt file")
):
    """Export Douyin cookies from local installed browsers (Chrome, Edge, Firefox, Brave, Opera)."""
    configure_logging()
    logger.info("Exporting Douyin cookies from local browsers...")
    from app.services.downloader import export_cookies_from_browser
    
    output_path = Path(output).resolve()
    success = export_cookies_from_browser(output_path)
    if success:
        typer.echo(f"\n[SUCCESS] Cookies exported successfully and saved to: {output_path}")
    else:
        typer.echo("\n[ERROR] Failed to export cookies from any local browser.", err=True)
        typer.echo("[INFO] Please ensure the targeted browser is closed completely before running.", err=True)
        raise typer.Exit(code=1)

@app.command(name="server")
def run_server(
    host: str = typer.Option("127.0.0.1", "--host", "-h", help="API server bind host"),
    port: int = typer.Option(8000, "--port", "-p", help="API server bind port"),
    reload: bool = typer.Option(False, "--reload", help="Enable live auto-reload on code change")
):
    """Start the FastAPI backend server and serve the Web UI dashboard."""
    configure_logging()
    logger.info(f"Starting API server on http://{host}:{port} ...")
    
    import uvicorn
    if reload:
        uvicorn.run("app.server:app", host=host, port=port, reload=True)
    else:
        from app.server import app as fastapi_app
        uvicorn.run(fastapi_app, host=host, port=port)

if __name__ == "__main__":
    app()


