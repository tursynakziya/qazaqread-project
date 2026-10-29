#!/usr/bin/env bash
# Render build command: ./build.sh
# Start command:        gunicorn config.wsgi --workers 1 --threads 8 --timeout 120
#   (one worker: live speech recognisers are kept in that process's memory)
set -o errexit

pip install -r requirements.txt

# Kazakh speech model (60 MB) is not in git; download it once per build.
MODEL=vosk-model-small-kz-0.42
if [ ! -d "models/$MODEL" ]; then
  mkdir -p models
  curl -sSL -o models/kz.zip "https://alphacephei.com/vosk/models/$MODEL.zip"
  python -c "import zipfile; zipfile.ZipFile('models/kz.zip').extractall('models')"
  rm models/kz.zip
fi

python manage.py collectstatic --no-input
python manage.py migrate
