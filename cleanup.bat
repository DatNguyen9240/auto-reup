@echo off
echo =======================================================
echo   AUTO-REUP PROJECT CLEANUP ^& REORGANIZATION
echo =======================================================
echo.
echo This script will reorganize files and remove redundant logic
echo to clean up the project structure.
echo.

rem Create docs directory if it doesn't exist
if not exist docs (
    echo Creating docs folder...
    mkdir docs
)

rem Move documentation files to the docs folder
echo Moving documentation files...
if exist IDEA.docx (
    move IDEA.docx docs\IDEA.docx >nul
    echo   [Moved] IDEA.docx to docs\
)
if exist features_and_usage.md (
    move features_and_usage.md docs\features_and_usage.md >nul
    echo   [Moved] features_and_usage.md to docs\
)
if exist implementation_workflow.md (
    move implementation_workflow.md docs\implementation_workflow.md >nul
    echo   [Moved] implementation_workflow.md to docs\
)

rem Remove obsolete and redundant scripts
echo Removing redundant/unused scripts...
if exist get_douyin_cookies.py (
    del get_douyin_cookies.py
    echo   [Deleted] get_douyin_cookies.py
)
if exist export_cookies.py (
    del export_cookies.py
    echo   [Deleted] export_cookies.py
)
if exist pyinstxtractor.py (
    del pyinstxtractor.py
    echo   [Deleted] pyinstxtractor.py
)
if exist app\utils\app_paths.py (
    del app\utils\app_paths.py
    echo   [Deleted] app\utils\app_paths.py
)
if exist playwright_screenshot.png (
    del playwright_screenshot.png
    echo   [Deleted] playwright_screenshot.png
)
if exist config\local_app_config.json (
    del config\local_app_config.json
    echo   [Deleted] config\local_app_config.json
)
if exist config (
    rmdir config
    echo   [Deleted] config/ folder
)


echo.
echo =======================================================
echo Cleanup completed successfully!
echo =======================================================
echo.
pause
