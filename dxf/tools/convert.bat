@echo off
rem Usage:   convert.bat INPUT_FOLDER OUTPUT_FOLDER
rem Example: convert.bat C:\Users\USER\Downloads\DXF_ENG C:\Users\USER\Downloads\DXF_ENG\EN
set PYTHONUTF8=1
python "%~dp0translate_all.py" %1 %2
if %errorlevel%==2 echo Missing terms: fill in OUTPUT_FOLDER\missing_terms.csv and add them to glossary.csv
pause
