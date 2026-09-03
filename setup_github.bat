@echo off
chcp 65001 > nul
echo ========================================================
echo   Загрузка бота в GitHub (tonipogozhev1234-coder)
echo ========================================================
echo.

set REPO_NAME=school-chat-moderator-bot
set /p REPO_INPUT="Введите имя репозитория на GitHub (по умолчанию %REPO_NAME%): "
if not "%REPO_INPUT%"=="" set REPO_NAME=%REPO_INPUT%

echo.
echo 1. Инициализация Git и добавление файлов...
git init
git add .
git commit -m "feat: школьный бот-модератор с бальной системой и мутами"

echo.
echo 2. Привязка удаленного репозитория...
git remote remove origin >nul 2>&1
git remote add origin https://github.com/tonipogozhev1234-coder/%REPO_NAME%.git
git branch -M main

echo.
echo 3. Отправка на GitHub...
echo Если репозиторий еще не создан, создайте его на https://github.com/new с именем: %REPO_NAME%
echo.
git push -u origin main

if %ERRORLEVEL% equ 0 (
    echo.
    echo [УСПЕХ] Проект успешно опубликован на GitHub!
    echo Ссылка: https://github.com/tonipogozhev1234-coder/%REPO_NAME%
) else (
    echo.
    echo [ВНИМАНИЕ] Не удалось выполнить git push.
    echo Убедитесь, что репозиторий создан на GitHub: https://github.com/new
)
pause
