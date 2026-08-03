#!/usr/bin/env bash
set -e

echo "== Manga Auto Translator =="

echo "== Update package =="
sudo apt-get update

echo "== Install system dependencies =="
sudo apt-get install -y \
    fonts-liberation \
    libgl1 \
    libglib2.0-0

echo "== Upgrade pip =="
python3 -m pip install --upgrade pip

echo "== Install Python dependencies =="
pip3 install -r requirements.txt

echo "== Build and Install Rust Modules =="
pip3 install maturin numpy opencv-python

echo "1. Build font_style_rs"
cd font_style_rs
maturin build --release
pip3 install target/wheels/*.whl
cd ..

echo "2. Build typeset_rs"
cd typeset_rs
maturin build --release
pip3 install target/wheels/*.whl
cd ..

echo "== Run translator =="
python3 main.py

echo "== Save artifact =="

mkdir -p /kaggle/working/artifact

if [ -d output ]; then
    echo "Menyalin output..."
    cp -r output/* /kaggle/working/artifact/
else
    echo "Folder output tidak ditemukan."
fi

if [ -d ai_logs ]; then
    echo "Menyalin ai_logs..."
    mkdir -p /kaggle/working/artifact/ai_logs
    cp -r ai_logs/* /kaggle/working/artifact/ai_logs/
else
    echo "Folder ai_logs tidak ditemukan."
fi

echo "Selesai!"
echo "Artifact ada di:"
echo "/kaggle/working/artifact"
