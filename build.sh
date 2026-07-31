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

echo "== Run translator =="
python3 main.py

echo "== Save artifact =="

mkdir -p /kaggle/working/artifact

if [ -d output ]; then
    cp -r output/* /kaggle/working/artifact/
else
    echo "Folder output tidak ditemukan."
fi

echo "Selesai!"
echo "Artifact ada di:"
echo "/kaggle/working/artifact"